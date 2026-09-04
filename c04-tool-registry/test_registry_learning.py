import unittest

from registry_learning import RefundDomain, Runtime, ToolResponse, build_registry


class RegistryLearningTest(unittest.TestCase):
    def test_unknown_tool(self):
        response = build_registry(RefundDomain("none")).execute("missing", {})
        self.assertEqual((response.error_code, response.recovery_action),
                         ("UNKNOWN_TOOL", "DO_NOT_RETRY"))

    def test_disabled_tool_stops_before_handler(self):
        domain = RefundDomain("none")
        registry = build_registry(domain)
        registry.disable("refund_order")
        response = registry.execute("refund_order", {"order_id": "O-100", "idempotency_key": "K"})
        self.assertEqual(response.error_code, "TOOL_UNAVAILABLE")
        self.assertEqual(domain.handler_execution_count, 0)

    def test_invalid_argument(self):
        response = build_registry(RefundDomain("none")).execute("get_weather", {})
        self.assertEqual(response.error_code, "INVALID_ARGUMENT")

    def test_other_handler_failure(self):
        response = build_registry(RefundDomain("none")).execute("search_notes", {"query": "mcp"})
        self.assertEqual((response.error_code, response.recovery_action),
                         ("EXECUTION_ERROR", "DO_NOT_RETRY"))

    def test_invalid_update_keeps_healthy_old_version(self):
        domain = RefundDomain("none")
        registry = build_registry(domain)
        old_version = registry.tools["refund_order"].version
        with self.assertRaisesRegex(ValueError, "输入契约不一致"):
            registry.register("refund_order", {"order_id"},
                              {"order_id", "idempotency_key"}, domain.refund)
        response = registry.execute(
            "refund_order", {"order_id": "O-100", "idempotency_key": "K-3"}
        )
        self.assertEqual(response.status, "SUCCESS")
        self.assertEqual(registry.tools["refund_order"].version, old_version)

    def test_timeout_after_success_replays_without_duplicate_refund(self):
        domain = RefundDomain("after_success")
        runtime = Runtime(build_registry(domain), domain)
        response = runtime.refund_with_recovery("K-1")
        self.assertEqual(response.status, "SUCCESS")
        self.assertEqual(domain.handler_execution_count, 1)
        self.assertIn("runtime_action=REPLAY_SUCCESS", runtime.trace)

    def test_timeout_before_execution_retries_once(self):
        domain = RefundDomain("before_execution")
        runtime = Runtime(build_registry(domain), domain)
        response = runtime.refund_with_recovery("K-2")
        self.assertEqual(response.status, "SUCCESS")
        self.assertEqual(domain.handler_execution_count, 1)
        self.assertIn("runtime_action=RETRY_ONCE", runtime.trace)


if __name__ == "__main__":
    unittest.main()
