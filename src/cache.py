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
	preview = img.copy()
	preview = preview.convert("RGB")
	max_side = 1024
	w, h = preview.size
	if max(w, h) > max_side:
		ratio = max_side / max(w, h)
		preview = preview.resize((int(w * ratio), int(h * ratio)))
	rgb_bytes = preview.tobytes()
	return hashlib.md5(rgb_bytes).hexdigest()


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
