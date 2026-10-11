import argparse
import os
import subprocess
import sys
import time
import threading
import logging
import atexit
from datetime import datetime, timedelta
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
	DownloadCancelled,
	close_session,
)
from .wallpaper import set_wallpaper_from_image
from .cache import read_last, write_last, md5_of_image
from .logging_setup import setup_logging, get_log_path, install_crash_handler
from .config import load_config, save_config, resolve, validate
from .tray import TrayController
from .version import VERSION


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
		self.mode = validate(mode, "mode")
		self.interval_seconds = validate(interval_seconds, "interval")
		self.style = validate(style, "style")
		self.on_updated = on_updated
		self.last_update_time: Optional[datetime] = None
		self._stop = threading.Event()
		self._wakeup = threading.Event()
		self._lock = threading.RLock()
		self._tick_lock = threading.Lock()
		self._force_refresh_requested = False
		self._bypass_cache_requested = False
		self._download_cancel = threading.Event()
		self._last_applied = None
		self._failures = 0
		self.on_status_changed = None
		self._status = {"state": "idle", "progress": None, "last_checked": None,
			"next_check": None, "resolution": None, "notice": None}
		self._last_progress = 0.0
		self._mode_version = 0
		self._thread = None

	def get_status(self):
		with self._lock:
			return dict(self._status)

	def _publish(self, state=None, version=None, **changes):
		with self._lock:
			if version is not None and version != self._mode_version:
				return
			if state:
				self._status["state"] = state
			self._status.update(changes)
			snapshot = dict(self._status)
		if self.on_status_changed:
			try:
				self.on_status_changed(snapshot)
			except Exception:
				log.debug("status callback failed", exc_info=True)

	def _progress(self, version, completed, total):
		with self._lock:
			if version != self._mode_version or self._stop.is_set():
				return
			now = time.monotonic()
			if completed != total and now - self._last_progress < 0.25:
				return
			self._last_progress = now
		self._publish(version=version, progress=(completed, total))

	def _tick_once(self, force: bool = False, bypass_cache=None) -> None:
		with self._tick_lock:
			with self._lock:
				mode = self.mode
				style = self.style
				mode_version = self._mode_version
				cancel = self._download_cancel
				if self._stop.is_set():
					return
			self._publish("updating", version=mode_version, progress=None, next_check=None)
			fetch = _fetcher(mode)
			img = None
			try:
				with download_scope(cancel, force=force if bypass_cache is None else bypass_cache,
					progress=lambda done, total: self._progress(mode_version, done, total)):
					img, url = fetch()
				hashv = md5_of_image(img)
				last_url, last_hash = read_last()
				log.info(f"tick: mode={mode} url={url} hash={hashv} last_url={last_url} last_hash={last_hash} force={force}")
				with self._lock:
					# Do not let an older download overwrite a newly selected mode.
					if self._stop.is_set() or mode_version != self._mode_version:
						log.info(f"tick: discard stale result for mode={mode}")
						return
					skip = not force and last_url == url and last_hash == hashv and self._last_applied == (mode, style)
				if skip:
					self._failures = 0
					self._publish("unchanged", version=mode_version, last_checked=datetime.now(), progress=None)
					return
				# Native wallpaper I/O must not hold the lock needed by tray actions.
				set_wallpaper_from_image(img, style=style)
				write_last(url, hashv)
				updated_at = datetime.now()
				with self._lock:
					if self._stop.is_set() or mode_version != self._mode_version:
						return
					self.last_update_time = updated_at
					self._last_applied = (mode, style)
					self._failures = 0
				if self.on_updated:
					self.on_updated(updated_at)
				log.info("tick: wallpaper updated")
				self._publish("updated", version=mode_version, last_checked=updated_at, progress=None, resolution=img.size)
			except DownloadCancelled:
				log.info("obsolete or stopped download cancelled")
			except Exception:
				with self._lock:
					current = mode_version == self._mode_version and not self._stop.is_set()
					if current:
						self._failures += 1
				if current:
					self._publish("error", version=mode_version, progress=None, last_checked=datetime.now())
				raise
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
				bypass = self._bypass_cache_requested
				self._bypass_cache_requested = False
			# Detect a long gap (machine slept/woken): the wallpaper is now stale.
			now = time.monotonic()
			if now - last_start > interval_seconds + 300:
				log.info("loop: long gap (sleep/wake?) detected, forcing refresh")
				force = True
			try:
				self._tick_once(force=force, bypass_cache=bypass)
			except Exception as e:
				log.error(f"runner error: {e}")
			last_start = time.monotonic()
			if self._stop.is_set():
				break
			with self._lock:
				interval_seconds = self.interval_seconds
				interval_seconds = min(interval_seconds * (2 ** min(max(self._failures - 1, 0), 4)), max(3600, interval_seconds))
			self._publish(next_check=datetime.now() + timedelta(seconds=interval_seconds))
			self._wakeup.wait(interval_seconds)
		log.info("runner stopped")
		close_session()

	def start(self):
		with self._lock:
			if self._stop.is_set() or (self._thread and self._thread.is_alive()):
				return
			self._thread = threading.Thread(target=self.loop, daemon=True)
			self._thread.start()

	def stop(self, wait=True):
		with self._lock:
			self._stop.set()
			self._download_cancel.set()
			self._wakeup.set()
		if wait and self._thread and self._thread is not threading.current_thread():
			self._thread.join(timeout=3)

	def force_refresh_now(self):
		"""Schedule a cache-bypassing refresh without blocking the tray UI."""
		with self._lock:
			if self._status["state"] == "updating" or self._stop.is_set():
				return False
			self._force_refresh_requested = True
			self._bypass_cache_requested = True
			self._wakeup.set()
		log.info("force refresh requested")
		return True

	def switch_mode(self, new_mode: str):
		new_mode = validate(new_mode, "mode")
		with self._lock:
			if self.mode == new_mode:
				return
			log.info(f"switch mode: {self.mode} -> {new_mode}")
			self.mode = new_mode
			self._mode_version += 1
			self._download_cancel.set()
			self._download_cancel = threading.Event()
			self._failures = 0
			self._force_refresh_requested = True
			self._status.update(state="updating", progress=None, next_check=None)
			self._wakeup.set()
		log.info(f"mode refresh requested: {new_mode}")
		self._publish()

	def set_style(self, style):
		style = validate(style, "style")
		with self._lock:
			if style == self.style:
				return
			self.style = style
			self._mode_version += 1
			self._download_cancel.set()
			self._download_cancel = threading.Event()
			self._force_refresh_requested = True
			self._status.update(state="updating", progress=None, next_check=None)
			self._wakeup.set()
		self._publish()

	def get_style(self):
		with self._lock:
			return self.style

	def set_interval(self, interval_seconds: int):
		interval_seconds = validate(interval_seconds, "interval")
		with self._lock:
			log.info(f"switch interval: {self.interval_seconds}s -> {interval_seconds}s")
			self.interval_seconds = interval_seconds
			# Wake promptly to recompute the schedule after a setting change.
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
	cfg.update(mode=mode, interval=interval_seconds, style=style)
	# On first run (no saved config), still honor the HELLOPLANET_LANG env var.
	initial_language = cfg.get("language") if "language" in cfg.get("_valid_keys", []) else None
	log_window_process: Optional[subprocess.Popen] = None

	def persist():
		runner._publish(notice=None if save_config(cfg) else "settings_unsaved")

	def on_force_refresh():
		runner.force_refresh_now()

	def on_switch(new_mode: str):
		runner.switch_mode(new_mode)
		cfg["mode"] = new_mode
		persist()

	def on_set_style(style):
		runner.set_style(style)
		cfg["style"] = style
		persist()

	def on_set_interval(interval: int):
		runner.set_interval(interval)
		cfg["interval"] = interval
		persist()

	def on_set_language(language: str):
		cfg["language"] = language
		persist()

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
		notepad = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "notepad.exe")
		log_window_process = subprocess.Popen([notepad, path])

	def on_quit():
		log.info("quit requested")
		if is_log_window_open():
			log_window_process.terminate()
		runner.stop(wait=False)
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
		get_status=runner.get_status,
		on_set_style=on_set_style,
		get_style=runner.get_style,
	)
	runner.on_updated = tray.set_last_update
	runner.on_status_changed = tray.set_status
	runner.start()
	try:
		tray.run()
	finally:
		runner.stop()


def parse_args(argv: list) -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="HelloPlanet realtime wallpaper")
	parser.add_argument("--version", action="version", version=f"HelloPlanet {VERSION}")
	parser.add_argument(
		"--mode",
		choices=["earth", "goes_west", "asia", "asia_2k", "asia_4k", "asia_custom", "asia_gk2a", "asia_modis", "earth_epic", "sky", "sun_sdo", "mars"],
		default=None,
	)
	def interval_arg(value):
		try:
			return validate(value, "interval")
		except ValueError as error:
			raise argparse.ArgumentTypeError(str(error)) from error
	parser.add_argument("--interval", type=interval_arg, default=None)
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
		from ctypes import wintypes
		kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
		kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
		kernel32.CreateMutexW.restype = wintypes.HANDLE
		kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
		kernel32.CloseHandle.restype = wintypes.BOOL
		user = os.getenv("USERNAME", "default")
		name = "Local\\HelloPlanet_Instance_" + "".join(c if c.isalnum() else "_" for c in user)
		handle = kernel32.CreateMutexW(None, False, name)
		if not handle:
			raise ctypes.WinError(ctypes.get_last_error())
		_INSTANCE_MUTEX = handle
		if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
			kernel32.CloseHandle(handle)
			_INSTANCE_MUTEX = None
			return False
		atexit.register(kernel32.CloseHandle, handle)
		return True
	except Exception as e:
		log.error(f"single-instance check failed: {e}")
		return False


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
