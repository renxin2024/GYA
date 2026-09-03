import unittest
import main

class C03Test(unittest.TestCase):
    def test_swapped_only_changes_description(self):
        self.assertEqual(main.tools("precise")[0]["function"]["name"], main.tools("swapped")[0]["function"]["name"])
        self.assertNotEqual(main.tools("precise")[0]["function"]["description"], main.tools("swapped")[0]["function"]["description"])
    def test_observed_call_requires_correct_tool_and_id(self):
        self.assertEqual(main.observe("prompt-only", {"content":'{"name":"refund_order","arguments":{"order_id":"O-100"}}'}), ("refund_order", {"order_id":"O-100"}))
        self.assertEqual(main.observe("native-tools", {"tool_calls":[]}), (None, None))
