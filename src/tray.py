import logging
import os
import sys
from datetime import datetime
from typing import Callable, Optional

from PIL import Image, ImageDraw
import pystray


log = logging.getLogger(__name__)
APP_NAME = "HelloPlanet"

if sys.platform == "win32":
	class StatusIcon(pystray.Icon):
		def _on_notify(self, wparam, lparam):
			# Refresh only on the UI thread, before the popup opens.
			if lparam in (0x0202, 0x0205):  # WM_LBUTTONUP / WM_RBUTTONUP
				self.update_menu()
				lparam = 0x0205
			return super()._on_notify(wparam, lparam)
else:
	StatusIcon = pystray.Icon

TEXT = {
	"zh": {
		"last_update": "上次更新",
		"not_updated": "尚未更新",
		"force_refresh": "强制刷新",
		"mode": "模式",
		"earth": "地球",
		"goes": "美洲 (GOES-19)",
		"goes_west": "太平洋 (GOES-18)",
		"asia_gk2a": "亚太 (GK-2A)",
		"asia_modis": "亚太每日合成 (MODIS/VIIRS)",
		"earth_epic": "地球全景 (EPIC，延迟数日)",
		"asia_2k": "亚太 2K (Himawari)",
		"asia_4k": "亚太 4K (Himawari)",
		"sky": "天空",
		"apod": "每日天文图 (APOD)",
		"sun": "太阳实时图 (SUVI)",
		"mars": "火星精选 (NASA 图集)",
		"refresh_rate": "刷新频率",
		"low": "低 (1小时)",
		"medium": "中 (30分钟)",
		"high": "高 (5分钟)",
		"log_window": "日志窗口",
		"language": "语言 / Language",
		"chinese": "中文",
		"english": "English",
		"quit": "退出",
		"idle": "等待更新",
		"updating": "正在更新",
		"updated": "壁纸已更新",
		"unchanged": "暂无新图片，已检查",
		"error": "更新失败，保留当前壁纸；可重试或换模式",
		"settings_unsaved": "设置未保存，下次启动可能恢复旧值",
		"display": "壁纸显示方式",
		"fill": "铺满（可能裁剪）",
		"fit": "完整显示（可能留边）",
		"center": "居中（原尺寸）",
		"stretch": "拉伸（可能变形）",
		"tile": "平铺",
		"next_check": "下次检查",
	},
	"en": {
		"last_update": "Last update",
		"not_updated": "Not updated yet",
		"force_refresh": "Force refresh",
		"mode": "Mode",
		"earth": "Earth",
		"goes": "Americas (GOES-19)",
		"goes_west": "Pacific (GOES-18)",
		"asia_gk2a": "Asia-Pacific (GK-2A)",
		"asia_modis": "Asia daily map (MODIS/VIIRS)",
		"earth_epic": "Earth disk (EPIC, delayed)",
		"asia_2k": "Asia-Pacific 2K (Himawari)",
		"asia_4k": "Asia-Pacific 4K (Himawari)",
		"sky": "Sky",
		"apod": "Astronomy Picture (APOD)",
		"sun": "Live Sun (SUVI)",
		"mars": "Mars gallery (NASA)",
		"refresh_rate": "Refresh rate",
		"low": "Low (1 hour)",
		"medium": "Medium (30 minutes)",
		"high": "High (5 minutes)",
		"log_window": "Log window",
		"language": "Language / 语言",
		"chinese": "中文",
		"english": "English",
		"quit": "Quit",
		"idle": "Waiting for update",
		"updating": "Updating",
		"updated": "Wallpaper updated",
		"unchanged": "Checked, no new image",
		"error": "Update failed; wallpaper kept. Retry or change mode",
		"settings_unsaved": "Settings not saved; may reset after restart",
		"display": "Wallpaper display",
		"fill": "Fill (may crop)",
		"fit": "Fit (show whole image)",
		"center": "Center (original size)",
		"stretch": "Stretch (may distort)",
		"tile": "Tile",
		"next_check": "Next check",
	},
}


def _create_icon() -> Image.Image:
	size = 64
	img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
	draw = ImageDraw.Draw(img)
	draw.ellipse((4, 4, size - 4, size - 4), fill=(34, 139, 230, 255))
	draw.arc((14, 18, size - 14, size - 10), start=200, end=340, fill=(255, 255, 255, 235), width=4)
	draw.arc((18, 12, size - 18, size - 8), start=20, end=160, fill=(130, 220, 120, 230), width=4)
	return img


class TrayController:
	def __init__(
		self,
		on_force_refresh: Callable[[], None],
		on_switch_mode: Callable[[str], None],
		on_set_interval: Callable[[int], None],
		on_toggle_log_window: Callable[[], None],
		is_log_window_open: Callable[[], bool],
		on_quit: Callable[[], None],
		on_set_language: Callable[[str], None] = None,
		initial_language: str = "zh",
		get_mode: Callable[[], str] = None,
		get_interval: Callable[[], int] = None,
		get_last_update_time: Callable[[], Optional[datetime]] = None,
		get_status=None,
		on_set_style=None,
		get_style=None,
	):
		self.on_force_refresh = on_force_refresh
		self.on_switch_mode = on_switch_mode
		self.on_set_interval = on_set_interval
		self.on_toggle_log_window = on_toggle_log_window
		self.is_log_window_open = is_log_window_open
		self.on_quit = on_quit
		self.on_set_language = on_set_language
		self.get_mode = get_mode or (lambda: "")
		self.get_interval = get_interval or (lambda: 0)
		self.get_last_update_time = get_last_update_time or (lambda: None)
		self.get_status = get_status or (lambda: {"state": "idle"})
		self.on_set_style = on_set_style or (lambda style: None)
		self.get_style = get_style or (lambda: "fill")
		self.language = self._normalize_language(initial_language or os.getenv("HELLOPLANET_LANG", "zh"))
		self._icon = None

	def _normalize_language(self, language: str) -> str:
		language = (language or "zh").lower()
		return "en" if language.startswith("en") else "zh"

	def _text(self, key: str) -> str:
		return TEXT[self.language][key]

	def _last_update_text(self) -> str:
		updated_at = self.get_last_update_time()
		if updated_at is None:
			return self._text("not_updated")
		return updated_at.strftime("%H:%M:%S")

	def _title(self) -> str:
		return f"{APP_NAME} - {self._text('last_update')}: {self._last_update_text()} | {self._status_text()}"[:127]

	def _status_text(self):
		status = self.get_status()
		key = status.get("state", "idle")
		text = self._text(key if key in TEXT[self.language] else "idle")
		if status.get("state") == "updating" and status.get("progress"):
			done, total = status["progress"]
			text += f" ({done}/{total})"
		elif status.get("state") == "updated" and status.get("resolution"):
			width, height = status["resolution"]
			text += f" ({width}x{height})"
		return text

	def set_status(self, status):
		if self._icon:
			self._icon.title = self._title()

	def _label(self, key: str):
		"""Resolve menu labels when pystray rebuilds the native Windows menu."""
		return lambda item: self._text(key)

	def set_last_update(self, updated_at: datetime):
		if self._icon:
			self._icon.title = self._title()

	def _safe_call(self, fn: Callable[[], None]):
		try:
			fn()
		except Exception as e:
			log.error(f"tray action error: {e}")

	def _action(self, fn: Callable[[], None]):
		return lambda icon, item: self._safe_call(fn)

	def _switch_mode_action(self, mode: str):
		return self._action(lambda: self.on_switch_mode(mode))

	def _set_interval_action(self, interval_seconds: int):
		return self._action(lambda: self.on_set_interval(interval_seconds))

	def _set_language_action(self, language: str):
		lang = self._normalize_language(language)
		def _fn():
			self.language = lang
			if self._icon:
				self._icon.title = self._title()
			if self.on_set_language:
				self.on_set_language(lang)
		return self._action(_fn)

	def _mode_checked(self, mode: str):
		return lambda item: self.get_mode() == mode or (mode == "asia_2k" and self.get_mode() == "asia")

	def _interval_checked(self, interval_seconds: int):
		return lambda item: self.get_interval() == interval_seconds

	def _language_checked(self, language: str):
		return lambda item: self.language == language

	def _build_menu(self) -> pystray.Menu:
		menu = pystray.Menu(
			pystray.MenuItem(self._label("force_refresh"), self._action(self.on_force_refresh),
				enabled=lambda item: self.get_status().get("state") != "updating"),
			pystray.MenuItem(
				self._label("mode"),
				pystray.Menu(
					pystray.MenuItem(
						self._label("earth"),
						pystray.Menu(
							pystray.MenuItem(self._label("goes"), self._switch_mode_action("earth"), checked=self._mode_checked("earth"), radio=True),
							pystray.MenuItem(self._label("goes_west"), self._switch_mode_action("goes_west"), checked=self._mode_checked("goes_west"), radio=True),
							pystray.MenuItem(self._label("asia_2k"), self._switch_mode_action("asia_2k"), checked=self._mode_checked("asia_2k"), radio=True),
							pystray.MenuItem(self._label("asia_4k"), self._switch_mode_action("asia_4k"), checked=self._mode_checked("asia_4k"), radio=True),
							pystray.MenuItem(self._label("asia_gk2a"), self._switch_mode_action("asia_gk2a"), checked=self._mode_checked("asia_gk2a"), radio=True),
							pystray.MenuItem(self._label("asia_modis"), self._switch_mode_action("asia_modis"), checked=self._mode_checked("asia_modis"), radio=True),
							pystray.MenuItem(self._label("earth_epic"), self._switch_mode_action("earth_epic"), checked=self._mode_checked("earth_epic"), radio=True),
						),
					),
					pystray.MenuItem(
						self._label("sky"),
						pystray.Menu(
							pystray.MenuItem(self._label("apod"), self._switch_mode_action("sky"), checked=self._mode_checked("sky"), radio=True),
							pystray.MenuItem(self._label("sun"), self._switch_mode_action("sun_sdo"), checked=self._mode_checked("sun_sdo"), radio=True),
							pystray.MenuItem(self._label("mars"), self._switch_mode_action("mars"), checked=self._mode_checked("mars"), radio=True),
						),
					),
				),
			),
			pystray.MenuItem(
				self._label("refresh_rate"),
				pystray.Menu(
					pystray.MenuItem(self._label("low"), self._set_interval_action(60 * 60), checked=self._interval_checked(60 * 60), radio=True),
					pystray.MenuItem(self._label("medium"), self._set_interval_action(30 * 60), checked=self._interval_checked(30 * 60), radio=True),
					pystray.MenuItem(self._label("high"), self._set_interval_action(5 * 60), checked=self._interval_checked(5 * 60), radio=True),
				),
			),
			pystray.MenuItem(self._label("log_window"), self._action(self.on_toggle_log_window), checked=lambda item: self.is_log_window_open()),
			pystray.MenuItem(lambda item: self._status_text(), None, enabled=False),
			pystray.MenuItem(lambda item: f"{self._text('last_update')}: {self._last_update_text()}", None, enabled=False),
			pystray.MenuItem(self._label("display"), pystray.Menu(*[
				pystray.MenuItem(self._label(style), self._action(lambda style=style: self.on_set_style(style)),
					checked=lambda item, style=style: self.get_style() == style, radio=True)
				for style in ("fit", "fill", "center", "stretch", "tile")
			])),
			pystray.MenuItem(
				self._label("language"),
				pystray.Menu(
					pystray.MenuItem(self._label("chinese"), self._set_language_action("zh"), checked=self._language_checked("zh"), radio=True),
					pystray.MenuItem(self._label("english"), self._set_language_action("en"), checked=self._language_checked("en"), radio=True),
				),
			),
			pystray.MenuItem(self._label("quit"), self._action(self.on_quit)),
		)
		items = list(menu.items)
		mode_groups = items[1].submenu.items
		mode_menu = pystray.MenuItem(self._label("mode"), pystray.Menu(
			*mode_groups[0].submenu.items, pystray.Menu.SEPARATOR, *mode_groups[1].submenu.items))
		def next_label(item):
			time = self.get_status().get("next_check")
			return f"{self._text('next_check')}: {time.strftime('%H:%M:%S')}" if time else self._status_text()
		return pystray.Menu(items[4], items[5], pystray.MenuItem(next_label, None, enabled=False),
			pystray.MenuItem(self._label("settings_unsaved"), None, enabled=False,
				visible=lambda item: self.get_status().get("notice") == "settings_unsaved"),
			pystray.Menu.SEPARATOR, items[0], mode_menu, items[6], items[2], items[7],
			pystray.Menu.SEPARATOR, items[3], items[8])

	def run(self):
		icon = StatusIcon(APP_NAME, _create_icon(), self._title(), self._build_menu())
		self._icon = icon
		log.info("tray starting...")
		icon.run()

	def stop(self):
		if self._icon:
			log.info("tray stopping...")
			self._icon.stop()
