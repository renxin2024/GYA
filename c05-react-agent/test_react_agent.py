import unittest

from react_agent import ModelTurn, ReactRuntime, RunStatus, ToolCall


class ScriptedModel:
    def __init__(self, *turns): self.turns = iter(turns)
    def decide(self, messages, tools): return next(self.turns)


class ReactAgentTest(unittest.TestCase):
    def test_observation_changes_weather_argument(self):
        runtime = ReactRuntime(ScriptedModel(
            ModelTurn(tool_calls=[ToolCall("resolve_company_address", {"company_name": "北京总部"})]),
            ModelTurn(tool_calls=[ToolCall("get_weather", {"city": "北京"})]), ModelTurn(content="完成")))
        state = runtime.start("查询北京总部天气")
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertIn('runtime_execute=get_weather{"city": "北京"}', state.trace)

    def test_bad_parameter_becomes_observation_then_model_recovers(self):
        runtime = ReactRuntime(ScriptedModel(
            ModelTurn(tool_calls=[ToolCall("get_weather", {})]),
            ModelTurn(tool_calls=[ToolCall("resolve_company_address", {"company_name": "上海总部"})]),
            ModelTurn(tool_calls=[ToolCall("get_weather", {"city": "上海"})]), ModelTurn(content="完成")))
        state = runtime.start("查询总部天气")
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertIn("observation=get_weather:ERROR", state.trace)

    def test_runtime_stops_repeated_decisions(self):
        runtime = ReactRuntime(ScriptedModel(
            ModelTurn(tool_calls=[ToolCall("resolve_company_address", {"company_name": "上海总部"})]),
            ModelTurn(tool_calls=[ToolCall("resolve_company_address", {"company_name": "上海总部"})])))
        self.assertEqual(runtime.start("查询总部天气", max_steps=2).status, RunStatus.MAX_STEPS)


if __name__ == "__main__":
    unittest.main()
