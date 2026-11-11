import unittest

from frame import build_video_segments, decide


class FrameTests(unittest.TestCase):
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
