import hashlib
import os
import tempfile
import logging
from typing import Optional

from PIL import Image


CACHE_DIR = os.path.join(tempfile.gettempdir(), "hello_planet")
LAST_META = os.path.join(CACHE_DIR, "last.txt")


def ensure_cache_dir() -> None:
	os.makedirs(CACHE_DIR, exist_ok=True)


def md5_of_image(img: Image.Image) -> str:
	# Resize before converting: avoid a full-resolution RGB duplicate.
	ratio = min(1.0, 1024 / max(img.size))
	size = (max(1, round(img.width * ratio)), max(1, round(img.height * ratio)))
	with img.resize(size, Image.Resampling.BILINEAR, reducing_gap=1.0) as preview:
		with preview.convert("RGB") as rgb:
			return hashlib.md5(rgb.tobytes()).hexdigest()


def read_last() -> tuple[Optional[str], Optional[str]]:
	try:
		with open(LAST_META, "r", encoding="utf-8") as f:
			parts = f.read(8192).split("\n")
			url = parts[0] or None
			hashv = parts[1] if len(parts) > 1 else None
			return url, hashv
	except (OSError, UnicodeError):
		return None, None


def write_last(url: str, hashv: str) -> None:
	temp = None
	try:
		ensure_cache_dir()
		with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=CACHE_DIR, delete=False) as file:
			temp = file.name
			file.write(url + "\n" + hashv)
		os.replace(temp, LAST_META)
	except OSError as error:
		logging.getLogger(__name__).warning("Could not save wallpaper metadata: %s", error)
	finally:
		if temp:
			try:
				os.unlink(temp)
			except OSError:
				pass
