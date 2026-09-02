#!/usr/bin/env python3

import json
import unittest

import main


class MainTest(unittest.TestCase):
    def test_execute_weather(self) -> None:
        result = main.execute_tool("get_weather", json.dumps({"city": "北京"}))
        self.assertEqual("多云，25℃，东北风3级", result)

    def test_unknown_tool_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "未知工具"):
            main.execute_tool("delete_all", "{}")

    def test_extra_arguments_are_rejected(self) -> None:
        arguments = json.dumps({"city": "北京", "admin": True})
        with self.assertRaisesRegex(ValueError, "只能包含 city"):
            main.execute_tool("get_weather", arguments)


if __name__ == "__main__":
    unittest.main()
