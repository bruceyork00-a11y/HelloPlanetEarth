# HelloPlanet v1.3.0 图片源审计

审计日期：2026-10-11。网络可用性以本机测试环境为准，原始检查结果保存在 `source-audit-baseline.json`；新版逐模式及逐提供商完整下载结果保存在 `source-audit-results.json`。

## 原有问题及处理

| 原节点/逻辑 | 实测问题 | 处理 |
| --- | --- | --- |
| NASA Mars Photos API，Perseverance / Curiosity | 两条 API 都返回 404；NASA 已归档服务 | 删除两条地址，火星模式改为 NASA Science 精选图集 |
| GIBS 三条旧 WMTS URL | 全部返回 404 | 删除，改用官方 WMS GetMap 接口 |
| map1.vis 两条旧 MODIS URL | 重定向后返回 400 | 删除，日地图使用新 WMS 服务 |
| SDO 4096 AIA171 / HMIIC | 可下载，但 Last-Modified 停在 2026-09-21 | 删除实时源，太阳改用 NOAA SUVI 主/备卫星 |
| GOES16 latest.jpg | 可用但重定向到 GOES19，文件 10848×10848、约 10 MB | 直接连接 GOES19 1808×1808，新增 GOES18 模式 |
| Himawari 镜像 | 元数据及 4d/8d 瓦片都仍可连接 | 保留四个真实提供商，删除重复的“亚洲网页 + 京都瓦片”配置 |
| JMA 区域图/全盘低分辨率回退 | 官方页面可连接；全盘为 601×601，不满足 2K/4K | 从高分辨率自动回退链中移除 |
| RAMMB 旧 Himawari-9 单图候选 | 返回 404 | 不接入，改用 CIRA SLIDER 当前瓦片路径 |
| Perseverance 原始 RSS API | 多次超时 | 不接入；旧每周精选网页图片也停止更新且只有 480×480 |
| 亚太回退 EPIC/GOES、火星回退太阳、APOD 回退火星 | 选中模式与显示内容不一致 | 删除跨主题/卫星回退，失败时保留原壁纸 |
| 允许 15% 瓦片缺失 | 黑块仍被当成成功图片 | 任一瓦片失败或尺寸错误，拒绝整图并清理图片对象 |
| 下载多层重试 | adapter 与外层重试叠加，错误时等待过久 | 单层两次重试，4xx 立即失败，限制下载体积与时长 |

## 新版节点与图片类型

| 模式 | 主源 | 备用 | 原生尺寸/时效 |
| --- | --- | --- | --- |
| 美洲 GOES-19 | NOAA STAR | CIRA GOES-19 | 1808×1808 / 2712×2712，约十分钟更新 |
| 太平洋 GOES-18 | NOAA STAR | CIRA GOES-18 | 1808×1808 / 2712×2712，约十分钟更新 |
| 亚太 Himawari 2K/4K | 京都、himawari.asia、NICT download、NICT | CIRA Himawari-9 | 2200/4400 方图；备用 2752/5504 方图 |
| 亚太 GK-2A | CIRA GK-2A | 无 | 2752×2752，近实时 |
| 亚太 MODIS/VIIRS 日地图 | NASA GIBS WMS，Terra/Aqua/NOAA20 | 前两日数据补轨道空隙 | 2200×2200，缺失覆盖超过 2% 时拒绝输出 |
| EPIC 地球全景 | NASA EPIC 公开 API + JPEG 档案 | 无 | 本次 JPEG 实测 1080×1080，通常延迟数日，最长接受十四日 |
| APOD | NASA Science APOD WordPress API | 近七天最新非视频图 | 按提供者原生分辨率；下载 hdurl，url 为文章 |
| 实时太阳 | NOAA SUVI primary 171 | NOAA SUVI secondary 171 | 1280×1280，近实时 |
| 火星精选 | NASA Science 图集 | 同列表中的匹配图片 | 精选档案图片，按发布日期选择；不代表实时原始下传 |

Himawari、GOES 和 SUVI 拒绝超过三小时的图像时间戳。CIRA 下载一次图像只使用同一观测时间，禁止混拼不同时刻瓦片。EPIC 按日期排序选取最新观测，而不是使用数组第一张图。日地图与整盘图不同，会组合多传感器轨道覆盖，记录使用的日期、图层和覆盖率。

## 调研依据

- 开源项目 [domoritz/satellite-new-tab](https://github.com/domoritz/satellite-new-tab) 当前使用 CIRA SLIDER 以及 EPIC，其源码提供最新时间列表、各卫星原生瓦片大小和路径布局。本项目独立实现下载与拼图，没有复制其代码。
- [CIRA SLIDER](https://slider.cira.colostate.edu/) 官方站点及 [产品定义](https://slider.cira.colostate.edu/js/define-products---rammb-slider.js)：核对 satellite id、full_disk、geocolor、688/678 原生瓦片大小；Himawari 和 GK-2A 已抽样实测。
- [NOAA STAR GOES-East](https://www.star.nesdis.noaa.gov/goes/fulldisk.php?sat=G19)：核对 GOES19 当前命名、GeoColor 图片分辨率和更新周期。
- [NASA Open APIs](https://api.nasa.gov/)：公告 Mars Rover API 归档及 APOD 向 WordPress 迁移；新版 API 为 `https://science.nasa.gov/wp-json/wp/v2/apod-basic`。
- [NASA GIBS 接入文档](https://nasa-gibs.github.io/gibs-api-docs/access-basics/)：使用 WMS 1.1.1 和 EPSG:4326，明确 BBOX 为经度/纬度次序。
- [NOAA SUVI 官方说明](https://www.spaceweather.gov/products/goes-solar-ultraviolet-imager-suvi)：使用公开 animation JSON 获取观测文件。

## 测试方法

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe scripts/check_sources.py --all-providers
```

回归测试覆盖：过期/未来时间、缺瓦片拒绝整图和资源清理、瓦片坐标、不跨模式回退、错误 HTML、APOD 视频与图片选择、线程独立 Session、火星搜索结果过滤、切换模式后丢弃旧图、退出后拒绝设壁纸、退出时取消下载及后续回退、下载中请求强制刷新、模式持久化、中英文菜单、BMP 编码。

网络测试覆盖菜单中的全部十个模式，并单独下载四个 Himawari 镜像、四个 CIRA 卫星产品、CIRA Himawari 4K、SUVI secondary 和 GIBS VIIRS NOAA20。每幅图完整下载并解码，记录尺寸、观测时间/发布日期、耗时、来源 URL 和 SHA-256，生成预览图以检查画面。检查不会改变当前桌面壁纸。

最终结果：16/16 项回归测试通过，21/21 项网络整图检查通过，EXE 重建与 `--help` 启动检查通过。初测 CIRA 4K 和 SUVI secondary 的临时断连/超时、替换前火星与日地图记录保留在 JSON 的 `superseded_checks` 中，最终记录使用修复/复测结果。MODIS 同日 Terra/Aqua 合成实测覆盖率为 99.86%。

本机网络的大图传输存在波动；某次超时不能单独证明公共服务永久失效。永久 404/400、归档节点及已停止更新的图片已删除，其余节点按完整图测试结果处理。托盘原生鼠标交互不在自动网络检查范围内。
