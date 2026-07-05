import logging
import os
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
	fh = RotatingFileHandler(get_log_path(), maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
	fh.setLevel(numeric_level)
	fh.setFormatter(formatter)
	logger.addHandler(fh)

