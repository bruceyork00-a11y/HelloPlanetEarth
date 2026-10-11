"""Bounded, lossless cache for immutable, timestamped satellite frames."""
import hashlib
import logging
import os
import tempfile
import threading
from pathlib import Path

from PIL import Image

CACHE_DIR = Path(os.getenv("LOCALAPPDATA", tempfile.gettempdir())) / "HelloPlanet" / "frames"
MAX_BYTES = 128 * 1024 * 1024
MAX_PIXELS = 32_000_000
_lock = threading.Lock()
log = logging.getLogger(__name__)


def _path(key):
    return CACHE_DIR / (hashlib.sha256(key.encode("utf-8")).hexdigest() + ".png")


def get(key):
    path = _path(key)
    image = None
    try:
        if path.is_symlink() or path.stat().st_size > MAX_BYTES:
            return None
        with Image.open(path, formats=["PNG"]) as original:
            if original.width * original.height > MAX_PIXELS:
                return None
            original.load()
            image = original.convert("RGB")
        os.utime(path, None)
        image.info["cache_hit"] = True
        return image
    except (OSError, ValueError, Image.DecompressionBombError):
        if image is not None:
            image.close()
        return None


def put(key, image):
    temp = None
    try:
        with _lock:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=CACHE_DIR, suffix=".tmp", delete=False) as file:
                temp = file.name
            image.save(temp, format="PNG", compress_level=1)
            os.replace(temp, _path(key))
            files = sorted(CACHE_DIR.glob("*.png"), key=lambda path: path.stat().st_mtime, reverse=True)
            total = 0
            for index, path in enumerate(files):
                total += path.stat().st_size
                if index >= 3 or total > MAX_BYTES:
                    path.unlink(missing_ok=True)
    except (OSError, ValueError) as error:
        log.debug("Frame cache unavailable: %s", error)
    finally:
        if temp:
            try:
                os.unlink(temp)
            except FileNotFoundError:
                pass
            except OSError:
                pass
