import json
import os
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


def load_config() -> dict:
	"""Load persisted config, falling back to defaults. Tolerant of corruption.
	Sets a runtime-only `_loaded` flag indicating an actual file was read."""
	cfg = dict(DEFAULTS)
	cfg["_loaded"] = False
	try:
		with open(CONFIG_PATH, "r", encoding="utf-8") as f:
			data = json.load(f)
		if isinstance(data, dict):
			cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
		cfg["_loaded"] = True
	except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
		pass
	return cfg


def save_config(cfg: dict) -> None:
	"""Atomically persist config to %APPDATA%/HelloPlanet/config.json."""
	try:
		os.makedirs(CONFIG_DIR, exist_ok=True)
		tmp = CONFIG_PATH + ".tmp"
		with open(tmp, "w", encoding="utf-8") as f:
			json.dump({k: cfg.get(k, DEFAULTS[k]) for k in DEFAULTS}, f, ensure_ascii=False, indent=2)
		os.replace(tmp, CONFIG_PATH)
	except OSError:
		# Non-fatal: persistence is best-effort and must not break the app.
		pass


def resolve(initial: Optional[str], key: str, env_key: Optional[str] = None):
	"""Precedence: explicit CLI > saved config (if a file exists) > env var > default."""
	if initial:
		return initial
	cfg = load_config()
	if cfg.get("_loaded"):
		val = cfg.get(key)
		if val not in (None, ""):
			return val
	if env_key:
		env_val = os.getenv(env_key)
		if env_val:
			return env_val
	return DEFAULTS[key]
