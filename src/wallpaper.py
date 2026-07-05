import os
import tempfile
import ctypes
from ctypes import wintypes
from PIL import Image
import winreg
import logging

# SPI constants
SPI_SETDESKWALLPAPER = 20
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDWININICHANGE = 0x02

# Wallpaper styles mapping (Windows)
# 0: Center, 2: Stretch, 6: Fit, 10: Fill
WALLPAPER_STYLE_TO_REG = {
	"center": ("0", "0"),
	"stretch": ("2", "0"),
	"fit": ("6", "0"),
	"fill": ("10", "0"),
	"tile": ("0", "1"),
}

log = logging.getLogger(__name__)


def _set_style_in_registry(style: str) -> None:
	style = style.lower()
	if style not in WALLPAPER_STYLE_TO_REG:
		raise ValueError(f"Unsupported wallpaper style: {style}")
	wallpaper_style, tile_wallpaper = WALLPAPER_STYLE_TO_REG[style]
	log.info(f"registry style set: style={style} WallpaperStyle={wallpaper_style} TileWallpaper={tile_wallpaper}")
	with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\\Desktop", 0, winreg.KEY_SET_VALUE) as key:
		winreg.SetValueEx(key, "WallpaperStyle", 0, winreg.REG_SZ, wallpaper_style)
		winreg.SetValueEx(key, "TileWallpaper", 0, winreg.REG_SZ, tile_wallpaper)


def _save_as_bmp(image: Image.Image, target_path: str) -> str:
	os.makedirs(os.path.dirname(target_path), exist_ok=True)
	rgb_image = image.convert("RGB")
	rgb_image.save(target_path, format="BMP")
	log.info(f"bmp saved: path={target_path} size={rgb_image.size}")
	return target_path


def set_wallpaper_from_image(image: Image.Image, style: str = "fill") -> None:
	_set_style_in_registry(style)
	cache_dir = os.path.join(tempfile.gettempdir(), "hello_planet")
	bmp_path = os.path.join(cache_dir, "current_wallpaper.bmp")
	bmp_path = _save_as_bmp(image, bmp_path)
	ctypes.windll.user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
	ctypes.windll.user32.SystemParametersInfoW.restype = wintypes.BOOL
	log.info("SPI set wallpaper calling...")
	result = ctypes.windll.user32.SystemParametersInfoW(
		SPI_SETDESKWALLPAPER,
		0,
		bmp_path,
		SPIF_UPDATEINIFILE | SPIF_SENDWININICHANGE,
	)
	log.info(f"SPI result: {bool(result)} path={bmp_path}")
	if not result:
		raise OSError("Failed to set wallpaper via SystemParametersInfoW")
