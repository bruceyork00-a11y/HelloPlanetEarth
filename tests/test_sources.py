import datetime as dt
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from src import config, main, sources
from src.tray import TrayController
from src.wallpaper import _save_as_bmp


class SourceTests(unittest.TestCase):
    def test_shutdown_prevents_network_and_additional_fallbacks(self):
        event = threading.Event()
        event.set()
        with sources.download_scope(event), patch.object(sources, "_get_session") as session:
            with self.assertRaises(sources.DownloadCancelled):
                sources._download_image("https://example.com/image")
            session.assert_not_called()
        fallback = unittest.mock.Mock()
        def cancelled():
            raise sources.DownloadCancelled("shutdown")
        with self.assertRaises(sources.DownloadCancelled):
            sources._best_effort([("first", cancelled), ("second", fallback)])
        fallback.assert_not_called()

    def test_stale_and_future_observations_rejected(self):
        now = dt.datetime.now(dt.timezone.utc)
        for stamp in (now - dt.timedelta(days=1), now + dt.timedelta(hours=1)):
            with self.assertRaises(sources.SourceError):
                sources._fresh(stamp)
        sources._fresh(now - dt.timedelta(minutes=20))

    def test_missing_tile_rejects_entire_frame_and_closes_images(self):
        tiles = []
        def download(url):
            if url == "1,1":
                raise sources.SourceError("missing tile")
            image = Image.new("RGB", (2, 2), "blue")
            tiles.append(image)
            return image
        with patch.object(sources, "_download_image", side_effect=download):
            with self.assertRaisesRegex(sources.SourceError, "Incomplete tile grid"):
                sources._tile_grid(lambda x, y: f"{x},{y}", 2, 2)
        for tile in tiles:
            with self.assertRaises(ValueError):
                tile.getpixel((0, 0))

    def test_tile_placement_and_size(self):
        def download(url):
            x, y = map(int, url.split(","))
            return Image.new("RGB", (2, 2), (x * 100, y * 100, 0))
        with patch.object(sources, "_download_image", side_effect=download):
            with sources._tile_grid(lambda x, y: f"{x},{y}", 2, 2) as image:
                self.assertEqual(image.size, (4, 4))
                self.assertEqual(image.getpixel((3, 1)), (100, 0, 0))
                self.assertEqual(image.getpixel((1, 3)), (0, 100, 0))

    def test_daily_map_fills_only_missing_sensor_pixels(self):
        first = Image.new("RGB", (2, 2), "red")
        first.putpixel((0, 0), (0, 0, 0))
        second = Image.new("RGB", (2, 2), "blue")
        with patch.object(sources, "GIBS_MAP_SIZE", 2), \
             patch.object(sources, "_download_image", side_effect=[first, second]):
            image, _ = sources.fetch_worldview_asia_latest()
            with image:
                self.assertEqual(image.getpixel((0, 0)), (0, 0, 255))
                self.assertEqual(image.getpixel((1, 1)), (255, 0, 0))
                self.assertEqual(image.info["coverage_percent"], 100)

    def test_asia_failure_never_calls_goes(self):
        with patch.object(sources, "fetch_himawari_latest", side_effect=sources.SourceError("offline")), \
             patch.object(sources, "fetch_slider_latest", side_effect=sources.SourceError("offline")), \
             patch.object(sources, "fetch_goes_geocolor") as goes:
            with self.assertRaises(sources.SourceError):
                sources.fetch_asia_pacific_4k_best_effort()
            goes.assert_not_called()

    def test_corrupt_download_is_not_returned_as_image(self):
        with patch.object(sources, "_request", return_value=(b"<html>error</html>", {})):
            with self.assertRaises(sources.SourceError):
                sources._download_image("https://example.com/error", max_retries=1)

    def test_apod_selects_recent_image_not_video_or_article(self):
        data = [{"date": "2026-10-11", "media_type": "video", "url": "article"},
                {"date": "2026-10-10", "media_type": "image", "url": "article", "hdurl": "image"}]
        with patch.object(sources, "_json", return_value=data), \
             patch.object(sources, "_download_image", return_value=Image.new("RGB", (2, 2))) as download:
            image, url = sources.fetch_apod_image()
            image.close()
            self.assertEqual(url, "image")
            download.assert_called_once_with("image", min_size=400)

    def test_threads_do_not_share_session(self):
        other = []
        thread = threading.Thread(target=lambda: other.append(sources._get_session()))
        thread.start()
        thread.join()
        self.assertIsNot(other[0], sources._get_session())
        other[0].close()

    def test_mars_gallery_filters_unrelated_search_results(self):
        data = [{"date": "2026-10-10", "_embedded": {"wp:featuredmedia": [
                    {"alt_text": "A nebula", "source_url": "nebula"}]}},
                {"date": "2026-10-03", "_embedded": {"wp:featuredmedia": [
                    {"alt_text": "Curiosity rover on Mars", "source_url": "mars"}]}}]
        with patch.object(sources, "_json", return_value=data), \
             patch.object(sources, "_download_image", return_value=Image.new("RGB", (2, 2))) as download:
            image, url = sources.fetch_mars_best_effort()
            image.close()
            self.assertEqual(url, "mars")
            download.assert_called_once_with("mars", min_size=400)


class RunnerTests(unittest.TestCase):
    def test_mode_switch_during_fetch_discards_old_frame(self):
        runner = main.Runner("earth", 1800, "fill")
        image = Image.new("RGB", (2, 2), "blue")
        def fetch():
            runner.switch_mode("asia_4k")
            return image, "old-goes"
        with patch.object(main, "_fetcher", return_value=fetch), \
             patch.object(main, "read_last", return_value=(None, None)), \
             patch.object(main, "set_wallpaper_from_image") as apply, \
             patch.object(main, "write_last") as save:
            runner._tick_once(force=True)
            apply.assert_not_called()
            save.assert_not_called()
        self.assertTrue(runner._wakeup.is_set())
        self.assertTrue(runner._force_refresh_requested)

    def test_stop_during_fetch_does_not_apply_wallpaper(self):
        runner = main.Runner("earth", 1800, "fill")
        def fetch():
            runner.stop()
            return Image.new("RGB", (2, 2)), "goes"
        with patch.object(main, "_fetcher", return_value=fetch), \
             patch.object(main, "read_last", return_value=(None, None)), \
             patch.object(main, "set_wallpaper_from_image") as apply:
            runner._tick_once()
            apply.assert_not_called()

    def test_force_request_during_tick_is_not_lost(self):
        runner = main.Runner("earth", 1800, "fill")
        calls = []
        def tick(force=False):
            calls.append(force)
            if len(calls) == 1:
                runner.force_refresh_now()
            else:
                runner._stop.set()
        runner._tick_once = tick
        runner.start()
        runner._thread.join(2)
        self.assertFalse(runner._thread.is_alive())
        self.assertEqual(calls, [False, True])


class AppTests(unittest.TestCase):
    def test_new_modes_persist_without_touching_user_config(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(config, "CONFIG_DIR", directory), \
             patch.object(config, "CONFIG_PATH", str(Path(directory) / "config.json")):
            for mode in ("goes_west", "asia_gk2a", "asia_modis", "earth_epic"):
                cfg = dict(config.DEFAULTS, mode=mode)
                config.save_config(cfg)
                self.assertEqual(config.resolve(None, "mode"), mode)
                self.assertTrue(callable(main._fetcher(mode)))

    def test_bilingual_menu_switch_and_force_only(self):
        runner = main.Runner("earth", 1800, "fill")
        tray = TrayController(runner.force_refresh_now, runner.switch_mode, runner.set_interval,
                              lambda: None, lambda: False, lambda: None, get_mode=runner.get_mode)
        menu = tray._build_menu()
        self.assertNotIn("刷新一次", [item.text for item in menu.items])
        earth_items = menu.items[1].submenu.items[0].submenu.items
        earth_items[1](None)
        self.assertEqual(runner.get_mode(), "goes_west")
        self.assertTrue(earth_items[1].checked)
        self.assertFalse(earth_items[0].checked)
        tray.language = "en"
        self.assertEqual(menu.items[0].text, "Force refresh")
        self.assertEqual(earth_items[1].text, "Pacific (GOES-18)")

    def test_bmp_encode_round_trip(self):
        with tempfile.TemporaryDirectory() as directory, Image.new("RGB", (10, 10), "red") as image:
            path = _save_as_bmp(image, str(Path(directory) / "wallpaper.bmp"))
            with Image.open(path) as saved:
                self.assertEqual(saved.getpixel((0, 0)), (255, 0, 0))


if __name__ == "__main__":
    unittest.main()
