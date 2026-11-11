import logging
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from utils.ai import AIUnavailable, ask_json


class AITests(unittest.TestCase):
    def test_bad_model_hierarchy_raises_ai_unavailable(self):
        settings = SimpleNamespace(ai="auto", ai_model_hierarchy=["bad-entry"])

        with self.assertRaisesRegex(AIUnavailable, "invalid AI model hierarchy"):
            ask_json("", list, settings, logging.getLogger("test"))

    def test_unknown_ai_mode_names_invalid_value(self):
        settings = SimpleNamespace(ai="unknown", ai_model_hierarchy=[])

        with self.assertRaisesRegex(AIUnavailable, "unknown"):
            ask_json("", list, settings, logging.getLogger("test"))

    def test_import_error_is_not_retried(self):
        settings = SimpleNamespace(ai="claude", ai_model_hierarchy=["claude:model"])
        log = logging.getLogger("test")

        def fake_retry(fn, retry_if, **kwargs):
            self.assertFalse(retry_if(ImportError("missing provider")))
            raise ImportError("missing provider")

        with patch("utils.ai.PROVIDERS", {
            "claude": (lambda *args: "", lambda: True),
            "gemini": (lambda *args: "", lambda: False),
            "groq": (lambda *args: "", lambda: False),
        }), patch("utils.ai.retry", side_effect=fake_retry):
            with self.assertRaises(AIUnavailable):
                ask_json("", list, settings, log)


if __name__ == "__main__":
    unittest.main()
