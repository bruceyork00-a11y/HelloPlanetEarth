import os
import io
import json
import datetime as dt
import logging
import re
from typing import Optional, Tuple

import requests
from PIL import Image
import certifi
from requests.exceptions import SSLError

# Guard against decompression bombs / malicious oversized images from any source.
Image.MAX_IMAGE_PIXELS = 120_000_000

NASA_API_KEY = os.getenv("NASA_API_KEY", "DEMO_KEY")

USER_AGENT = "HelloPlanet/1.2 (+https://anyanygame.com)"
TIMEOUT = 20
log = logging.getLogger(__name__)


class SourceError(Exception):
	pass


def _download_image(url: str, allow_insecure: bool = False, extra_headers: Optional[dict] = None) -> Image.Image:
	headers = {"User-Agent": USER_AGENT, "Cache-Control": "no-cache"}
	if extra_headers:
		headers.update(extra_headers)
	verify_path = False if allow_insecure else certifi.where()
	if allow_insecure:
		log.warning("SECURITY: TLS certificate verification DISABLED for this download (ALLOW_INSECURE_*=1)")
	log.info(f"download start: {url} insecure={allow_insecure}")
	resp = requests.get(url, headers=headers, timeout=TIMEOUT, verify=verify_path)
	log.info(f"download response: status={resp.status_code} bytes={len(resp.content)}")
	resp.raise_for_status()
	try:
		return Image.open(io.BytesIO(resp.content))
	except Image.DecompressionBombError as e:
		raise SourceError(f"image too large (possible decompression bomb): {url}") from e


# --- Himawari-8/9 (NICT/Kyoto mirrors) ---
# D531106 is the full-disk visible composite used by the real-time Himawari web
# viewer. The public mirrors share the same latest.json and tile path layout.

HIMAWARI_TILE_SIZE = 550
HIMAWARI_DEFAULT_TILE_COUNT = 4
HIMAWARI_ALLOWED_TILE_COUNTS = {1, 2, 4, 8, 16, 20}

HIMAWARI_SOURCES = [
	(
		"himawari.asia web / Kyoto tiles",
		"https://himawari.asia/img/D531106/latest.json",
		"https://jh190005-4.kudpc.kyoto-u.ac.jp/himawari/img/D531106/{count}d/550/{y}/{m}/{d}/{h}{mi}{s}_{x}_{tile_y}.png",
	),
	(
		"Kyoto Himawari mirror",
		"https://jh190005-4.kudpc.kyoto-u.ac.jp/himawari/img/D531106/latest.json",
		"https://jh190005-4.kudpc.kyoto-u.ac.jp/himawari/img/D531106/{count}d/550/{y}/{m}/{d}/{h}{mi}{s}_{x}_{tile_y}.png",
	),
	(
		"himawari.asia direct",
		"https://himawari.asia/img/D531106/latest.json",
		"https://himawari.asia/img/D531106/{count}d/550/{y}/{m}/{d}/{h}{mi}{s}_{x}_{tile_y}.png",
	),
	(
		"NICT",
		"https://himawari8.nict.go.jp/img/D531106/latest.json",
		"https://himawari8.nict.go.jp/img/D531106/{count}d/550/{y}/{m}/{d}/{h}{mi}{s}_{x}_{tile_y}.png",
	),
	(
		"NICT download mirror",
		"https://himawari8-dl.nict.go.jp/himawari8/img/D531106/latest.json",
		"https://himawari8-dl.nict.go.jp/himawari8/img/D531106/{count}d/550/{y}/{m}/{d}/{h}{mi}{s}_{x}_{tile_y}.png",
	),
]


def _himawari_tile_count(preferred_count: Optional[int] = None) -> int:
	raw_count = str(preferred_count) if preferred_count is not None else os.getenv("HIMAWARI_TILE_COUNT", str(HIMAWARI_DEFAULT_TILE_COUNT))
	try:
		count = int(raw_count)
	except ValueError:
		log.warning(f"invalid HIMAWARI_TILE_COUNT={raw_count!r}, using {HIMAWARI_DEFAULT_TILE_COUNT}")
		return HIMAWARI_DEFAULT_TILE_COUNT
	if count not in HIMAWARI_ALLOWED_TILE_COUNTS:
		log.warning(f"unsupported HIMAWARI_TILE_COUNT={count}, using {HIMAWARI_DEFAULT_TILE_COUNT}")
		return HIMAWARI_DEFAULT_TILE_COUNT
	return count


def _himawari_tile_url(image_template: str, dt_obj: dt.datetime, count: int, x: int, y: int) -> str:
	return image_template.format(
		count=count,
		y=dt_obj.strftime("%Y"),
		m=dt_obj.strftime("%m"),
		d=dt_obj.strftime("%d"),
		h=dt_obj.strftime("%H"),
		mi=dt_obj.strftime("%M"),
		s=dt_obj.strftime("%S"),
		x=x,
		tile_y=y,
	)


def _download_himawari_tile_grid(image_template: str, dt_obj: dt.datetime, count: int, allow_insecure: bool = False) -> Image.Image:
	size = HIMAWARI_TILE_SIZE * count
	result = Image.new("RGB", (size, size))
	try:
		for tile_y in range(count):
			for x in range(count):
				url = _himawari_tile_url(image_template, dt_obj, count, x, tile_y)
				tile = _download_image(url, allow_insecure=allow_insecure).convert("RGB")
				try:
					result.paste(tile, (x * HIMAWARI_TILE_SIZE, tile_y * HIMAWARI_TILE_SIZE))
				finally:
					tile.close()
	except Exception:
		result.close()
		raise
	log.info(f"himawari tile grid stitched: count={count} size={result.size}")
	return result


def fetch_himawari_latest(tile_count: Optional[int] = None) -> Tuple[Image.Image, str]:
	allow_insecure_env = os.getenv("ALLOW_INSECURE_HIMAWARI", "0") == "1"
	tile_count = _himawari_tile_count(tile_count)
	last_error = None
	for name, api_url, image_template in HIMAWARI_SOURCES:
		log.info(f"himawari query: source={name} url={api_url} tile_count={tile_count} allow_insecure_env={allow_insecure_env}")
		try:
			resp = requests.get(api_url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, verify=certifi.where())
			log.info(f"himawari response: source={name} status={resp.status_code}")
			resp.raise_for_status()
			data = resp.json()
			date_str = data.get("date")
			if not date_str:
				raise SourceError("Himawari latest.json missing 'date'")
			log.info(f"himawari latest: source={name} date={date_str}")
			dt_obj = dt.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
			img = _download_himawari_tile_grid(image_template, dt_obj, tile_count)
			url = _himawari_tile_url(image_template, dt_obj, tile_count, 0, 0)
			return img, f"{url}#stitched-{tile_count}d"
		except SSLError as e:
			log.warning(f"himawari SSL error (secure): source={name} error={e}")
			last_error = e
			if allow_insecure_env:
				try:
					log.warning(f"himawari retrying with insecure SSL (verify=False): source={name}")
					resp = requests.get(api_url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, verify=False)
					log.info(f"himawari response (insecure): source={name} status={resp.status_code}")
					resp.raise_for_status()
					data = resp.json()
					date_str = data.get("date")
					if not date_str:
						raise SourceError("Himawari latest.json missing 'date'")
					log.info(f"himawari latest (insecure): source={name} date={date_str}")
					dt_obj = dt.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
					img = _download_himawari_tile_grid(image_template, dt_obj, tile_count, allow_insecure=True)
					url = _himawari_tile_url(image_template, dt_obj, tile_count, 0, 0)
					return img, f"{url}#stitched-{tile_count}d"
				except Exception as ie:
					log.error(f"himawari insecure fetch failed: source={name} error={ie}")
					last_error = ie
		except Exception as e:
			log.warning(f"himawari failed: source={name} url={api_url} error={e}")
			last_error = e
	if last_error:
		raise SourceError(f"Himawari failed: {last_error}")
	raise SourceError("Himawari unknown failure")


# --- JMA Himawari Real-Time Image sectors ---
JMA_HIMAWARI_BASE = "https://www.data.jma.go.jp/mscweb/data/himawari/"
JMA_HIMAWARI_PAGE = JMA_HIMAWARI_BASE + "sat_img.php?area={area}"
JMA_ASIA_SECTORS = [
	# True Color Reproduction imagery. se2 is centered on East/Southeast Asia.
	("se2", "trm"),
	("se3", "trm"),
	("se1", "trm"),
	("se4", "trm"),
	("ca1", "trm"),
]


def fetch_jma_himawari_sector_latest() -> Tuple[Image.Image, str]:
	last_error = None
	for area, element in JMA_ASIA_SECTORS:
		page_url = JMA_HIMAWARI_PAGE.format(area=area)
		try:
			log.info(f"jma himawari sector query: area={area} element={element} url={page_url}")
			resp = requests.get(page_url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, verify=certifi.where())
			log.info(f"jma himawari sector response: status={resp.status_code}")
			resp.raise_for_status()
			match = re.search(r"<option\s+value=([0-9]{4})>", resp.text)
			if not match:
				raise SourceError(f"JMA sector page missing latest time option: area={area}")
			time_code = match.group(1)
			url = f"{JMA_HIMAWARI_BASE}img/{area}/{area}_{element}_{time_code}.jpg"
			img = _download_image(url)
			log.info(f"jma himawari sector success: area={area} time={time_code} url={url} size={img.size}")
			return img, url
		except Exception as e:
			log.warning(f"jma himawari sector failed: area={area} error={e}")
			last_error = e
	if last_error:
		raise SourceError(f"JMA Himawari sectors failed: {last_error}")
	raise SourceError("JMA Himawari sectors unknown failure")


# --- GOES-16 GeoColor full-disk (NESDIS CDN) ---
GOES16_BASE = "https://cdn.star.nesdis.noaa.gov/GOES16/ABI/FD/GEOCOLOR/latest.jpg"


def fetch_goes16_geocolor() -> Tuple[Image.Image, str]:
	# Avoid CDN cache by appending timestamp query
	ts = int(dt.datetime.utcnow().timestamp())
	url = f"{GOES16_BASE}?t={ts}"
	try:
		img = _download_image(url, extra_headers={"Pragma": "no-cache"})
		log.info(f"goes16 success: {url} size={img.size}")
		return img, GOES16_BASE
	except Exception as e:
		raise SourceError(str(e))


# --- NASA EPIC Natural color latest ---
EPIC_API = "https://api.nasa.gov/EPIC/api/natural/images"
EPIC_ARCHIVE = "https://epic.gsfc.nasa.gov/archive/natural/{y}/{m}/{d}/png/{name}.png"


def fetch_epic_latest() -> Tuple[Image.Image, str]:
	params = {"api_key": NASA_API_KEY}
	log.info(f"epic query: {EPIC_API} params={params}")
	resp = requests.get(EPIC_API, params=params, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, verify=certifi.where())
	log.info(f"epic response: status={resp.status_code}")
	resp.raise_for_status()
	data = resp.json()
	if not data:
		log.error("epic empty list")
		raise SourceError("EPIC empty response")
	latest = data[0]
	date_str = latest.get("date")
	image_name = latest.get("image")
	log.info(f"epic latest: date={date_str} image={image_name}")
	date = dt.datetime.fromisoformat(date_str)
	url = EPIC_ARCHIVE.format(y=date.strftime("%Y"), m=date.strftime("%m"), d=date.strftime("%d"), name=image_name)
	img = _download_image(url)
	return img, url


# --- NASA APOD image-only ---
APOD_API = "https://api.nasa.gov/planetary/apod"


def fetch_apod_image() -> Tuple[Image.Image, str]:
	params = {"api_key": NASA_API_KEY, "thumbs": "true"}
	log.info(f"apod query: {APOD_API} params={params}")
	resp = requests.get(APOD_API, params=params, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, verify=certifi.where())
	log.info(f"apod response: status={resp.status_code}")
	resp.raise_for_status()
	data = resp.json()
	media_type = data.get("media_type")
	url = None
	if media_type == "image":
		url = data.get("hdurl") or data.get("url")
	elif media_type == "video":
		url = data.get("thumbnail_url") or data.get("url")
	log.info(f"apod media_type={media_type} url={url}")
	if not url:
		raise SourceError("APOD no image url")
	img = _download_image(url)
	return img, url


# --- NASA SDO Sun latest (AIA 0171 as example) ---
SDO_CANDIDATES = [
	"https://sdo.gsfc.nasa.gov/assets/img/latest/latest_4096_0171.jpg",
	"https://sdo.gsfc.nasa.gov/assets/img/latest/latest_4096_HMIIC.jpg",
]


def fetch_sdo_latest() -> Tuple[Image.Image, str]:
	allow_insecure_env = os.getenv("ALLOW_INSECURE_SDO", "0") == "1"
	last_error = None
	for url in SDO_CANDIDATES:
		try:
			img = _download_image(url)
			log.info(f"sdo success: {url} size={img.size}")
			return img, url
		except SSLError as e:
			log.warning(f"sdo SSL error (secure): {e}")
			last_error = e
			if allow_insecure_env:
				try:
					log.warning("sdo retrying with insecure SSL (verify=False)")
					img = _download_image(url, allow_insecure=True)
					return img, url
				except Exception as ie:
					log.error(f"sdo insecure fetch failed: {ie}")
					last_error = ie
		except Exception as e:
			log.warning(f"sdo failed: {url} error={e}")
			last_error = e
	if last_error:
		raise SourceError(f"SDO failed: {last_error}")
	raise SourceError("SDO unknown failure")


# --- NASA Mars Rover Images (Alternative space view) ---
MARS_ROVER_CANDIDATES = [
	"https://api.nasa.gov/mars-photos/api/v1/rovers/perseverance/latest_photos?api_key={key}",
	"https://api.nasa.gov/mars-photos/api/v1/rovers/curiosity/latest_photos?api_key={key}",
]


def fetch_mars_rover_latest() -> Tuple[Image.Image, str]:
	# Get latest Mars rover photo as alternative space content
	for url_template in MARS_ROVER_CANDIDATES:
		try:
			url = url_template.format(key=NASA_API_KEY)
			log.info(f"mars query: {url}")
			resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, verify=certifi.where())
			log.info(f"mars response: status={resp.status_code}")
			resp.raise_for_status()
			data = resp.json()
			photos = data.get("latest_photos", [])
			if not photos:
				continue
			# Get the first available photo
			photo_url = photos[0]["img_src"]
			log.info(f"mars photo selected: {photo_url}")
			img = _download_image(photo_url)
			return img, photo_url
		except Exception as e:
			log.warning(f"mars failed: {url_template} error={e}")
			continue
	raise SourceError("Mars rover images unavailable")


def fetch_earth_best_effort() -> Tuple[Image.Image, str]:
	try:
		return fetch_goes16_geocolor()
	except Exception as e:
		log.warning(f"earth fallback to EPIC due to: {e}")
		return fetch_epic_latest()


# --- NASA Worldview MODIS/VIIRS (Asia-Pacific alternative) ---
WORLDVIEW_ASIA_CANDIDATES = [
	# MODIS Aqua True Color (Asia-Pacific region)
	"https://gibs.earthdata.nasa.gov/wmts/1.0.0/MODIS_Aqua_CorrectedReflectance_TrueColor/default/{date}/GoogleMapsCompatible_Level9/5/12/21.jpg",
	"https://gibs.earthdata.nasa.gov/wmts/1.0.0/MODIS_Terra_CorrectedReflectance_TrueColor/default/{date}/GoogleMapsCompatible_Level9/5/12/21.jpg",
	# VIIRS SNPP Day Night Band (for night/day coverage)
	"https://gibs.earthdata.nasa.gov/wmts/1.0.0/VIIRS_SNPP_CorrectedReflectance_TrueColor/default/{date}/GoogleMapsCompatible_Level9/5/12/21.jpg",
]

def fetch_worldview_asia_latest() -> Tuple[Image.Image, str]:
	# Get current date in the format needed for NASA GIBS
	from datetime import datetime, timedelta
	
	# Try current date and previous few days in case of delays
	for days_back in range(0, 5):
		date = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
		
		for url_template in WORLDVIEW_ASIA_CANDIDATES:
			url = url_template.format(date=date)
			try:
				log.info(f"worldview asia query: {url}")
				img = _download_image(url)
				log.info(f"worldview asia success: {url} size={img.size}")
				return img, url
			except Exception as e:
				log.warning(f"worldview asia failed: {url} error={e}")
				continue
	
	raise SourceError("NASA Worldview Asia-Pacific images unavailable")


# --- MODIS Global as backup for Asia-Pacific ---
MODIS_GLOBAL_CANDIDATES = [
	# NASA GIBS MODIS global composite (covers Asia-Pacific)
	"https://map1.vis.earthdata.nasa.gov/wmts-geo/1.0.0/MODIS_Aqua_CorrectedReflectance_TrueColor/default/{date}/EPSG4326_1km/0/0/0.jpg",
	"https://map1.vis.earthdata.nasa.gov/wmts-geo/1.0.0/MODIS_Terra_CorrectedReflectance_TrueColor/default/{date}/EPSG4326_1km/0/0/0.jpg",
]

def fetch_modis_global_latest() -> Tuple[Image.Image, str]:
	from datetime import datetime, timedelta
	
	for days_back in range(0, 3):
		date = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
		
		for url_template in MODIS_GLOBAL_CANDIDATES:
			url = url_template.format(date=date)
			try:
				log.info(f"modis global query: {url}")
				img = _download_image(url)
				log.info(f"modis global success: {url} size={img.size}")
				return img, url
			except Exception as e:
				log.warning(f"modis global failed: {url} error={e}")
				continue
	
	raise SourceError("MODIS global images unavailable")


def fetch_asia_pacific_best_effort(tile_count: Optional[int] = None) -> Tuple[Image.Image, str]:
	try:
		log.info("asia-pacific using Himawari full-disk")
		return fetch_himawari_latest(tile_count=tile_count)
	except Exception as e:
		log.warning(f"asia-pacific fallback to JMA Himawari sector due to: {e}")
	try:
		return fetch_jma_himawari_sector_latest()
	except Exception as e:
		log.warning(f"asia-pacific fallback to EPIC due to: {e}")
	try:
		return fetch_epic_latest()
	except Exception as e:
		log.warning(f"asia-pacific fallback to GOES due to: {e}")
		return fetch_goes16_geocolor()


def fetch_asia_pacific_2k_best_effort() -> Tuple[Image.Image, str]:
	return fetch_asia_pacific_best_effort(tile_count=4)


def fetch_asia_pacific_4k_best_effort() -> Tuple[Image.Image, str]:
	return fetch_asia_pacific_best_effort(tile_count=8)


def fetch_sky_best_effort() -> Tuple[Image.Image, str]:
	try:
		return fetch_apod_image()
	except Exception as e:
		log.warning(f"sky fallback to Mars due to: {e}")
		return fetch_mars_rover_latest()


def fetch_mars_best_effort() -> Tuple[Image.Image, str]:
	try:
		return fetch_mars_rover_latest()
	except Exception as e:
		log.warning(f"mars fallback to SDO due to: {e}")
		return fetch_sdo_latest()
