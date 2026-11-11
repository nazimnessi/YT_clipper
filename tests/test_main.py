import unittest

from main import first_line


class MainTests(unittest.TestCase):
    def test_first_line_handles_empty_exception_message(self):
        error = RuntimeError("")

        self.assertEqual(first_line(error), "RuntimeError")

    def test_first_line_returns_first_message_line(self):
        error = RuntimeError("first line\nsecond line")

        self.assertEqual(first_line(error), "first line")


if __name__ == "__main__":
    unittest.main()
