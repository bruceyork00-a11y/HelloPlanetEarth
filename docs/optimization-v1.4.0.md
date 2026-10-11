# HelloPlanet v1.4.0 优化与验证

日期：2026-10-11。环境：Windows 10 19045，Python 3.13.5，Pillow 12.3.0，Requests 2.34.2，pystray 0.19.5。

## 修复与优化

| 领域 | 原问题 | 处理 |
| --- | --- | --- |
| 下载 | 相同时间戳仍重复下载所有瓦片 | 缓存完整无损 PNG，最多三张且总计 128 MiB；手动强制刷新绕过缓存 |
| 内存/CPU | 指纹计算和 BMP 编码复制全尺寸 RGB | 缩小后转换，RGB 直接编码；显式关闭工作线程的连接池 |
| 切换/退出 | 旧下载不能及时取消，原生壁纸调用占用状态锁 | 独立取消令牌、取消排队瓦片，原生 I/O 不占用菜单所需锁 |
| 重试 | 断网/源站失败按固定频率持续请求 | 渐增等待间隔，最长取原间隔与一小时中的较大值；手动重试立即执行 |
| 网络安全 | HTTP URL/危险跳转在请求之后才检查 | 请求前以及每次跳转检查 HTTPS、可信域名、无凭据、443 端口；最多五次跳转 |
| 解码 | 巨大图和错误尺寸瓦片可能先分配大量内存 | 解码前检查 3200 万像素上限和原生瓦片尺寸，明确限定格式，不启用 FITS 等其他解码器 |
| 配置 | 负数/零间隔、错类型、未知模式可进入运行逻辑 | 类型/范围/枚举检查、16K 字符配置上限、非法值回退；有效 CLI > 有效已保存值 > 有效环境变量 > 默认值 |
| 写入 | 配置/元数据/BMP 可部分覆盖 | 临时文件后原子替换；BMP 使用两个槽位，不覆盖当前活跃文件；保存失败给出菜单提示 |
| 单实例 | Windows HANDLE 缺少 64 位签名、重复实例的句柄未关闭 | 声明完整 ctypes 签名、检查错误并关闭重复句柄，进程退出时释放拥有的句柄 |
| 日志/发布 | 重设日志未关闭旧句柄，日志不可写可能阻止启动 | 关闭旧处理器、不可写时静默回退；EXE 填入产品版本，删除重复打包的源代码和字节码 |

## 托盘 UX

- 左/右键均打开菜单。状态、上次更新时间和下次检查时间置顶，模式选择从三级降为二级，诊断和退出置于底部。
- 下载期间显示完成瓦片数；重复强制刷新禁用。失败说明保留了旧壁纸，用户可重试或换模式。
- 增加五种原生显示方式，文字提示裁剪、留边和变形的区别，保留原有默认值与用户已保存设置。
- 中文/英文切换即刻更新菜单与悬浮文字。所有状态使用文字，不仅靠颜色，默认不弹出通知或日志窗口。
- Windows 菜单只在 UI 线程打开之前重建，下载线程只更新悬浮状态，避免原生菜单句柄的并发销毁。

这些选择参考 [Microsoft 通知区域说明](https://learn.microsoft.com/en-us/windows/win32/shell/notification-area) 和 [通知区域交互原则](https://learn.microsoft.com/en-us/windows/win32/uxguide/winenv-notification)。后者是历史 Windows 7 指南，本项目只采用仍适用的交互原则。

## 验证与性能数据

- 36 项回归/边界测试通过，包含真实 Windows 多进程互斥锁的获取、重复实例拒绝和退出释放，以及旧任务不能覆盖新模式状态。
- 十个模式完成在线整图检查，原始数据见 `optimization-v1.4.0-live.json`。初次遇到 NASA 部分查询参数返回 403，改为默认 APOD 请求和较小的三篇图集请求后，最终复测通过。
- 验证了非法 URL 在连接前被拒绝、重定向拒绝、无 Content-Length 时的体积上限、慢速分块读取预算、解码前像素限制、配置错误、损坏缓存、磁盘写入失败、快速切换和原生操作不阻塞菜单。
- 缓存测试的四瓦片场景：首次下载四次，重复读取新增零次，强制刷新再下载四次。没有把网络波动当作 CPU 优化效果。

4400×4400 合成噪声图，五次指纹计算的中位数，前后分别在独立进程中运行：

| 指标 | 原实现 | 优化后 |
| --- | --- | --- |
| 指纹处理耗时 | 82.02 ms | 42.13 ms |
| 测试进程峰值工作集 | 198.08 MiB | 111.64 MiB |

这表示该局部基准约快 49%、测试进程峰值工作集约低 44%，不代表整个程序总内存/所有机器都下降同样比例。下载取消仍受底层网络读取超时影响；已开始的 Windows 壁纸提交不能撤销，后续目标模式会继续更新。

复现：

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe scripts/benchmark.py old
.venv\Scripts\python.exe scripts/benchmark.py new
.venv\Scripts\python.exe scripts/check_sources.py
```

安全依据：[Pillow 安全说明](https://pillow.readthedocs.io/en/stable/handbook/security.html)、[FITS 解压缩炸弹公告](https://github.com/python-pillow/Pillow/security/advisories/GHSA-whj4-6x5x-4v2j)、[Requests 超时与重定向](https://requests.readthedocs.io/en/latest/user/quickstart/)。本轮没有进行全面渗透测试，也没有在全部 Windows/DPI/辅助技术组合下人工验证。
