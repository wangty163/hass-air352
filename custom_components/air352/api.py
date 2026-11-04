import asyncio
import hashlib
import hmac
import base64
import json
import logging
import time
import uuid
from email.utils import formatdate
from gzip import decompress as gzip_decompress
from urllib.parse import quote

import aiohttp

from .const import (
    APPID_352, BASE_URL_352, ALI_APP_KEY, ALI_APP_SECRET,
    ALI_DOMAIN, ALI_OA_DOMAIN, Z120_REFRESH_PROPERTY, Z120_REFRESH_VALUE,
)
from .mobile_protocol import (
    MobileTriple,
    build_aepauth_auth_info,
)

_LOGGER = logging.getLogger(__name__)


def _raise_if_service_unavailable(data: dict) -> None:
    """Do not mistake gateway/service errors for rejected account credentials."""
    code = data.get("code")
    message = str(data.get("message", data.get("localizedMsg", "")))
    try:
        server_error = int(code) == 429 or 500 <= int(code) <= 599
    except (TypeError, ValueError):
        server_error = False
    if server_error or any(word in message.lower() for word in (
        "timeout", "timed out", "service unavailable", "系统繁忙", "服务异常",
    )):
        raise Air352ApiError(code, "352 cloud service temporarily unavailable")


class Air352AuthError(Exception):
    pass


class Air352ConnectionError(Exception):
    pass


class Air352ApiError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        super().__init__(message)


class Air352ApiClient:

    def __init__(self, session: aiohttp.ClientSession, username: str, password: str):
        self._session = session
        self._username = username
        self._password = password
        self._access_token: str | None = None
        self._iot_token: str | None = None
        self._iot_refresh_token: str | None = None
        self._iot_token_ts: float = 0
        self._iot_token_expire: int = 0
        self.devices: list[dict] = []
        self._auth_lock = asyncio.Lock()
        self._auth_retry_after: float = 0
        self._auth_failure: Exception | None = None

    async def _request_json(self, method: str, url: str, **kwargs) -> dict:
        """Normalize transport failures without including credentials in errors."""
        try:
            async with self._session.request(
                method, url, timeout=aiohttp.ClientTimeout(total=15), **kwargs
            ) as resp:
                resp.raise_for_status()
                raw = await resp.read()
                if raw[:2] == b"\x1f\x8b":
                    raw = gzip_decompress(raw)
                data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
            return data
        except (aiohttp.ClientError, TimeoutError, OSError, ValueError) as err:
            raise Air352ConnectionError(
                f"352 cloud request failed ({type(err).__name__})"
            ) from err

    # ── 352 API helpers ──

    def _352_sign(self, path: str) -> tuple[str, str]:
        ts = str(int(time.time()))
        return ts, hashlib.md5((APPID_352 + path + ts).encode()).hexdigest()

    def _352_headers(self, path: str, token: str = "") -> dict:
        ts, sign = self._352_sign(path)
        return {
            "Content-Type": "application/json;charset=utf-8",
            "Authorization": f"Token {token}",
            "ts": ts,
            "sign": sign,
        }

    async def _352_request(self, method: str, path: str, json_data: dict | None = None) -> dict:
        url = BASE_URL_352 + path
        headers = self._352_headers(path, self._access_token or "")
        data = await self._request_json(method, url, headers=headers, json=json_data)
        if data.get("code") not in (0, 200):
            raise Air352ApiError(data.get("code", -1), data.get("message", "unknown"))
        return data

    # ── Alibaba IoT API Gateway helpers ──

    def _ali_gw_sign(self, method: str, path: str, params: dict, api_ver: str, iot_token: str | None = None) -> tuple[dict, bytes]:
        """Build signed request for api.link.aliyun.com (JSON body)."""
        req_id = str(uuid.uuid4())
        body_obj = {
            "id": req_id,
            "version": "1.0",
            "request": {"apiVer": api_ver, "language": "zh-CN"},
            "params": params,
        }
        if iot_token:
            body_obj["request"]["iotToken"] = iot_token
        body_bytes = json.dumps(body_obj).encode()

        nonce = str(uuid.uuid4())
        ts_ms = str(int(time.time() * 1000))
        ct = "application/json; charset=utf-8"
        accept = "application/json; charset=utf-8"
        content_md5 = base64.b64encode(hashlib.md5(body_bytes).digest()).decode()

        sign_headers = {"x-ca-key": ALI_APP_KEY, "x-ca-nonce": nonce, "x-ca-timestamp": ts_ms}
        sh_str = "".join(f"{k}:{v}\n" for k, v in sorted(sign_headers.items()))
        sts = f"{method}\n{accept}\n{content_md5}\n{ct}\n\n{sh_str}{path}"
        sig = base64.b64encode(hmac.new(ALI_APP_SECRET.encode(), sts.encode(), hashlib.sha1).digest()).decode()

        headers = {
            "content-type": ct, "accept": accept,
            "x-ca-key": ALI_APP_KEY, "x-ca-nonce": nonce, "x-ca-timestamp": ts_ms,
            "x-ca-signature": sig,
            "x-ca-signature-headers": ",".join(sorted(sign_headers.keys())),
            "x-ca-signature-method": "HmacSHA1",
            "content-md5": content_md5,
        }
        return headers, body_bytes

    _ALI_AUTH_ERROR_CODES = {401, 2001, 2002, 2459, 26101, 26102}

    async def _ali_gw_request(self, path: str, params: dict, api_ver: str = "1.0.2", iot_token: str | None = None, _retried: bool = False) -> dict:
        headers, body = self._ali_gw_sign("POST", path, params, api_ver, iot_token)
        url = f"https://{ALI_DOMAIN}{path}"
        data = await self._request_json("POST", url, headers=headers, data=body)
        code = data.get("code", -1)
        if code in (200,):
            return data
        msg = data.get("message", data.get("localizedMsg", "unknown"))
        _raise_if_service_unavailable(data)
        is_auth_error = code in self._ALI_AUTH_ERROR_CODES or any(
            word in msg.lower() for word in ("identity", "token", "session")
        )
        if is_auth_error and iot_token:
            if not _retried:
                _LOGGER.debug("IoT token invalid (code %s), refreshing authentication", code)
                # Another request may already have replaced this rejected token.
                if self._iot_token == iot_token:
                    self._iot_token = None
                await self.authenticate()
                return await self._ali_gw_request(path, params, api_ver, self._iot_token, _retried=True)
            raise Air352AuthError(f"Auth failed after retry: {code} {msg}")
        if code in self._ALI_AUTH_ERROR_CODES:
            # Bootstrap requests cannot refresh a token they do not have.
            raise Air352AuthError(f"352 cloud rejected authentication (code {code})")
        raise Air352ApiError(code, msg)

    async def _ali_oa_login(self, access_token: str) -> str:
        """Call loginbyoauth on living-account endpoint, return sid."""
        nonce = str(uuid.uuid4())
        ts_ms = str(int(time.time() * 1000))
        date_str = formatdate(timeval=None, localtime=False, usegmt=True)
        ct = "application/x-www-form-urlencoded; charset=utf-8"
        accept = "application/json; charset=utf-8"
        path = "/api/prd/loginbyoauth.json"

        oa_json = json.dumps({
            "country": "CN", "authCode": access_token,
            "oauthPlateform": 23, "oauthAppKey": ALI_APP_KEY,
            "riskControlInfo": {
                "appVersion": "1070001", "USE_OA_PWD_ENCRYPT": "true",
                "utdid": "ffffffffffffffffffffffff", "netType": "wifi",
                "umidToken": "", "locale": "zh_CN", "appVersionName": "1.7.1",
                "deviceId": str(uuid.uuid4()), "routerMac": "02:00:00:00:00:00",
                "platformVersion": "36", "appAuthToken": "",
                "appID": "com.mxchip.project352", "signType": "RSA",
                "sdkVersion": "3.4.2", "model": "HA",
                "USE_H5_NC": "true", "platformName": "android",
                "brand": "HomeAssistant", "yunOSId": "",
            },
        }, separators=(",", ":"))

        body_bytes = ("loginByOauthRequest=" + quote(oa_json, safe="")).encode()
        sign_headers = {
            "x-ca-key": ALI_APP_KEY, "x-ca-nonce": nonce,
            "x-ca-signature-method": "HmacSHA1", "x-ca-timestamp": ts_ms,
        }
        sh_str = "".join(f"{k}:{v}\n" for k, v in sorted(sign_headers.items()))
        sts = f"POST\n{accept}\n\n{ct}\n{date_str}\n{sh_str}{path}?loginByOauthRequest={oa_json}"
        sig = base64.b64encode(hmac.new(ALI_APP_SECRET.encode(), sts.encode(), hashlib.sha1).digest()).decode()

        headers = {
            "content-type": ct, "accept": accept,
            "x-ca-key": ALI_APP_KEY, "x-ca-nonce": nonce, "x-ca-timestamp": ts_ms,
            "x-ca-signature": sig,
            "x-ca-signature-headers": ",".join(sorted(sign_headers.keys())),
            "x-ca-signature-method": "HmacSHA1",
            "ca_version": "1", "user-agent": "ALIYUN-ANDROID-DEMO",
            "date": date_str, "Accept-Encoding": "gzip",
        }

        url = f"https://{ALI_OA_DOMAIN}{path}"
        data = await self._request_json("POST", url, headers=headers, data=body_bytes)
        _raise_if_service_unavailable(data)
        nested = data.get("data")
        if isinstance(nested, dict):
            _raise_if_service_unavailable(nested)

        try:
            return data["data"]["data"]["loginSuccessResult"]["sid"]
        except (KeyError, TypeError) as e:
            raise Air352AuthError("352 cloud rejected OAuth login") from e

    # ── Public API ──

    async def authenticate(self, *, force: bool = False) -> None:
        """Share one login and back off failed logins across concurrent callers."""
        observed_token = self._iot_token
        async with self._auth_lock:
            if self.is_iot_token_valid() and (
                not force or self._iot_token != observed_token
            ):
                return
            if self._auth_failure is not None and time.monotonic() < self._auth_retry_after:
                raise self._auth_failure
            try:
                await self._authenticate()
            except (Air352AuthError, Air352ApiError, Air352ConnectionError) as err:
                self._auth_failure = err
                self._auth_retry_after = time.monotonic() + 60
                raise
            self._auth_failure = None
            self._auth_retry_after = 0

    async def _authenticate(self) -> None:
        """Full auth: 352 login → region → OA login → IoT session."""
        # Step 1: 352 login
        login_path = "/api/v1/enduser/login"
        headers = self._352_headers(login_path)
        url = BASE_URL_352 + login_path
        data = await self._request_json("POST", url, headers=headers,
                json={"account": self._username, "password": self._password})
        _raise_if_service_unavailable(data)
        if data.get("code") not in (0, 200):
            raise Air352AuthError(data.get("message", "login failed"))
        self._access_token = data["data"]["access_token"]

        # Step 2: region get
        await self._ali_gw_request(
            "/living/account/region/get",
            {"type": "THIRD_AUTHCODE", "countryCode": "CN", "authCode": self._access_token},
        )

        # Step 3: OA login
        sid = await self._ali_oa_login(self._access_token)

        # Step 4: create IoT session
        r = await self._ali_gw_request(
            "/account/createSessionByAuthCode",
            {"request": {"authCode": sid, "accountType": "OA_SESSION", "appKey": ALI_APP_KEY}},
            api_ver="1.0.4",
        )
        self._iot_token = r["data"]["iotToken"]
        self._iot_refresh_token = r["data"]["refreshToken"]
        self._iot_token_expire = r["data"].get("iotTokenExpire", 72000)
        self._iot_token_ts = time.time()
        _LOGGER.debug("IoT auth complete, token expires in %ds", self._iot_token_expire)

    def is_iot_token_valid(self) -> bool:
        if not self._iot_token:
            return False
        elapsed = time.time() - self._iot_token_ts
        return elapsed < (self._iot_token_expire - 3600)

    @property
    def iot_token(self) -> str:
        """Return the current account token without logging or persisting it."""
        if not self._iot_token:
            raise Air352AuthError("IoT token is not available")
        return self._iot_token

    async def ensure_authenticated(self) -> None:
        if not self.is_iot_token_valid():
            await self.authenticate()

    async def get_mobile_channel_credentials(
        self, device_sn: str
    ) -> MobileTriple:
        """Create or recover the virtual-device identity used by the App."""
        auth_info = build_aepauth_auth_info(
            ALI_APP_KEY,
            ALI_APP_SECRET,
            device_sn,
        )
        response = await self._ali_gw_request(
            "/app/aepauth/handle",
            {"authInfo": auth_info},
            api_ver="1.0.0",
        )
        data = response.get("data", {})
        try:
            return MobileTriple(
                product_key=data["productKey"],
                device_name=data["deviceName"],
                device_secret=data["deviceSecret"],
            )
        except (KeyError, TypeError) as err:
            raise Air352AuthError(
                "Aliyun mobile-channel credentials are incomplete"
            ) from err

    async def get_device_list(self) -> list[dict]:
        await self.ensure_authenticated()
        r = await self._ali_gw_request(
            "/uc/listBindingByAccount",
            {"pageNo": 1, "pageSize": 50},
            iot_token=self._iot_token,
        )
        self.devices = r.get("data", {}).get("data", [])
        return self.devices

    async def get_device_properties(self, iot_id: str) -> dict:
        await self.ensure_authenticated()
        r = await self._ali_gw_request(
            "/thing/properties/get",
            {"iotId": iot_id},
            iot_token=self._iot_token,
        )
        return r.get("data", {})

    async def set_device_properties(self, iot_id: str, items: dict) -> None:
        await self.ensure_authenticated()
        await self._ali_gw_request(
            "/thing/properties/set",
            {"iotId": iot_id, "items": items},
            iot_token=self._iot_token,
        )

    async def request_z120_property_report(self, iot_id: str) -> None:
        """Ask a Z120 to report all live properties, as the official App does."""
        await self.set_device_properties(
            iot_id,
            {Z120_REFRESH_PROPERTY: Z120_REFRESH_VALUE},
        )

    async def get_device_info(self, iot_id: str) -> dict:
        """Get device info from 352 API (includes firmware, mac, etc.)."""
        return (await self._352_request("GET", f"/api/device/info/{iot_id}")).get("data", {})
