"""Reproducible local CPU/memory benchmarks; no network or wallpaper changes."""
import argparse
import ctypes
import json
import sys
import time
from pathlib import Path
from PIL import Image
import hashlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.cache import md5_of_image


class Counters(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
        (name, ctypes.c_size_t) for name in ("peak", "working", "peak_paged", "paged",
                                           "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]


def memory():
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    fn = ctypes.windll.psapi.GetProcessMemoryInfo
    fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
    fn.restype = ctypes.c_int
    if not fn(ctypes.c_void_p(-1), ctypes.byref(counters), counters.cb):
        raise OSError("GetProcessMemoryInfo failed")
    return counters.peak / 1024**2


def old_hash(image):
    with image.convert("RGB") as preview:
        preview.thumbnail((1024, 1024))
        return hashlib.md5(preview.tobytes()).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("case", choices=["old", "new"])
    args = parser.parse_args()
    image = Image.effect_noise((4400, 4400), 60).convert("RGB")
    times = []
    for _ in range(5):
        start = time.perf_counter()
        (old_hash if args.case == "old" else md5_of_image)(image)
        times.append(time.perf_counter() - start)
    print(json.dumps({"case": args.case, "image": image.size,
                      "median_ms": round(sorted(times)[2] * 1000, 2),
                      "peak_working_set_mb": round(memory(), 2)}))
    image.close()
