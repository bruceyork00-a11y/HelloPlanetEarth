import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
import subprocess
import sys
import uuid
from PIL import Image
from src import config, sources, image_cache, main, wallpaper
from src.tray import TrayController


class SecurityTests(unittest.TestCase):
    def test_slow_drip_checks_total_budget_per_available_chunk(self):
        response = requests.Response()
        response.status_code = 200
        response.url = "https://science.nasa.gov/image"
        response.raw = Mock()
        response.raw.read1.return_value = b"x"
        session = Mock()
        session.get.return_value = response
        with patch.object(sources, "_get_session", return_value=session), \
             patch.object(sources.time, "monotonic", side_effect=range(0, 200, 10)):
            with self.assertRaises(sources.SourceError):
                sources._request(response.url)
        self.assertLessEqual(response.raw.read1.call_count, 7)
    def test_untrusted_urls_are_rejected_before_connecting(self):
        urls = ["http://science.nasa.gov/a", "https://127.0.0.1/a", "file:///etc/passwd",
                "https://science.nasa.gov.evil.com/a", "https://user:password@science.nasa.gov/a",
                "https://science.nasa.gov:8080/a", "https://science.nasa.gov/a\n"]
        with patch.object(sources, "_get_session") as session:
            for url in urls:
                with self.subTest(url=url), self.assertRaises(sources.SourceError):
                    sources._request(url)
            session.assert_not_called()

    def test_redirect_is_validated_before_second_request(self):
        response = requests.Response()
        response.status_code = 302
        response.url = "https://science.nasa.gov/image"
        response.headers["Location"] = "https://localhost/private"
        response._content = b""
        response._content_consumed = True
        session = Mock()
        session.get.return_value = response
        with patch.object(sources, "_get_session", return_value=session):
            with self.assertRaises(sources.SourceError):
                sources._request(response.url)
        self.assertEqual(session.get.call_count, 1)

    def test_stream_limit_applies_without_content_length(self):
        response = requests.Response()
        response.status_code = 200
        response.url = "https://science.nasa.gov/image"
        response._content = b"a" * 100
        response._content_consumed = True
        session = Mock()
        session.get.return_value = response
        with patch.object(sources, "_get_session", return_value=session):
            with self.assertRaises(sources.SourceError):
                sources._request(response.url, max_bytes=16)

    def test_pixel_limit_checked_before_decode(self):
        original = Mock(width=10000, height=10000)
        original.__enter__ = Mock(return_value=original)
        original.__exit__ = Mock(return_value=False)
        with patch.object(sources, "_request", return_value=(b"png", {})), \
             patch.object(sources.Image, "open", return_value=original):
            with self.assertRaises(sources.SourceError):
                sources._download_image("https://science.nasa.gov/image")
        original.load.assert_not_called()

    def test_large_grid_rejected_before_allocation(self):
        with patch.object(sources.Image, "new") as allocate:
            with self.assertRaises(sources.SourceError):
                sources._tile_grid(lambda x, y: "tile", 100, 550)
        allocate.assert_not_called()


class BoundaryTests(unittest.TestCase):
    def test_invalid_saved_value_allows_valid_environment_default(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(config, "CONFIG_PATH", str(Path(directory)/"config.json")):
            Path(config.CONFIG_PATH).write_text('{"mode": "unknown"}', encoding="utf-8")
            with patch.dict(config.os.environ, {"MODE": "asia_4k"}):
                self.assertEqual(config.resolve(None, "mode", "MODE"), "asia_4k")
    def test_invalid_config_values_do_not_reach_runtime(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(config, "CONFIG_PATH", str(Path(directory)/"config.json")):
            for interval in (False, -1, 0, 1, 10**100, [], {}):
                # Test data, not production file edits.
                Path(config.CONFIG_PATH).write_text(json.dumps({"mode": {}, "interval": interval,
                                                               "language": 5, "style": "bad"}), encoding="utf-8")
                loaded = config.load_config()
                for key in config.DEFAULTS:
                    self.assertEqual(loaded[key], config.DEFAULTS[key])

    def test_large_and_wrong_shape_config_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(config, "CONFIG_PATH", str(Path(directory)/"config.json")):
            for text in ("[]", "x" * 17000, "{invalid", "[" * 1200):
                Path(config.CONFIG_PATH).write_text(text, encoding="utf-8")
                self.assertFalse(config.load_config()["_loaded"])

    def test_failed_settings_write_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(config, "CONFIG_DIR", directory), \
             patch.object(config, "CONFIG_PATH", str(Path(directory)/"config.json")):
            self.assertTrue(config.save_config(config.DEFAULTS))
            original = Path(config.CONFIG_PATH).read_bytes()
            with patch.object(config.os, "replace", side_effect=OSError("disk full")):
                self.assertFalse(config.save_config(dict(config.DEFAULTS, mode="asia_4k")))
            self.assertEqual(Path(config.CONFIG_PATH).read_bytes(), original)
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_failed_bmp_write_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory, Image.new("RGB", (4, 4), "red") as image:
            target = str(Path(directory)/"active.bmp")
            wallpaper._save_as_bmp(image, target)
            original = Path(target).read_bytes()
            with patch.object(Image.Image, "save", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    wallpaper._save_as_bmp(image, target)
            self.assertEqual(Path(target).read_bytes(), original)
            self.assertEqual(len(list(Path(directory).iterdir())), 1)


class PerformanceAndUXTests(unittest.TestCase):
    def test_obsolete_status_cannot_overwrite_new_mode(self):
        runner = main.Runner("earth", 1800, "fill")
        old_version = runner._mode_version
        runner.switch_mode("asia_4k")
        runner._publish("error", version=old_version)
        self.assertEqual(runner.get_status()["state"], "updating")

    def test_native_apply_does_not_block_mode_selection(self):
        runner = main.Runner("earth", 1800, "fill")
        started, release = threading.Event(), threading.Event()
        def apply(image, style):
            started.set()
            release.wait(2)
        fetch = lambda: (Image.new("RGB", (4, 4)), "goes")
        with patch.object(main, "_fetcher", return_value=fetch), \
             patch.object(main, "read_last", return_value=(None, None)), \
             patch.object(main, "write_last"), patch.object(main, "set_wallpaper_from_image", side_effect=apply):
            worker = threading.Thread(target=runner._tick_once)
            worker.start()
            self.assertTrue(started.wait(1))
            change = threading.Thread(target=lambda: runner.switch_mode("asia_4k"))
            change.start()
            change.join(0.5)
            self.assertFalse(change.is_alive())
            release.set()
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertIsNone(runner.last_update_time)

    def test_worker_sessions_closed_after_incomplete_grid(self):
        sessions = []
        def session():
            item = Mock()
            sessions.append(item)
            return item
        with patch.object(image_cache, "get", return_value=None), \
             patch.object(sources, "_get_session", side_effect=session), \
             patch.object(sources, "_download_image", side_effect=sources.SourceError("offline")):
            with self.assertRaises(sources.SourceError):
                sources._tile_grid(lambda x, y: "tile", 2, 2)
        self.assertTrue(sessions)
        for item in sessions:
            item.close.assert_called_once()
    @unittest.skipUnless(sys.platform == "win32", "Windows mutex")
    def test_native_single_instance_mutex_is_released(self):
        key = "HelloPlanetTest_" + uuid.uuid4().hex
        code = ("import sys; from unittest.mock import patch; from src.main import _ensure_single_instance; "
                "p=patch('src.main.os.getenv', return_value=sys.argv[1]); p.start(); "
                "print(_ensure_single_instance(), flush=True); "
                "sys.stdin.readline() if len(sys.argv)>2 else None")
        process = subprocess.Popen([sys.executable, "-c", code, key, "hold"], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            self.assertEqual(process.stdout.readline().strip(), "True")
            result = subprocess.check_output([sys.executable, "-c", code, key], text=True,
                                            creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
            self.assertEqual(result.strip(), "False")
        finally:
            process.communicate("exit\n", timeout=10)
        result = subprocess.check_output([sys.executable, "-c", code, key], text=True,
                                        creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
        self.assertEqual(result.strip(), "True")

    def test_frame_cache_and_force_refresh_semantics(self):
        calls = []
        def fetch(url, **kwargs):
            calls.append(url)
            return Image.new("RGB", (2, 2), "green")
        with tempfile.TemporaryDirectory() as directory, patch.object(image_cache, "CACHE_DIR", Path(directory)), \
             patch.object(sources, "_download_image", side_effect=fetch):
            for force, expected in ((False, 4), (False, 4), (True, 8)):
                with sources.download_scope(None, force=force):
                    image = sources._tile_grid(lambda x, y: f"https://science.nasa.gov/{x}/{y}", 2, 2)
                    image.close()
                self.assertEqual(len(calls), expected)

    def test_cache_corruption_and_capacity(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(image_cache, "CACHE_DIR", Path(directory)), \
             Image.new("RGB", (4, 4), "red") as image:
            for key in ("a", "b", "c", "d"):
                image_cache.put(key, image)
            self.assertLessEqual(len(list(Path(directory).glob("*.png"))), 3)
            image_cache._path("d").write_bytes(b"broken")
            self.assertIsNone(image_cache.get("d"))

    def test_mode_switch_cancels_old_download_scope(self):
        runner = main.Runner("earth", 1800, "fill")
        original = runner._download_cancel
        runner.switch_mode("asia_4k")
        self.assertTrue(original.is_set())
        self.assertFalse(runner._download_cancel.is_set())
        self.assertFalse(runner._stop.is_set())
        runner.stop()
        self.assertTrue(runner._download_cancel.is_set())

    def test_style_change_reapplies_identical_image(self):
        runner = main.Runner("earth", 1800, "fill")
        fetch = lambda: (Image.new("RGB", (4, 4), "red"), "same-url")
        with patch.object(main, "_fetcher", return_value=fetch), \
             patch.object(main, "read_last", return_value=("same-url", "hash")), \
             patch.object(main, "md5_of_image", return_value="hash"), \
             patch.object(main, "write_last"), patch.object(main, "set_wallpaper_from_image") as apply:
            runner._tick_once()
            runner._tick_once()
            self.assertEqual(apply.call_count, 1)
            self.assertEqual(runner.get_status()["state"], "unchanged")
            runner.set_style("fit")
            runner._tick_once()
            self.assertEqual(apply.call_count, 2)
            self.assertEqual(apply.call_args.kwargs["style"], "fit")

    def test_menu_busy_state_and_immediate_language_switch(self):
        state = {"state": "updating", "progress": (12, 64)}
        tray = TrayController(lambda: None, lambda mode: None, lambda value: None,
                              lambda: None, lambda: False, lambda: None, get_status=lambda: state)
        menu = tray._build_menu()
        refresh = next(item for item in menu.items if item.text == tray._text("force_refresh"))
        self.assertFalse(refresh.enabled)
        self.assertIn("12/64", tray._title())
        tray._icon = Mock()
        tray._set_language_action("en")(None, None)
        self.assertIn("Updating", tray._icon.title)
        state["state"] = "error"
        self.assertTrue(refresh.enabled)
        self.assertIn("wallpaper kept", tray._status_text())


if __name__ == "__main__":
    unittest.main()
