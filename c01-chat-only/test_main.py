#!/usr/bin/env python3

import unittest

import main


class ActionProtocolTest(unittest.TestCase):
    def test_valid_action_is_parsed_and_executed(self) -> None:
        action = main.parse_action(
            '{"name":"get_weather","arguments":{"city":"北京"}}'
        )
        self.assertEqual(main.ActionRequest("get_weather", "北京"), action)
        self.assertEqual("多云，25℃，东北风3级", main.execute_action(action))

    def test_markdown_wrapped_json_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "纯 JSON"):
            main.parse_action(
                '```json\n{"name":"get_weather","arguments":{"city":"北京"}}\n```'
            )

    def test_unknown_action_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "未知动作"):
            main.parse_action('{"name":"delete_file","arguments":{"city":"北京"}}')

    def test_extra_argument_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "只能包含 city"):
            main.parse_action(
                '{"name":"get_weather","arguments":{"city":"北京","admin":true}}'
            )

    def test_blank_city_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "非空字符串"):
            main.parse_action('{"name":"get_weather","arguments":{"city":" "}}')


if __name__ == "__main__":
    unittest.main()
