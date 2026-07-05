import logging
import os
from datetime import datetime
from typing import Callable, Optional

from PIL import Image, ImageDraw
import pystray


log = logging.getLogger(__name__)
APP_NAME = "HelloPlanet"

TEXT = {
	"zh": {
		"last_update": "上次更新",
		"not_updated": "尚未更新",
		"refresh_once": "刷新一次",
		"force_refresh": "强制刷新",
		"mode": "模式",
		"earth": "地球",
		"goes": "全球 (GOES)",
		"asia_2k": "亚太 2K (Himawari)",
		"asia_4k": "亚太 4K (Himawari)",
		"sky": "天空",
		"apod": "每日天文图 (APOD)",
		"sun": "太阳 (SDO)",
		"mars": "火星 (探测器)",
		"refresh_rate": "刷新频率",
		"low": "低 (1小时)",
		"medium": "中 (30分钟)",
		"high": "高 (5分钟)",
		"log_window": "日志窗口",
		"language": "语言 / Language",
		"chinese": "中文",
		"english": "English",
		"quit": "退出",
	},
	"en": {
		"last_update": "Last update",
		"not_updated": "Not updated yet",
		"refresh_once": "Refresh once",
		"force_refresh": "Force refresh",
		"mode": "Mode",
		"earth": "Earth",
		"goes": "Global (GOES)",
		"asia_2k": "Asia-Pacific 2K (Himawari)",
		"asia_4k": "Asia-Pacific 4K (Himawari)",
		"sky": "Sky",
		"apod": "Astronomy Picture (APOD)",
		"sun": "Sun (SDO)",
		"mars": "Mars (Rover)",
		"refresh_rate": "Refresh rate",
		"low": "Low (1 hour)",
		"medium": "Medium (30 minutes)",
		"high": "High (5 minutes)",
		"log_window": "Log window",
		"language": "Language / 语言",
		"chinese": "中文",
		"english": "English",
		"quit": "Quit",
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
		on_refresh: Callable[[], None],
		on_switch_mode: Callable[[str], None],
		on_set_interval: Callable[[int], None],
		on_toggle_log_window: Callable[[], None],
		is_log_window_open: Callable[[], bool],
		on_quit: Callable[[], None],
		on_force_refresh: Callable[[], None] = None,
		get_mode: Callable[[], str] = None,
		get_interval: Callable[[], int] = None,
		get_last_update_time: Callable[[], Optional[datetime]] = None,
	):
		self.on_refresh = on_refresh
		self.on_switch_mode = on_switch_mode
		self.on_set_interval = on_set_interval
		self.on_toggle_log_window = on_toggle_log_window
		self.is_log_window_open = is_log_window_open
		self.on_quit = on_quit
		self.on_force_refresh = on_force_refresh or on_refresh
		self.get_mode = get_mode or (lambda: "")
		self.get_interval = get_interval or (lambda: 0)
		self.get_last_update_time = get_last_update_time or (lambda: None)
		self.language = self._normalize_language(os.getenv("HELLOPLANET_LANG", "zh"))
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
		return f"{APP_NAME} - {self._text('last_update')}: {self._last_update_text()}"

	def _refresh_menu(self):
		if self._icon:
			self._icon.title = self._title()
			self._icon.menu = self._build_menu()
			self._icon.update_menu()

	def set_last_update(self, updated_at: datetime):
		if self._icon:
			self._icon.title = f"{APP_NAME} - {self._text('last_update')}: {updated_at.strftime('%H:%M:%S')}"

	def _safe_call(self, fn: Callable[[], None]):
		try:
			fn()
			self._refresh_menu()
		except Exception as e:
			log.error(f"tray action error: {e}")

	def _action(self, fn: Callable[[], None]):
		return lambda icon, item: self._safe_call(fn)

	def _switch_mode_action(self, mode: str):
		return self._action(lambda: self.on_switch_mode(mode))

	def _set_interval_action(self, interval_seconds: int):
		return self._action(lambda: self.on_set_interval(interval_seconds))

	def _set_language_action(self, language: str):
		return self._action(lambda: setattr(self, "language", self._normalize_language(language)))

	def _mode_checked(self, mode: str):
		return lambda item: self.get_mode() == mode or (mode == "asia_2k" and self.get_mode() == "asia")

	def _interval_checked(self, interval_seconds: int):
		return lambda item: self.get_interval() == interval_seconds

	def _language_checked(self, language: str):
		return lambda item: self.language == language

	def _build_menu(self) -> pystray.Menu:
		return pystray.Menu(
			pystray.MenuItem(self._text("refresh_once"), self._action(self.on_refresh)),
			pystray.MenuItem(self._text("force_refresh"), self._action(self.on_force_refresh)),
			pystray.MenuItem(
				self._text("mode"),
				pystray.Menu(
					pystray.MenuItem(
						self._text("earth"),
						pystray.Menu(
							pystray.MenuItem(self._text("goes"), self._switch_mode_action("earth"), checked=self._mode_checked("earth"), radio=True),
							pystray.MenuItem(self._text("asia_2k"), self._switch_mode_action("asia_2k"), checked=self._mode_checked("asia_2k"), radio=True),
							pystray.MenuItem(self._text("asia_4k"), self._switch_mode_action("asia_4k"), checked=self._mode_checked("asia_4k"), radio=True),
						),
					),
					pystray.MenuItem(
						self._text("sky"),
						pystray.Menu(
							pystray.MenuItem(self._text("apod"), self._switch_mode_action("sky"), checked=self._mode_checked("sky"), radio=True),
							pystray.MenuItem(self._text("sun"), self._switch_mode_action("sun_sdo"), checked=self._mode_checked("sun_sdo"), radio=True),
							pystray.MenuItem(self._text("mars"), self._switch_mode_action("mars"), checked=self._mode_checked("mars"), radio=True),
						),
					),
				),
			),
			pystray.MenuItem(
				self._text("refresh_rate"),
				pystray.Menu(
					pystray.MenuItem(self._text("low"), self._set_interval_action(60 * 60), checked=self._interval_checked(60 * 60), radio=True),
					pystray.MenuItem(self._text("medium"), self._set_interval_action(30 * 60), checked=self._interval_checked(30 * 60), radio=True),
					pystray.MenuItem(self._text("high"), self._set_interval_action(5 * 60), checked=self._interval_checked(5 * 60), radio=True),
				),
			),
			pystray.MenuItem(self._text("log_window"), self._action(self.on_toggle_log_window), checked=lambda item: self.is_log_window_open()),
			pystray.MenuItem(
				self._text("language"),
				pystray.Menu(
					pystray.MenuItem(self._text("chinese"), self._set_language_action("zh"), checked=self._language_checked("zh"), radio=True),
					pystray.MenuItem(self._text("english"), self._set_language_action("en"), checked=self._language_checked("en"), radio=True),
				),
			),
			pystray.MenuItem(self._text("quit"), self._action(self.on_quit)),
		)

	def run(self):
		icon = pystray.Icon(APP_NAME, _create_icon(), self._title(), self._build_menu())
		self._icon = icon
		log.info("tray starting...")
		icon.run()

	def stop(self):
		if self._icon:
			log.info("tray stopping...")
			self._icon.stop()
