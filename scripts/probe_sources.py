"""Probe public image endpoints without changing the desktop wallpaper."""
import concurrent.futures
import datetime as dt
import io
import json
import sys
import time
from pathlib import Path

import requests
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import sources


def probe(item):
    name, url = item
    start = time.monotonic()
    result = {"name": name, "url": url}
    try:
        with requests.get(url, timeout=(8, 15), headers={"User-Agent": sources.USER_AGENT}) as response:
            result.update(status=response.status_code, final_url=response.url,
                          last_modified=response.headers.get("Last-Modified"), bytes=len(response.content))
            response.raise_for_status()
            if "json" in response.headers.get("Content-Type", "") or url.endswith(".json"):
                data = response.json()
                result["data"] = data if isinstance(data, dict) else data[:1]
            elif response.headers.get("Content-Type", "").startswith("image/"):
                with Image.open(io.BytesIO(response.content)) as image:
                    image.load()
                    result.update(size=image.size, format=image.format,
                                  extrema=image.convert("RGB").getextrema())
            else:
                result["text"] = response.text[:300]
    except Exception as error:
        result["error"] = str(error)
    result["seconds"] = round(time.monotonic() - start, 2)
    return result


def endpoints():
    baseline = Path(__file__).resolve().parents[1] / "docs" / "source-audit-baseline.json"
    if baseline.exists():
        data = json.loads(baseline.read_text(encoding="utf-8"))
        return [(item["name"], item["url"]) for item in data["results"]]
    raise RuntimeError("Baseline endpoint inventory not found")




if __name__ == "__main__":
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(probe, endpoints()))
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "source-probe.json")
    path.write_text(json.dumps({"tested_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                                "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    for result in results:
        print(json.dumps(result, ensure_ascii=True))
