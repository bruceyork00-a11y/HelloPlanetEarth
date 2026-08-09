# HelloPlanet

HelloPlanet 是一个 Windows 实时地球/星空壁纸工具。它会从公开卫星与 NASA 数据源抓取最新图片，定时更新桌面壁纸，并通过系统托盘菜单控制模式、刷新频率和语言。

## 下载

- Windows exe: [dist/HelloPlanet.exe](dist/HelloPlanet.exe)
- Gitee exe 下载页: https://gitee.com/yinxiaolong007/hello-planet-earth/blob/master/dist/HelloPlanet.exe
- 源码压缩包: https://gitee.com/yinxiaolong007/hello-planet-earth/repository/archive/master.zip

## 功能

- 地球模式：全球 GOES、亚太 2K Himawari、亚太 4K Himawari
- 天空模式：NASA APOD、太阳 SDO、火星探测器图片
- 刷新频率：低 1 小时、中 30 分钟、高 5 分钟
- 中英文托盘菜单切换
- 默认无控制台窗口，日志窗口可在托盘菜单中手动开启
- 鼠标悬浮托盘图标显示上次更新时间

## 运行

直接运行：

```bash
dist/HelloPlanet.exe
```

源码运行：

```bash
pip install -r requirements.txt
python app.py --mode asia_2k --interval 1800 --style fill
```

常用参数：

```bash
python app.py --mode earth
python app.py --mode asia_2k
python app.py --mode asia_4k
python app.py --mode sky
python app.py --mode sun_sdo
python app.py --mode mars
```

## 打包

```bash
pip install -r requirements.txt
pip install pyinstaller
pyinstaller HelloPlanet.spec --clean --noconfirm
```

生成文件位于 `dist/HelloPlanet.exe`。

## 配置

- `NASA_API_KEY`: NASA API key，默认使用 `DEMO_KEY`
- `MODE`: 默认模式，例如 `earth`、`asia_2k`、`asia_4k`
- `INTERVAL_SECONDS`: 默认刷新间隔秒数，默认 1800
- `LOG_LEVEL`: 日志等级，默认 `INFO`
- `HELLOPLANET_LANG`: 默认托盘语言，`zh` 或 `en`
- `HIMAWARI_TILE_COUNT`: 自定义 Himawari 瓦片层级，仅 `asia_custom` 使用

## 注意

- Windows 设置壁纸依赖 `SystemParametersInfoW` 和注册表壁纸样式。
- 亚太 4K 会下载 8x8 个 Himawari 瓦片，刷新会比 2K 慢。
- 日志和缓存默认写入系统临时目录下的 `hello_planet` 文件夹。
- 最低系统要求 **Windows 8.1**（exe 由 Python 3.13 构建，不支持 Windows 7/8.0）。
- 托盘中切换的 **模式 / 刷新频率 / 语言** 现在会持久化到 `%APPDATA%\HelloPlanet\config.json`，重启后保留；命令行参数与 `MODE`/`INTERVAL_SECONDS` 环境变量仅在未保存过配置时作为初始默认值。
- 仅允许 **单实例** 运行：重复启动会检测到已有实例并自动退出。
- 机器从睡眠/休眠唤醒后，会**自动强制刷新**一次壁纸（避免停留在旧图）。
- 未捕获的异常现在会写入日志文件（`hello_planet\app.log`）而非静默崩溃，便于排查。
- `ALLOW_INSECURE_HIMAWARI` / `ALLOW_INSECURE_SDO=1` 会**关闭 TLS 证书校验**，仅用于源站证书异常时临时排查，存在中间人攻击风险，不建议长期使用。
