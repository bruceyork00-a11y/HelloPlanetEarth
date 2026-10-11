"""Public imagery providers. Fallbacks preserve the selected satellite."""
import concurrent.futures
import datetime as dt
import io
import json
import logging
import os
import re
import threading
import time
from email.utils import parsedate_to_datetime
from contextlib import contextmanager
from urllib.parse import urljoin, urlencode

import requests
from requests.adapters import HTTPAdapter
from PIL import Image, ImageChops

Image.MAX_IMAGE_PIXELS = 120_000_000
USER_AGENT = "HelloPlanet/1.3.0 (+https://gitee.com/yinxiaolong007/hello-planet-earth)"
TIMEOUT = (8, 20)
MAX_BYTES = 48 * 1024 * 1024
MAX_SATELLITE_AGE = dt.timedelta(hours=3)
log = logging.getLogger(__name__)
_local = threading.local()


class SourceError(Exception):
    pass


class DownloadCancelled(SourceError):
    pass


@contextmanager
def download_scope(stop_event):
    previous = getattr(_local, "stop_event", None)
    _local.stop_event = stop_event
    try:
        yield
    finally:
        _local.stop_event = previous


def _check_cancelled():
    event = getattr(_local, "stop_event", None)
    if event is not None and event.is_set():
        raise DownloadCancelled("Download cancelled on application shutdown")


def _get_session():
    # Sessions have mutable cookies; give each worker its own reusable pool.
    if not hasattr(_local, "session"):
        session = requests.Session()
        session.mount("https://", HTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=0))
        session.headers.update({"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
        _local.session = session
    return _local.session


def _request(url, max_bytes=MAX_BYTES):
    _check_cancelled()
    start = time.monotonic()
    with _get_session().get(url, timeout=TIMEOUT, stream=True) as response:
        response.raise_for_status()
        if not response.url.startswith("https://"):
            raise SourceError("Provider redirected to an insecure URL")
        if int(response.headers.get("Content-Length", "0")) > max_bytes:
            raise SourceError("Response exceeds download size limit")
        chunks, size = [], 0
        for chunk in response.iter_content(64 * 1024):
            _check_cancelled()
            size += len(chunk)
            if size > max_bytes or time.monotonic() - start > 60:
                raise SourceError("Download exceeded size or duration limit")
            chunks.append(chunk)
        return b"".join(chunks), dict(response.headers)


def _json(url):
    for attempt in range(2):
        try:
            body, _ = _request(url, max_bytes=8 * 1024 * 1024)
            break
        except requests.HTTPError as error:
            if attempt or error.response is None or error.response.status_code < 500:
                raise
        except requests.RequestException:
            if attempt:
                raise
        time.sleep(0.25)
    try:
        return json.loads(body)
    except (ValueError, UnicodeError) as error:
        raise SourceError("Provider did not return valid JSON") from error


def _fresh(timestamp, max_age=MAX_SATELLITE_AGE):
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=dt.timezone.utc)
    age = dt.datetime.now(dt.timezone.utc) - timestamp
    if age > max_age or age < -dt.timedelta(minutes=30):
        raise SourceError(f"Stale or invalid observation timestamp: {timestamp.isoformat()}")


def _download_image(url, max_retries=2, max_age=None, min_size=1):
    last_error = None
    for attempt in range(max_retries):
        try:
            body, headers = _request(url)
            if max_age and headers.get("Last-Modified"):
                _fresh(parsedate_to_datetime(headers["Last-Modified"]), max_age)
            with Image.open(io.BytesIO(body)) as original:
                original.load()
                if min(original.size) < min_size:
                    raise SourceError(f"Image resolution too small: {original.size}")
                image = original.convert("RGB")
            image.info.update(source_url=url, last_modified=headers.get("Last-Modified"))
            return image
        except requests.HTTPError as error:
            last_error = error
            if error.response is not None and error.response.status_code < 500:
                break
        except DownloadCancelled:
            raise
        except (SourceError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
            raise SourceError(str(error)) from error
        except (requests.RequestException, OSError, ValueError) as error:
            last_error = error
        if attempt + 1 < max_retries:
            time.sleep(0.25)
    raise SourceError(f"Image download failed: {url}: {last_error}")


def _best_effort(providers):
    errors = []
    for name, fetch in providers:
        try:
            image, url = fetch()
            image.info["provider"] = name
            log.info("source success: %s size=%s url=%s", name, image.size, url)
            return image, url
        except DownloadCancelled:
            raise
        except Exception as error:
            log.warning("source failed: %s: %s", name, error)
            errors.append(f"{name}: {error}")
    raise SourceError("No matching provider available: " + "; ".join(errors))


HIMAWARI_TILE_SIZE = 550
HIMAWARI_DEFAULT_TILE_COUNT = 4
HIMAWARI_ALLOWED_TILE_COUNTS = {1, 2, 4, 8, 16}
HIMAWARI_SOURCES = [
    ("Kyoto", "https://jh190005-4.kudpc.kyoto-u.ac.jp/himawari/img/D531106/latest.json",
     "https://jh190005-4.kudpc.kyoto-u.ac.jp/himawari/img/D531106/{count}d/550/{y}/{m}/{d}/{h}{mi}{s}_{x}_{tile_y}.png"),
    ("himawari.asia", "https://himawari.asia/img/D531106/latest.json",
     "https://himawari.asia/img/D531106/{count}d/550/{y}/{m}/{d}/{h}{mi}{s}_{x}_{tile_y}.png"),
    ("NICT download", "https://himawari8-dl.nict.go.jp/himawari8/img/D531106/latest.json",
     "https://himawari8-dl.nict.go.jp/himawari8/img/D531106/{count}d/550/{y}/{m}/{d}/{h}{mi}{s}_{x}_{tile_y}.png"),
    ("NICT", "https://himawari8.nict.go.jp/img/D531106/latest.json",
     "https://himawari8.nict.go.jp/img/D531106/{count}d/550/{y}/{m}/{d}/{h}{mi}{s}_{x}_{tile_y}.png"),
]


def _himawari_tile_count(preferred_count=None):
    try:
        count = int(preferred_count if preferred_count is not None else
                    os.getenv("HIMAWARI_TILE_COUNT", HIMAWARI_DEFAULT_TILE_COUNT))
    except (TypeError, ValueError):
        count = HIMAWARI_DEFAULT_TILE_COUNT
    return count if count in HIMAWARI_ALLOWED_TILE_COUNTS else HIMAWARI_DEFAULT_TILE_COUNT


def _himawari_tile_url(template, timestamp, count, x, y):
    return template.format(count=count, y=timestamp.strftime("%Y"), m=timestamp.strftime("%m"),
                           d=timestamp.strftime("%d"), h=timestamp.strftime("%H"),
                           mi=timestamp.strftime("%M"), s=timestamp.strftime("%S"), x=x, tile_y=y)


def _tile_grid(url_for_tile, count, tile_size):
    result = Image.new("RGB", (count * tile_size, count * tile_size))
    futures = {}
    stop_event = getattr(_local, "stop_event", None)
    def fetch_tile(url):
        with download_scope(stop_event):
            return _download_image(url)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, count * count)) as pool:
            futures = {pool.submit(fetch_tile, url_for_tile(x, y)): (x, y)
                       for y in range(count) for x in range(count)}
            for future in concurrent.futures.as_completed(futures):
                x, y = futures[future]
                try:
                    with future.result() as tile:
                        if tile.size != (tile_size, tile_size):
                            raise SourceError(f"Unexpected tile size: {tile.size}")
                        result.paste(tile, (x * tile_size, y * tile_size))
                except Exception as error:
                    for pending in futures:
                        pending.cancel()
                    if isinstance(error, DownloadCancelled):
                        raise
                    raise SourceError(f"Incomplete tile grid at ({x},{y}): {error}") from error
        return result
    except BaseException:
        result.close()
        for future in futures:
            if future.done() and not future.cancelled() and future.exception() is None:
                future.result().close()
        raise


def _fetch_himawari_source(source, count):
    _, api, template = source
    stamp = dt.datetime.strptime(_json(api)["date"], "%Y-%m-%d %H:%M:%S")
    _fresh(stamp)
    image = _tile_grid(lambda x, y: _himawari_tile_url(template, stamp, count, x, y),
                       count, HIMAWARI_TILE_SIZE)
    image.info["observed_at_utc"] = stamp.isoformat() + "Z"
    return image, _himawari_tile_url(template, stamp, count, 0, 0) + f"#stitched-{count}d"


def fetch_himawari_latest(tile_count=None):
    count = _himawari_tile_count(tile_count)
    return _best_effort([(source[0], lambda source=source: _fetch_himawari_source(source, count))
                         for source in HIMAWARI_SOURCES])


SLIDER_BASE = "https://slider.cira.colostate.edu/data/"
SLIDER_TILE_SIZES = {"himawari": 688, "gk2a": 688, "goes-19": 678, "goes-18": 678}


def fetch_slider_latest(satellite="himawari", count=4):
    if count not in {1, 2, 4, 8, 16}:
        raise SourceError("Unsupported CIRA tile count")
    times = _json(f"{SLIDER_BASE}json/{satellite}/full_disk/geocolor/latest_times.json").get("timestamps_int", [])
    if not times:
        raise SourceError("CIRA returned no observation timestamps")
    errors = []
    for raw_stamp in sorted(times, reverse=True)[:2]:
        stamp = dt.datetime.strptime(str(raw_stamp), "%Y%m%d%H%M%S")
        _fresh(stamp)
        base = (f"{SLIDER_BASE}imagery/{stamp:%Y/%m/%d}/{satellite}---full_disk/geocolor/"
                f"{raw_stamp}/{count.bit_length() - 1:02d}/")
        try:
            image = _tile_grid(lambda x, y: f"{base}{y:03d}_{x:03d}.png", count,
                               SLIDER_TILE_SIZES[satellite])
            image.info["observed_at_utc"] = stamp.isoformat() + "Z"
            return image, base + f"#stitched-{count}d"
        except DownloadCancelled:
            raise
        except SourceError as error:
            errors.append(str(error))
    raise SourceError("CIRA incomplete recent frames: " + "; ".join(errors))


def fetch_asia_pacific_best_effort(tile_count=None):
    count = _himawari_tile_count(tile_count)
    return _best_effort([
        ("Himawari mirrors", lambda: fetch_himawari_latest(count)),
        ("CIRA Himawari-9", lambda: fetch_slider_latest("himawari", count)),
    ])


def fetch_asia_pacific_2k_best_effort():
    return fetch_asia_pacific_best_effort(4)


def fetch_asia_pacific_4k_best_effort():
    return fetch_asia_pacific_best_effort(8)


def fetch_gk2a_latest():
    return fetch_slider_latest("gk2a", 4)


def fetch_goes_geocolor(satellite="GOES19"):
    url = f"https://cdn.star.nesdis.noaa.gov/{satellite}/ABI/FD/GEOCOLOR/1808x1808.jpg"
    return _download_image(url, max_age=MAX_SATELLITE_AGE, min_size=1600), url


def fetch_earth_best_effort():
    return _best_effort([
        ("NOAA GOES-19", lambda: fetch_goes_geocolor("GOES19")),
        ("CIRA GOES-19", lambda: fetch_slider_latest("goes-19", 4)),
    ])


def fetch_goes_west_best_effort():
    return _best_effort([
        ("NOAA GOES-18", lambda: fetch_goes_geocolor("GOES18")),
        ("CIRA GOES-18", lambda: fetch_slider_latest("goes-18", 4)),
    ])


def fetch_epic_latest():
    data = _json("https://epic.gsfc.nasa.gov/api/natural")
    if not data:
        raise SourceError("EPIC returned no images")
    latest = max(data, key=lambda item: item["date"])
    stamp = dt.datetime.fromisoformat(latest["date"])
    _fresh(stamp, dt.timedelta(days=14))
    url = f"https://epic.gsfc.nasa.gov/archive/natural/{stamp:%Y/%m/%d}/jpg/{latest['image']}.jpg"
    image = _download_image(url, min_size=1000)
    image.info["observed_at_utc"] = stamp.isoformat() + "Z"
    return image, url


APOD_API = "https://science.nasa.gov/wp-json/wp/v2/apod-basic"


def fetch_apod_image():
    today = dt.datetime.now(dt.timezone.utc).date()
    params = {"start_date": (today - dt.timedelta(days=7)).isoformat(), "end_date": today.isoformat()}
    data = _json(APOD_API + "?" + urlencode(params))
    if isinstance(data, dict):
        data = [data]
    for item in sorted(data, key=lambda item: item.get("date", ""), reverse=True):
        # New API's url points to an HTML article; download hdurl.
        if item.get("media_type") == "image" and item.get("hdurl"):
            url = item["hdurl"]
            image = _download_image(url, min_size=400)
            image.info["published_date"] = item["date"]
            return image, url
    raise SourceError("No APOD image available in the last seven days")


def fetch_sky_best_effort():
    return fetch_apod_image()


def _fetch_suvi(role):
    data = _json(f"https://services.swpc.noaa.gov/products/animations/suvi-{role}-171.json")
    if not data:
        raise SourceError("SUVI returned no images")
    path = max(item["url"] for item in data)
    match = re.search(r"_s(\d{8}T\d{6})Z", path)
    if not match:
        raise SourceError("SUVI observation timestamp missing")
    stamp = dt.datetime.strptime(match.group(1), "%Y%m%dT%H%M%S")
    _fresh(stamp)
    url = urljoin("https://services.swpc.noaa.gov", path)
    image = _download_image(url, min_size=1000)
    image.info["observed_at_utc"] = stamp.isoformat() + "Z"
    return image, url


def fetch_sdo_latest():
    """Legacy mode name, now served by the live GOES SUVI solar telescope."""
    return _best_effort([(f"NOAA SUVI {role}", lambda role=role: _fetch_suvi(role))
                         for role in ("primary", "secondary")])


MARS_GALLERY_API = "https://science.nasa.gov/wp-json/wp/v2/image-article"


def fetch_mars_best_effort():
    # This is a curated gallery, not a real-time rover downlink.
    params = {"search": "Curiosity", "per_page": 10, "_embed": "true"}
    data = _json(MARS_GALLERY_API + "?" + urlencode(params))
    for post in sorted(data, key=lambda item: item.get("date", ""), reverse=True):
        for media in post.get("_embedded", {}).get("wp:featuredmedia", []):
            alt = media.get("alt_text", "").lower()
            if "mars" in alt and "rover" in alt and media.get("source_url"):
                url = media["source_url"]
                image = _download_image(url, min_size=400)
                image.info["published_date"] = post["date"]
                return image, url
    raise SourceError("NASA Mars rover gallery returned no matching images")


GIBS_WMS = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
GIBS_MAP_SIZE = 2200
GIBS_LAYERS = ["MODIS_Terra_CorrectedReflectance_TrueColor",
               "MODIS_Aqua_CorrectedReflectance_TrueColor",
               "VIIRS_NOAA20_CorrectedReflectance_TrueColor"]


def _missing_map_mask(image):
    red, green, blue = image.split()
    try:
        with ImageChops.lighter(red, green) as first:
            with ImageChops.lighter(first, blue) as maximum:
                return maximum.point(lambda value: 255 if value <= 4 else 0)
    finally:
        red.close()
        green.close()
        blue.close()


def fetch_worldview_asia_latest():
    """Fill orbital gaps with other daily sensors, then the preceding day."""
    today = dt.datetime.now(dt.timezone.utc).date()
    result = Image.new("RGB", (GIBS_MAP_SIZE, GIBS_MAP_SIZE))
    used, missing_fraction = [], 1.0
    try:
        for days_back in (1, 2):
            for layer in GIBS_LAYERS:
                params = dict(SERVICE="WMS", VERSION="1.1.1", REQUEST="GetMap", LAYERS=layer,
                              TIME=(today - dt.timedelta(days=days_back)).isoformat(),
                              SRS="EPSG:4326", BBOX="80,-50,180,60",
                              WIDTH=GIBS_MAP_SIZE, HEIGHT=GIBS_MAP_SIZE, FORMAT="image/jpeg")
                url = GIBS_WMS + "?" + urlencode(params)
                try:
                    with _download_image(url, min_size=GIBS_MAP_SIZE) as image:
                        if image.size != result.size:
                            raise SourceError("GIBS returned incorrect map dimensions")
                        with _missing_map_mask(result) as mask:
                            result.paste(image, (0, 0), mask)
                    used.append({"layer": layer, "date": params["TIME"], "url": url})
                    with _missing_map_mask(result) as mask:
                        missing_fraction = mask.histogram()[255] / (GIBS_MAP_SIZE ** 2)
                    if missing_fraction <= 0.002:
                        break
                except DownloadCancelled:
                    raise
                except Exception as error:
                    log.warning("GIBS product failed: %s %s: %s", layer, params["TIME"], error)
            if missing_fraction <= 0.002:
                break
        if not used or missing_fraction > 0.02:
            raise SourceError(f"GIBS coverage incomplete: {missing_fraction:.1%} missing")
        result.info.update(observation_dates=sorted({item["date"] for item in used}),
                           layers=[item["layer"] for item in used],
                           coverage_percent=round((1 - missing_fraction) * 100, 2))
        return result, used[0]["url"] + "#daily-composite"
    except BaseException:
        result.close()
        raise
