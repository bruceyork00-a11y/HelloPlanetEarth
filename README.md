# HelloPlanet

HelloPlanet 是一个 Windows 实时地球/星空壁纸工具。它会从公开卫星与 NASA 数据源抓取最新图片，定时更新桌面壁纸，并通过系统托盘菜单控制模式、刷新频率和语言。

## 下载

- Windows ZIP（v1.3.0）: [dist/HelloPlanet-v1.3.0-win64.zip](dist/HelloPlanet-v1.3.0-win64.zip)
- Windows exe: [dist/HelloPlanet.exe](dist/HelloPlanet.exe)
- Gitee exe 下载页: https://gitee.com/yinxiaolong007/hello-planet-earth/blob/master/dist/HelloPlanet.exe
- 源码压缩包: https://gitee.com/yinxiaolong007/hello-planet-earth/repository/archive/master.zip

## 功能

- 地球模式：美洲 GOES-19、太平洋 GOES-18、亚太 2K/4K Himawari-9、韩国 GK-2A、亚太每日 MODIS/VIIRS 合成地图、DSCOVR EPIC 地球全景
- 天空模式：NASA APOD、NOAA SUVI 实时太阳、NASA 火星精选图集
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
python app.py --mode goes_west
python app.py --mode asia_2k
python app.py --mode asia_4k
python app.py --mode asia_gk2a
python app.py --mode asia_modis
python app.py --mode earth_epic
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

- 当前图片源无需 API key，旧的 `NASA_API_KEY` 不再需要。
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
- 所有节点校验 HTTPS 证书，旧的 `ALLOW_INSECURE_*` 开关已删除。

## 图片源更新（v1.3.0）

- 删除已归档的火星照片 API、返回 400/404 的旧 GIBS 路径、重复 Himawari 配置及停止更新的 SDO 图。
- 保留实测有效的京都、himawari.asia、NICT 镜像，接入 [CIRA SLIDER](https://slider.cira.colostate.edu/) 同卫星备用源；部分瓦片缺失时整图作废，保留原壁纸。
- APOD 接入 [NASA 新 WordPress API](https://science.nasa.gov/wp-json/wp/v2/apod-basic)，视频日期自动选择近七天内最新图片。
- 卫星与太阳图超过三小时视为过期。MODIS/VIIRS 是每日合成地理地图，最多用前两日数据补轨道空隙；EPIC 通常延迟数日，JPEG 实测 1080×1080；火星是精选档案图集，菜单已区分它们与实时图。
- GOES-19/18 官方图为 1808×1808，CIRA 备用为 2712×2712；Himawari 2K/4K 原生为 2200×2200 / 4400×4400，CIRA 备用为 2752×2752 / 5504×5504。
- `sun_sdo` 参数兼容保留，但图片现由 NOAA SUVI 提供。下载失败时不跨主题或跨卫星替换壁纸。

## 节点与回归测试

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe scripts/check_sources.py --all-providers
```

网络检查会下载并完整解码每幅图、核对尺寸与非空内容，并将结果和预览保存到 `build/source-audit/`，不会改动桌面壁纸。完整审计记录见 `docs/source-audit-baseline.json` 与 `docs/source-audit-results.json`。
