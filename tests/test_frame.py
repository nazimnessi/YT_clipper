import unittest
from unittest.mock import patch

from frame import build_auto_segments, build_video_segments, decide, _suggested_layout_enabled


class FrameTests(unittest.TestCase):
    def test_suggested_layout_environment_variable_defaults_to_enabled(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertTrue(_suggested_layout_enabled())
        with patch.dict("os.environ", {"USE_SUGGESTED_VIDEO_LAYOUT": "sometimes"}):
            with self.assertRaisesRegex(ValueError, "USE_SUGGESTED_VIDEO_LAYOUT"):
                _suggested_layout_enabled()

    def test_suggested_layout_environment_variable_parses_boolean_values(self):
        for value in ("true", "YES", "on", "1"):
            with self.subTest(value=value), patch.dict("os.environ", {"USE_SUGGESTED_VIDEO_LAYOUT": value}):
                self.assertTrue(_suggested_layout_enabled())
        for value in ("false", "NO", "off", "0"):
            with self.subTest(value=value), patch.dict("os.environ", {"USE_SUGGESTED_VIDEO_LAYOUT": value}):
                self.assertFalse(_suggested_layout_enabled())

    def test_auto_layout_can_fall_back_to_legacy_face_framing(self):
        shots = [(0, 3.0, [[
            (100, 100, 80, 120, 0.9),
            (700, 100, 80, 120, 0.9),
        ]])]

        suggested = build_auto_segments(shots, 1280, 720, "podcast", True)
        default = build_auto_segments(
            shots, 1280, 720, "podcast", True, suggested_layouts=False
        )

        self.assertEqual(suggested[0]["composition"]["layout"], "two_person_vertical")
        self.assertEqual(default[0]["layout"], "stacked")
        self.assertNotIn("composition", default[0])

    def test_forced_layout_is_preserved_for_vertical_source(self):
        result = decide([[(100, 100, 80, 120, 0.9)]], 360, 640, forced="single")

        self.assertEqual(result["layout"], "single")

    def test_auto_segments_inherit_and_merge_short_shots(self):
        shots = [
            (0, 0.5, [[]]),
            (0.5, 1.0, [[]]),
            (1.0, 3.0, [[]]),
        ]

        segments = build_video_segments(shots, 1280, 720, "podcast", True)

        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["start"], 0)
        self.assertEqual(segments[0]["end"], 3.0)
        self.assertIsNotNone(segments[0]["composition"]["regions"])


if __name__ == "__main__":
    unittest.main()
