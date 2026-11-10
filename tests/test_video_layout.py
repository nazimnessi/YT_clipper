import unittest

from utils.video_layout import (
    LAYOUTS,
    choose_layout,
    classify_video,
    compose_regions,
)


class VideoLayoutTests(unittest.TestCase):
    def test_classifies_metadata_and_uses_general_for_ambiguous_text(self):
        self.assertEqual(classify_video({"title": "Podcast with a special guest"}), "podcast")
        self.assertEqual(classify_video({"title": "Gaming reaction interview"}), "general")
        self.assertEqual(classify_video({"title": "Weekly updates"}), "general")

    def test_selects_type_specific_layouts_and_fallbacks(self):
        self.assertEqual(choose_layout("podcast", 2), "two_person_vertical")
        self.assertEqual(choose_layout("podcast", 1), "single_speaker")
        self.assertIsNone(choose_layout("interview", 0))
        self.assertEqual(choose_layout("gaming", 0), "gameplay_fullscreen")
        self.assertEqual(choose_layout("tutorial", 1), "presenter_screen")

    def test_regions_crop_same_source_independently(self):
        faces = [(100, 100, 80, 120), (700, 100, 80, 120)]
        regions = compose_regions("podcast", "two_person_vertical", faces, 1280, 720)

        self.assertEqual(len(regions), 2)
        self.assertNotEqual(regions[0]["crop"], regions[1]["crop"])
        for region in regions:
            x, y, width, height = region["crop"]
            self.assertGreater(width, 0)
            self.assertGreater(height, 0)
            self.assertLessEqual(x + width, 1280)
            self.assertLessEqual(y + height, 720)

    def test_missing_face_requests_fallback_and_all_templates_are_selectable(self):
        self.assertIsNone(compose_regions("podcast", "two_person_vertical", [(10, 10, 20, 20)], 640, 360))
        self.assertEqual(set(LAYOUTS), {
            "podcast", "gaming", "reaction", "tutorial", "interview",
            "single_person", "presentation", "general",
        })

if __name__ == "__main__":
    unittest.main()
