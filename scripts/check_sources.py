"""Live end-to-end image checks; never changes the user's wallpaper."""
import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

from PIL import ImageStat

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.main import _fetcher
from src import sources


def check_viirs_product():
    date = (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)).isoformat()
    params = dict(SERVICE="WMS", VERSION="1.1.1", REQUEST="GetMap",
                  LAYERS="VIIRS_NOAA20_CorrectedReflectance_TrueColor", TIME=date,
                  SRS="EPSG:4326", BBOX="80,-50,180,60", WIDTH=2200, HEIGHT=2200,
                  FORMAT="image/jpeg")
    url = sources.GIBS_WMS + "?" + urlencode(params)
    image = sources._download_image(url, min_size=2000)
    image.info["observation_date"] = date
    return image, url


def cases(all_providers):
    modes = ["earth", "goes_west", "asia_2k", "asia_4k", "asia_gk2a",
             "asia_modis", "earth_epic", "sky", "sun_sdo", "mars"]
    items = [(mode, _fetcher(mode)) for mode in modes]
    if all_providers:
        items += [("mirror-" + source[0], lambda source=source: sources._fetch_himawari_source(source, 4))
                  for source in sources.HIMAWARI_SOURCES]
        items += [("cira-" + satellite, lambda satellite=satellite: sources.fetch_slider_latest(satellite, 4))
                  for satellite in sources.SLIDER_TILE_SIZES]
        items += [("cira-himawari-4k", lambda: sources.fetch_slider_latest("himawari", 8)),
                  ("suvi-secondary", lambda: sources._fetch_suvi("secondary")),
                  ("gibs-viirs-noaa20", check_viirs_product)]
    return items


def check(case, directory):
    name, fetch = case
    start = time.monotonic()
    result = {"case": name}
    try:
        image, url = fetch()
        with image:
            image.load()
            if min(image.size) < 400:
                raise AssertionError("Resolution too small")
            metadata = {key: value for key, value in image.info.items()
                        if key in {"provider", "source_url", "last_modified", "observed_at_utc",
                                   "published_date", "observation_date", "observation_dates",
                                   "layers", "coverage_percent"}}
            result.update(size=image.size, url=url, metadata=metadata,
                          image_sha256=hashlib.sha256(image.tobytes()).hexdigest())
            with image.copy() as preview:
                preview.thumbnail((550, 550))
                if max(ImageStat.Stat(preview).stddev) < 3:
                    raise AssertionError("Blank image")
                preview.save(directory / (name.replace(" ", "-") + ".jpg"))
        result["status"] = "pass"
    except Exception as error:
        result.update(status="fail", error=str(error))
    result["seconds"] = round(time.monotonic() - start, 2)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--all-providers", action="store_true")
    parser.add_argument("--output", default="build/source-audit")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--case", action="append", help="Run only matching named cases")
    args = parser.parse_args()
    directory = Path(args.output)
    directory.mkdir(parents=True, exist_ok=True)
    results = []
    selected = [item for item in cases(args.all_providers) if not args.case or item[0] in args.case]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(check, item, directory) for item in selected]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            print(json.dumps(result, ensure_ascii=True), flush=True)
            (directory / "results.json").write_text(json.dumps({
                "tested_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "results": sorted(results, key=lambda item: item["case"]),
            }, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.exit(1 if any(item["status"] == "fail" for item in results) else 0)
