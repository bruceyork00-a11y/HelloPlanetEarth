# PyInstaller 打包说明

建议使用单文件方式：

```bash
pip install pyinstaller
pyinstaller -F -n HelloPlanet --add-data "src;src" app.py
```

- 输出在 `dist/HelloPlanet.exe`
- 如需设置图标：`--icon path/to/icon.ico`
- 若运行缺少依赖，确保在同一环境执行 `pip install -r requirements.txt`
