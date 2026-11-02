import logging

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import callback

from .api import Air352ApiClient, Air352AuthError, Air352ConnectionError
from .const import CONF_USER_AGENT, DOMAIN

_LOGGER = logging.getLogger(__name__)


class Air352ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return Air352OptionsFlow()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            session = aiohttp.ClientSession()
            try:
                api = Air352ApiClient(
                    session,
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                    user_agent=user_input.get(CONF_USER_AGENT),
                )
                await api.authenticate()
                devices = await api.get_device_list()
            except Air352AuthError:
                errors["base"] = "invalid_auth"
            except (Air352ConnectionError, Exception) as e:
                _LOGGER.exception("Connection error: %s", e)
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(user_input[CONF_USERNAME])
                self._abort_if_unique_id_configured()
                title = f"352 ({user_input[CONF_USERNAME]}) - {len(devices)} devices"
                return self.async_create_entry(title=title, data=user_input)
            finally:
                await session.close()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_USER_AGENT, default=""): str,
            }),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors = {}
        if user_input is not None:
            entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
            session = aiohttp.ClientSession()
            try:
                user_agent = entry.options.get(
                    CONF_USER_AGENT,
                    entry.data.get(CONF_USER_AGENT),
                )
                api = Air352ApiClient(
                    session,
                    entry.data[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                    user_agent=user_agent,
                )
                await api.authenticate()
            except Air352AuthError:
                errors["base"] = "invalid_auth"
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")
            finally:
                await session.close()

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )


class Air352OptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_ua = self.config_entry.options.get(
            CONF_USER_AGENT,
            self.config_entry.data.get(CONF_USER_AGENT, ""),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_USER_AGENT, default=current_ua or ""): str,
            }),
        )
