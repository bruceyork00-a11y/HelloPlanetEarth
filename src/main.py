import argparse
import os
import subprocess
import sys
import time
import threading
import logging
from datetime import datetime
from typing import Callable, Optional, Tuple

from PIL import Image

from .sources import (
	fetch_earth_best_effort,
	fetch_sky_best_effort,
	fetch_asia_pacific_best_effort,
	fetch_asia_pacific_2k_best_effort,
	fetch_asia_pacific_4k_best_effort,
	fetch_sdo_latest,
	fetch_mars_best_effort,
	fetch_goes_west_best_effort,
	fetch_gk2a_latest,
	fetch_epic_latest,
	fetch_worldview_asia_latest,
	download_scope,
)
from .wallpaper import set_wallpaper_from_image
from .cache import read_last, write_last, md5_of_image
from .logging_setup import setup_logging, get_log_path, install_crash_handler
from .config import load_config, save_config, resolve
from .tray import TrayController


log = logging.getLogger(__name__)

APP_NAME = "HelloPlanet"
DEFAULT_INTERVAL_SECONDS = 30 * 60
REFRESH_INTERVALS = {
	"low": 60 * 60,
	"medium": 30 * 60,
	"high": 5 * 60,
}

# Keep the single-instance mutex alive for the whole process lifetime.
_INSTANCE_MUTEX = None


def _fetcher(mode: str) -> Callable[[], Tuple[Image.Image, str]]:
	if mode == "earth":
		return fetch_earth_best_effort
	elif mode == "goes_west":
		return fetch_goes_west_best_effort
	elif mode == "asia_gk2a":
		return fetch_gk2a_latest
	elif mode == "earth_epic":
		return fetch_epic_latest
	elif mode == "asia_modis":
		return fetch_worldview_asia_latest
	elif mode in ("asia", "asia_2k"):
		return fetch_asia_pacific_2k_best_effort
	elif mode == "asia_4k":
		return fetch_asia_pacific_4k_best_effort
	elif mode == "asia_custom":
		return fetch_asia_pacific_best_effort
	elif mode == "sky":
		return fetch_sky_best_effort
	elif mode == "sun_sdo":
		return fetch_sdo_latest
	elif mode == "mars":
		return fetch_mars_best_effort
	else:
		raise ValueError(f"mode '{mode}' is not valid")


class Runner:
	def __init__(self, mode: str, interval_seconds: int, style: str, on_updated: Optional[Callable[[datetime], None]] = None):
		self.mode = mode
		self.interval_seconds = interval_seconds
		self.style = style
		self.on_updated = on_updated
		self.last_update_time: Optional[datetime] = None
		self._stop = threading.Event()
		self._wakeup = threading.Event()
		self._lock = threading.RLock()
		self._tick_lock = threading.Lock()
		self._force_refresh_requested = False
		self._mode_version = 0
		self._thread = None

	def _tick_once(self, force: bool = False) -> None:
		with self._tick_lock:
			with self._lock:
				mode = self.mode
				style = self.style
				mode_version = self._mode_version
			fetch = _fetcher(mode)
			img = None
			try:
				with download_scope(self._stop):
					img, url = fetch()
				hashv = md5_of_image(img)
				last_url, last_hash = read_last()
				log.info(f"tick: mode={mode} url={url} hash={hashv} last_url={last_url} last_hash={last_hash} force={force}")
				with self._lock:
					# Do not let an older download overwrite a newly selected mode.
					if self._stop.is_set() or mode_version != self._mode_version:
						log.info(f"tick: discard stale result for mode={mode}")
						return
					if not force and last_url == url and last_hash == hashv:
						log.info("tick: skip same image (url+hash)")
						return
					set_wallpaper_from_image(img, style=style)
					write_last(url, hashv)
					updated_at = datetime.now()
					self.last_update_time = updated_at
				if self.on_updated:
					self.on_updated(updated_at)
				log.info("tick: wallpaper updated")
			finally:
				if img is not None:
					img.close()

	def loop(self):
		log.info(f"runner start: mode={self.mode} interval={self.interval_seconds}s style={self.style}")
		last_start = time.monotonic()
		while not self._stop.is_set():
			with self._lock:
				self._wakeup.clear()
				interval_seconds = self.interval_seconds
				force = self._force_refresh_requested
				self._force_refresh_requested = False
			# Detect a long gap (machine slept/woken): the wallpaper is now stale.
			now = time.monotonic()
			if now - last_start > interval_seconds + 300:
				log.info("loop: long gap (sleep/wake?) detected, forcing refresh")
				force = True
			try:
				self._tick_once(force=force)
			except Exception as e:
				log.error(f"runner error: {e}")
			last_start = time.monotonic()
			if self._stop.is_set():
				break
			with self._lock:
				interval_seconds = self.interval_seconds
			self._wakeup.wait(interval_seconds)
		log.info("runner stopped")

	def start(self):
		self._thread = threading.Thread(target=self.loop, daemon=True)
		self._thread.start()

	def stop(self):
		self._stop.set()
		self._wakeup.set()
		if self._thread:
			self._thread.join(timeout=3)

	def force_refresh_now(self):
		"""Schedule a cache-bypassing refresh without blocking the tray UI."""
		with self._lock:
			self._force_refresh_requested = True
			self._wakeup.set()
		log.info("force refresh requested")

	def switch_mode(self, new_mode: str):
		with self._lock:
			log.info(f"switch mode: {self.mode} -> {new_mode}")
			self.mode = new_mode
			self._mode_version += 1
			self._force_refresh_requested = True
			self._wakeup.set()
		log.info(f"mode refresh requested: {new_mode}")

	def set_interval(self, interval_seconds: int):
		with self._lock:
			log.info(f"switch interval: {self.interval_seconds}s -> {interval_seconds}s")
			self.interval_seconds = interval_seconds
			self._wakeup.set()

	def get_mode(self) -> str:
		with self._lock:
			return self.mode

	def get_interval(self) -> int:
		with self._lock:
			return self.interval_seconds

	def get_last_update_text(self) -> str:
		with self._lock:
			if self.last_update_time is None:
				return "尚未更新"
			return self.last_update_time.strftime("%H:%M:%S")

	def get_last_update_time(self) -> Optional[datetime]:
		with self._lock:
			return self.last_update_time


def run_with_tray(mode: str, interval_seconds: int, style: str) -> None:
	setup_logging(os.getenv("LOG_LEVEL", "INFO"), enable_console=False)
	log.info(f"{APP_NAME} starting...")
	cfg = load_config()
	# On first run (no saved config), still honor the HELLOPLANET_LANG env var.
	initial_language = cfg.get("language") if cfg.get("_loaded") else None
	log_window_process: Optional[subprocess.Popen] = None

	def on_force_refresh():
		runner.force_refresh_now()

	def on_switch(new_mode: str):
		runner.switch_mode(new_mode)
		cfg["mode"] = new_mode
		save_config(cfg)

	def on_set_interval(interval: int):
		runner.set_interval(interval)
		cfg["interval"] = interval
		save_config(cfg)

	def on_set_language(language: str):
		cfg["language"] = language
		save_config(cfg)

	def is_log_window_open() -> bool:
		nonlocal log_window_process
		if log_window_process is None:
			return False
		if log_window_process.poll() is not None:
			log_window_process = None
			return False
		return True

	def on_toggle_log_window():
		nonlocal log_window_process
		path = get_log_path()
		if is_log_window_open():
			log_window_process.terminate()
			log_window_process = None
			return
		log_window_process = subprocess.Popen(["notepad.exe", path])

	def on_quit():
		log.info("quit requested")
		if is_log_window_open():
			log_window_process.terminate()
		runner.stop()
		tray.stop()

	runner = Runner(mode, interval_seconds, style)
	tray = TrayController(
		on_force_refresh=on_force_refresh,
		on_switch_mode=on_switch,
		on_set_interval=on_set_interval,
		on_toggle_log_window=on_toggle_log_window,
		on_set_language=on_set_language,
		is_log_window_open=is_log_window_open,
		on_quit=on_quit,
		initial_language=initial_language,
		get_mode=runner.get_mode,
		get_interval=runner.get_interval,
		get_last_update_time=runner.get_last_update_time,
	)
	runner.on_updated = tray.set_last_update
	runner.start()
	tray.run()


def parse_args(argv: list) -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="HelloPlanet realtime wallpaper")
	parser.add_argument(
		"--mode",
		choices=["earth", "goes_west", "asia", "asia_2k", "asia_4k", "asia_custom", "asia_gk2a", "asia_modis", "earth_epic", "sky", "sun_sdo", "mars"],
		default=None,
	)
	parser.add_argument("--interval", type=int, default=None)
	parser.add_argument("--style", choices=["center", "stretch", "fit", "fill", "tile"], default=None)
	parser.add_argument("--no-tray", action="store_true", help="禁用系统托盘，仅控制台运行")
	parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
	return parser.parse_args(argv)


def _ensure_single_instance() -> bool:
	"""Return True if this process may continue, False if another instance owns
	the mutex. Windows-only; other platforms always allow."""
	global _INSTANCE_MUTEX
	if sys.platform != "win32":
		return True
	try:
		import ctypes
		kernel32 = ctypes.windll.kernel32
		user = os.getenv("USERNAME", "default")
		name = "Local\\HelloPlanet_Instance_" + "".join(c if c.isalnum() else "_" for c in user)
		handle = kernel32.CreateMutexW(None, False, name)
		if not handle:
			return True
		_INSTANCE_MUTEX = handle
		if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
			return False
		return True
	except Exception as e:
		log.warning(f"single-instance check failed (proceeding): {e}")
		return True


def main(argv: list) -> int:
	install_crash_handler()
	args = parse_args(argv)
	if not _ensure_single_instance():
		log.warning("another HelloPlanet instance is already running; exiting")
		return 1
	mode = resolve(args.mode, "mode", "MODE")
	interval = int(resolve(args.interval, "interval", "INTERVAL_SECONDS") or DEFAULT_INTERVAL_SECONDS)
	style = resolve(args.style, "style")
	if args.no_tray:
		setup_logging(args.log_level, enable_console=True)
		log.info("console-only mode")
		runner = Runner(mode, interval, style)
		runner.start()
		try:
			while True:
				time.sleep(3600)
		except KeyboardInterrupt:
			log.info("keyboard interrupt")
			runner.stop()
	else:
		run_with_tray(mode, interval, style)
	return 0


if __name__ == "__main__":
	sys.exit(main(sys.argv[1:]))
