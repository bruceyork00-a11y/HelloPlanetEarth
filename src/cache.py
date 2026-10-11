import hashlib
import os
import tempfile
from typing import Optional

from PIL import Image


CACHE_DIR = os.path.join(tempfile.gettempdir(), "hello_planet")
LAST_META = os.path.join(CACHE_DIR, "last.txt")


def ensure_cache_dir() -> None:
	os.makedirs(CACHE_DIR, exist_ok=True)


def md5_of_image(img: Image.Image) -> str:
	# Compute MD5 of raw RGB bytes at a moderate size to stabilize across formats
	with img.convert("RGB") as preview:
		preview.thumbnail((1024, 1024))
		return hashlib.md5(preview.tobytes()).hexdigest()


def read_last() -> tuple[Optional[str], Optional[str]]:
	try:
		with open(LAST_META, "r", encoding="utf-8") as f:
			parts = f.read().split("\n")
			url = parts[0] or None
			hashv = parts[1] if len(parts) > 1 else None
			return url, hashv
	except FileNotFoundError:
		return None, None


def write_last(url: str, hashv: str) -> None:
	ensure_cache_dir()
	with open(LAST_META, "w", encoding="utf-8") as f:
		f.write(url + "\n" + hashv)
