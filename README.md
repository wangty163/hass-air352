# 352 Air - Home Assistant Integration

Home Assistant 自定义集成，支持 [352](https://www.352air.com/) 空气净化器、净水器、加湿器的状态监控和设备控制。

## 支持设备

| 类型 | 传感器 | 控制 |
|------|--------|------|
| 空气净化器 | PM2.5、TVOC、甲醛、CO2、温度、湿度、滤芯寿命 | 电源、童锁、屏幕、负离子、智能模式 |
| 净水器 | 进水TDS、出水TDS、水温、累计净水量、滤芯寿命 | 童锁 |
| 加湿器 | PM2.5、温度、湿度、滤芯寿命 | 电源、童锁、屏幕、智能模式 |

## 已测试设备

- 352 Z120 空气净化器

## 安装

### HACS（推荐）

1. HACS → 集成 → 右上角三点 → 自定义仓库
2. 输入仓库地址，类别选 "集成"
3. 搜索 "352 Air" 安装
4. 重启 Home Assistant

### 手动安装

将 `custom_components/air352` 目录复制到 Home Assistant 的 `config/custom_components/` 下，重启 HA。

## 配置

设置 → 设备与服务 → 添加集成 → 搜索 "352 Air" → 输入 352Life App 的手机号和密码。

## Z120 档位控制（3.0.0）

Z120 的风扇实体在 Home Assistant 原生详情页中直接提供 `1档`～`6档`，不再显示百分比滑杆。
自动、睡眠、Skin 和风干模式与六个手动档位位于同一个模式选择器中；选择任一档位会同时进入手动模式。

由于 Home Assistant 使用同一个 `SET_SPEED` 能力同时控制百分比界面和百分比服务，Z120 不再支持
`fan.set_percentage`、`fan.increase_speed` 和 `fan.decrease_speed`。自动化请改用
`fan.set_preset_mode`（`gear_1`～`gear_6`）；已有的 `fan.turn_on` + `percentage` 调用仍兼容。

开发验证：

```bash
python3 -m unittest discover -s tests -v
# 下面一项需在安装了 Home Assistant 的 Python 环境中执行
PYTHONPATH=. python3 tests/verify_real_ha_contract.py -v
```

## 工作原理

1. 通过 352 API 登录获取 access_token
2. 通过阿里云 IoT 生活物联网平台（飞燕）认证获取 iotToken
3. 通过阿里云 IoT API Gateway 获取设备列表和属性
4. 通过 `/thing/properties/set` 下发设备控制指令
5. 每 120 秒轮询一次设备状态

## 依赖

无外部 Python 依赖，仅使用 Home Assistant 内置的 `aiohttp` 和 Python 标准库。

## License

MIT
