# 352 Air - Home Assistant Integration

Home Assistant 自定义集成，支持 [352](https://www.352air.com/) 空气净化器、净水器、加湿器的状态监控和设备控制。

## 支持设备

| 类型 | 传感器 | 控制 |
|------|--------|------|
| 空气净化器 | PM2.5、TVOC、甲醛、CO2、温度、湿度、滤芯寿命 | 电源、运行模式、手动档位、童锁、屏幕、负离子、智能模式 |
| 净水器 | 进水TDS、出水TDS、水温、累计净水量、滤芯寿命 | 童锁 |
| 加湿器 | PM2.5、温度、湿度、滤芯寿命 | 电源、童锁、屏幕、智能模式 |

## 已测试设备

- 352 Z120 空气净化器

## 安装

### HACS（推荐）

1. HACS → 集成 → 右上角三点 → 自定义仓库
2. 输入 `https://github.com/wangty163/hass-air352`，类别选 "集成"
3. 搜索 "352 Air" 安装
4. 重启 Home Assistant

### 手动安装

将 `custom_components/air352` 目录复制到 Home Assistant 的 `config/custom_components/` 下，重启 HA。

## 配置

设置 → 设备与服务 → 添加集成 → 搜索 "352 Air" → 输入 352Life App 的手机号和密码。

## Z120 控制实体（4.0.0）

Z120 的控制已拆分为三个职责单一的实体：

| 实体 | 用途 | 可选值 / 行为 |
|------|------|---------------|
| 电源开关 | 仅开机、关机 | 只写入电源属性 |
| 运行模式 | 选择设备模式 | 手动、自动、睡眠、Skin、风干；设备关机时选择会按固件逻辑启动设备 |
| 手动档位 | 选择风量档位 | 1档～6档；选择后会同时把运行模式切换为手动，关机时选择会启动设备 |

这样电源、模式和档位可以分别在 Home Assistant 页面及自动化中控制。352 Z120 固件会在
收到模式或档位命令时启动设备，因此“实体拆分”不代表关机状态下可以预存模式或档位。自动化可分别调用
`switch.turn_on` / `switch.turn_off` 和 `select.select_option`；模式选项为
`manual`、`auto`、`sleep`、`skin`、`air_drying`，档位选项为 `gear_1`～`gear_6`。

旧的空气净化器 `fan` 实体仍保留用于兼容已有自动化，但对 Z120 默认禁用。升级前已经注册并启用的
`fan` 实体可能继续保持启用状态；确认页面和自动化都已改用上述三个实体后，可在实体设置中手动禁用它。
若暂时需要回退，重新启用旧 `fan` 实体即可。

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
