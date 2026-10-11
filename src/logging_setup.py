import logging
import os
import sys
import threading
import traceback
import tempfile
from logging.handlers import RotatingFileHandler


def get_log_dir() -> str:
	log_dir = os.path.join(tempfile.gettempdir(), "hello_planet")
	os.makedirs(log_dir, exist_ok=True)
	return log_dir


def get_log_path() -> str:
	return os.path.join(get_log_dir(), "app.log")


def setup_logging(level: str = "INFO", enable_console: bool = True) -> None:
	numeric_level = getattr(logging, level.upper(), logging.INFO)
	logger = logging.getLogger()
	logger.setLevel(numeric_level)

	# Clear existing handlers to avoid duplicates
	for h in list(logger.handlers):
		logger.removeHandler(h)
		h.close()

	formatter = logging.Formatter(
		fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
		datefmt="%Y-%m-%d %H:%M:%S",
	)

	if enable_console:
		ch = logging.StreamHandler()
		ch.setLevel(numeric_level)
		ch.setFormatter(formatter)
		logger.addHandler(ch)

	# Rotating file handler
	try:
		fh = RotatingFileHandler(get_log_path(), maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
		fh.setLevel(numeric_level)
		fh.setFormatter(formatter)
		logger.addHandler(fh)
	except OSError:
		if not logger.handlers:
			logger.addHandler(logging.NullHandler())


def install_crash_handler() -> None:
	"""Install last-resort handlers so an unhandled exception is recorded to the
	log file instead of silently vanishing (the tray icon just disappears)."""
	try:
		log_path = get_log_path()
	except OSError:
		log_path = None

	def _emit(exc_type, exc, tb):
		try:
			logging.getLogger().critical("unhandled exception, app exiting", exc_info=(exc_type, exc, tb))
		except Exception:
			pass
		try:
			with open(log_path, "a", encoding="utf-8") as f:
				traceback.print_exception(exc_type, exc, tb, file=f)
		except Exception:
			pass

	def _excepthook(exc_type, exc, tb):
		_emit(exc_type, exc, tb)
		# Let a hard crash still produce a visible error via stderr as a fallback.
		if sys.stderr is not None:
			traceback.print_exception(exc_type, exc, tb, file=sys.stderr)

	def _threading_excepthook(args):
		# Called for exceptions in threads other than the main thread.
		_emit(args.exc_type, args.exc_value, args.exc_traceback)

	sys.excepthook = _excepthook
	threading.excepthook = _threading_excepthook

