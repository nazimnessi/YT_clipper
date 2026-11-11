import shutil
import subprocess
import unittest

from render import _ts, build_filter, _render_key
from utils.config import Settings


class RenderTests(unittest.TestCase):
    def test_ass_timestamp_rounds_across_minute_boundary(self):
        self.assertEqual(_ts(59.996), "0:01:00.00")
        self.assertEqual(_ts(0), "0:00:00.00")
        self.assertEqual(_ts(3725.5), "1:02:05.50")

    def setUp(self):
        self.segments = [{
            "start": 0,
            "end": 1,
            "layout": "stacked",
            "crops": [],
            "composition": {
                "regions": [
                    {"crop": [0, 0, 320, 180], "x": 0, "y": 0, "width": 1, "height": 0.5},
                    {"crop": [320, 0, 320, 180], "x": 0, "y": 0.5, "width": 1, "height": 0.5},
                ],
            },
        }]

    def test_composed_graph_has_no_empty_filters(self):
        graph = build_filter(self.segments, 0, 1, False, False, None)

        self.assertNotIn(";;", graph)

    def test_composed_crop_is_even_and_within_source_bounds(self):
        segments = [{
            "start": 0,
            "end": 1,
            "composition": {
                "regions": [{
                    "crop": [-1, -3, 999, 999],
                    "x": 0, "y": 0, "width": 1, "height": 1,
                }],
            },
        }]

        graph = build_filter(segments, 0, 1, False, False, None, 641, 361)

        self.assertIn("crop=640:360:0:0", graph)

    def test_render_key_changes_with_settings_and_segments(self):
        settings = Settings()
        frame = {"segments": [{"start": 0, "end": 1}]}
        clip = {"title": "clip"}
        key = _render_key(frame, clip, settings)

        self.assertNotEqual(key, _render_key(frame, clip, settings.model_copy(update={"crf": 21})))
        self.assertNotEqual(key, _render_key({"segments": [{"start": 0, "end": 2}]}, clip, settings))

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is not installed")
    def test_composed_graph_runs_in_ffmpeg(self):
        graph = build_filter(self.segments, 0, 1, False, False, None)
        result = subprocess.run(
            [
                shutil.which("ffmpeg"),
                "-f", "lavfi", "-i", "color=c=red:s=640x360:r=30:d=1",
                "-filter_complex", graph, "-map", "[vout]", "-f", "null", "-",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
