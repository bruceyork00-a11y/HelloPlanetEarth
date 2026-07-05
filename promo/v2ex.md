# V2EX Draft

## 推荐节点

- 分享创造
- Windows
- 程序员

## 标题

做了一个把实时地球/亚太卫星图自动设成 Windows 壁纸的小工具

## 正文

最近做了一个小工具 HelloPlanet，主要是想让桌面壁纸不再是一张静态图，而是能跟着真实的地球和太空图片自动变化。

它目前是一个 Windows 托盘程序，默认没有窗口。功能大概是：

- 全球 GOES 地球图
- 亚太 Himawari 2K / 4K 卫星图，4K 是拼 Himawari 瓦片生成的
- NASA APOD 每日天文图
- SDO 太阳图
- 火星探测器图片
- 刷新频率：1 小时、30 分钟、5 分钟
- 托盘菜单支持中文/英文切换
- 鼠标悬浮托盘图标显示上次更新时间

项目和 exe 放在 Gitee：
https://gitee.com/yinxiaolong007/hello-planet-earth

Windows exe 下载页：
https://gitee.com/yinxiaolong007/hello-planet-earth/blob/master/dist/HelloPlanet.exe

欢迎试用，也想听听大家觉得这种工具应该继续保持简单托盘程序，还是做成更完整的桌面应用。
