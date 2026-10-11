import json
import os
import tempfile
import logging
from typing import Optional


APP_NAME = "HelloPlanet"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULTS = {
	"mode": "earth",
	"interval": 1800,
	"language": "zh",
	"style": "fill",
}
MODES = {"earth", "goes_west", "asia", "asia_2k", "asia_4k", "asia_custom",
         "asia_gk2a", "asia_modis", "earth_epic", "sky", "sun_sdo", "mars"}
STYLES = {"fill", "fit", "stretch", "center", "tile"}
log = logging.getLogger(__name__)


def validate(value, key):
	if key == "interval":
		if isinstance(value, bool) or not isinstance(value, (int, str)):
			raise ValueError("Refresh interval must be an integer")
		value = int(value)
		if not 300 <= value <= 86400:
			raise ValueError("Refresh interval must be between 300 and 86400 seconds")
		return value
	allowed = {"mode": MODES, "style": STYLES, "language": {"zh", "en"}}[key]
	if not isinstance(value, str) or value.lower() not in allowed:
		raise ValueError(f"Invalid {key}")
	return value.lower()


def load_config() -> dict:
	"""Load persisted config, falling back to defaults. Tolerant of corruption.
	Sets a runtime-only `_loaded` flag indicating an actual file was read."""
	cfg = dict(DEFAULTS)
	cfg["_loaded"] = False
	cfg["_valid_keys"] = []
	try:
		with open(CONFIG_PATH, "r", encoding="utf-8") as f:
			text = f.read(16385)
			if len(text) > 16384:
				return cfg
			data = json.loads(text)
		if isinstance(data, dict):
			for key in DEFAULTS:
				if key in data:
					try:
						cfg[key] = validate(data[key], key)
						cfg["_valid_keys"].append(key)
					except (ValueError, TypeError):
						pass
			cfg["_loaded"] = True
	except (OSError, ValueError, RecursionError):
		pass
	return cfg


def save_config(cfg: dict) -> bool:
	"""Atomically persist config to %APPDATA%/HelloPlanet/config.json."""
	tmp = None
	try:
		os.makedirs(CONFIG_DIR, exist_ok=True)
		data = {key: validate(cfg.get(key, DEFAULTS[key]), key) for key in DEFAULTS}
		with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=CONFIG_DIR, delete=False) as f:
			tmp = f.name
			json.dump(data, f, ensure_ascii=False, indent=2)
		os.replace(tmp, CONFIG_PATH)
		return True
	except (OSError, ValueError, TypeError) as error:
		log.warning("Could not save settings: %s", error)
		return False
	finally:
		if tmp and os.path.exists(tmp):
			try:
				os.unlink(tmp)
			except OSError:
				pass


def resolve(initial: Optional[str], key: str, env_key: Optional[str] = None):
	"""Precedence: explicit CLI > saved config (if a file exists) > env var > default."""
	if initial is not None:
		return validate(initial, key)
	cfg = load_config()
	if key in cfg.get("_valid_keys", []):
		val = cfg.get(key)
		if val not in (None, ""):
			return val
	if env_key:
		env_val = os.getenv(env_key)
		if env_val:
			try:
				return validate(env_val, key)
			except (ValueError, TypeError):
				log.warning("Invalid %s; using default", env_key)
	return DEFAULTS[key]
