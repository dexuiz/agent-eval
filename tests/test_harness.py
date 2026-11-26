import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from evalharness.__main__ import main
from evalharness.generate import main as generate_main
from evalharness.runner import run
from evalharness.scenario import load, read_json

MODELS = read_json("models.json")


class HarnessTest(unittest.TestCase):
    def test_preserves_history_and_carries_actual_reply(self):
        scenario = load("scenarios/discreet-reschedule.json")
        result = run(scenario, "fake", MODELS["fake"])
        self.assertEqual(result["status"], "pass")
        first, second = result["turns"]
        self.assertEqual(first["invocations"][0]["messages"][1:-1], scenario["history"])
        self.assertEqual(second["invocations"][0]["messages"][-3:], [
            {"role": "user", "content": scenario["request"]},
            {"role": "assistant", "content": first["response"]},
            {"role": "user", "content": scenario["followups"][0]},
        ])
        limited = run(scenario, "fake", MODELS["fake"], recent=1)
        self.assertEqual(limited["turns"][1]["invocations"][0]["messages"][1:-1], [
            {"role": "assistant", "content": limited["turns"][0]["response"]},
        ])

    def test_history_variants_change_first_action(self):
        scenario = load("scenarios/canary-preference.json")
        for history, expected in [("original", "canary"), ("none", "full"), ("one-off", "full")]:
            with self.subTest(history=history):
                result = run(scenario, "fake", MODELS["fake"], history, observe=True)
                self.assertEqual(result["status"], "observed")
                self.assertEqual(result["checks"], [])
                action = result["turns"][0]["invocations"][0]["actions"][0]
                self.assertEqual(action["arguments"], {"mode": expected})

    def test_cli_saves_failed_check_and_partial_trace(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(StringIO()):
            status = main(["scenarios/complete-scope.json", "--model", "fake",
                           "--model", "fake-partial", "--out", folder])
            results = {row["configuration"]["name"]: row
                       for row in map(read_json, Path(folder).glob("*.json"))}
        self.assertEqual(status, 1)
        self.assertEqual(results["fake"]["status"], "pass")
        partial = results["fake-partial"]
        self.assertEqual(partial["status"], "fail")
        self.assertIsNone(partial["error"])
        evidence = partial["checks"][0]["evidence"]
        self.assertEqual(evidence["missing_actions"][0]["arguments"], {"item": "Gamma"})
        self.assertEqual(len(evidence["observed_actions"]), 2)

    def test_execution_error_keeps_attempt(self):
        scenario = load("scenarios/complete-scope.json")
        with patch.dict(os.environ, {}, clear=True):
            result = run(scenario, "sol", MODELS["sol"])
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["phase"], "execution")
        self.assertEqual(result["checks"], [])
        self.assertIn("messages", result["turns"][0]["invocations"][0])

    def test_provider_tool_round_trip(self):
        scenario = load("scenarios/complete-scope.json")
        cases = [
            ("sol", "OPENAI_API_KEY",
             {"status": "completed", "output": [
                 {"type": "function_call", "name": "process_item", "call_id": "call-alpha",
                  "arguments": json.dumps({"item": "Alpha"})}
             ]},
             {"status": "completed", "output": [
                 {"type": "message", "content": [{"type": "output_text", "text": "Alpha complete."}]}
             ], "usage": {"input_tokens": 30}},
             "input"),
            ("router-deepseek-flash", "OPENROUTER_API_KEY",
             {"choices": [{"finish_reason": "tool_calls", "message": {
                 "content": None, "reasoning_details": [{"type": "reasoning.encrypted", "data": "test"}],
                 "tool_calls": [{"id": "call-alpha", "type": "function",
                                 "function": {"name": "process_item", "arguments": '{"item":"Alpha"}'}}],
             }}]},
             {"choices": [{"finish_reason": "stop", "message": {"content": "Alpha complete."}}],
              "usage": {"input_tokens": 30}},
             "messages"),
            ("opus", "ANTHROPIC_API_KEY",
             {"stop_reason": "tool_use", "content": [
                 {"type": "tool_use", "name": "process_item", "id": "call-alpha", "input": {"item": "Alpha"}}
             ]},
             {"stop_reason": "end_turn", "content": [{"type": "text", "text": "Alpha complete."}],
              "usage": {"input_tokens": 30}},
             "messages"),
        ]
        _, _, first, second, message_key = cases[0]
        cases += [(name, key, first, second, message_key) for name, key in [
            ("astra", "OPENAI_API_KEY"),
            ("router-sol", "OPENROUTER_API_KEY"),
            ("router-astra", "OPENROUTER_API_KEY"),
        ]]
        _, key, first, second, message_key = cases[2]
        cases += [(name, key, first, second, message_key) for name in ("fable", "haiku")]
        _, key, first, second, message_key = cases[1]
        cases.append(("router-luna", key, first, second, message_key))
        for name, key, first, second, message_key in cases:
            with self.subTest(model=name), patch.dict(os.environ, {key: "test"}):
                responses = iter([first, second])

                def post(url, headers, payload, invocation):
                    self.assertEqual(payload["model"], MODELS[name]["model"])
                    if name in ("router-sol", "router-astra"):
                        self.assertEqual(url, "https://openrouter.ai/api/v1/responses")
                        self.assertTrue(payload["provider"]["require_parameters"])
                    invocation.record_payload(payload)
                    return next(responses)

                with patch("evalharness.adapters.post", side_effect=post):
                    result = run(scenario, name, MODELS[name], observe=True)
                self.assertEqual(result["status"], "observed", result["error"])
                turn = result["turns"][0]
                self.assertEqual(turn["response"], "Alpha complete.")
                initial, continuation = turn["invocations"]
                self.assertTrue(initial["actions"][0]["ok"])
                self.assertEqual(continuation["usage"]["input_tokens"], 30)
                self.assertIn("call-alpha", json.dumps(continuation["payload"][message_key][-1]))
                self.assertIn("completed", json.dumps(continuation["payload"][message_key][-1]))
                if name == "router-deepseek-flash":
                    payload = continuation["payload"]
                    self.assertEqual(payload["provider"], {
                        "only": ["nebius/fp4"], "allow_fallbacks": False, "require_parameters": True,
                    })
                    self.assertEqual(payload["messages"][-2]["reasoning_details"],
                                     first["choices"][0]["message"]["reasoning_details"])
                    self.assertNotIn("Authorization", payload)


    def test_deepseek_carries_reasoning_with_selected_history(self):
        name = "router-deepseek-flash"
        scenario = load("scenarios/discreet-reschedule.json")
        details = [{"type": "reasoning.encrypted", "data": "opaque", "index": 0}]

        def post(url, headers, payload, invocation):
            invocation.record_payload(payload)
            message = {"content": "Could we reschedule for Thursday?", "reasoning_details": details}
            return {"choices": [{"finish_reason": "stop", "message": message}]}

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test"}), patch(
            "evalharness.adapters.post", side_effect=post
        ):
            result = run(scenario, name, MODELS[name], recent=1, observe=True)
            without_prior = run(scenario, name, MODELS[name], recent=0, observe=True)

        self.assertEqual(result["status"], "observed", result["error"])
        payload = result["turns"][1]["invocations"][0]["payload"]
        self.assertEqual(payload["model"], "deepseek/deepseek-v4.1-flash-1017")
        self.assertEqual(payload["provider"], {"only": ["nebius/fp4"], "allow_fallbacks": False})
        self.assertEqual(payload["reasoning"], {"enabled": True})
        self.assertEqual(payload["messages"][-2], {
            "role": "assistant", "content": "Could we reschedule for Thursday?",
            "reasoning_details": details,
        })
        trimmed = without_prior["turns"][1]["invocations"][0]["payload"]["messages"]
        self.assertEqual([item["role"] for item in trimmed], ["system", "user"])


    def test_generate_saves_a_runnable_scenario(self):
        candidate = {
            "id": "synthetic",
            "instructions": "Give a short answer.",
            "request": "Name a fictional city.",
            "expected": "A city name.",
            "checks": [{"type": "contains", "text": "city"}],
        }

        def post(url, headers, payload, invocation):
            self.assertEqual(payload["model"], "deepseek/deepseek-v4.1-flash-1017")
            self.assertEqual(payload["messages"][-1]["content"], "Test a fictional city.")
            return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(candidate)}}]}

        with tempfile.TemporaryDirectory() as folder, redirect_stdout(StringIO()):
            brief = Path(folder) / "brief.txt"
            brief.write_text("Test a fictional city.")
            scenario = Path(folder) / "synthetic.json"
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test"}), patch(
                "evalharness.adapters.post", side_effect=post
            ):
                self.assertEqual(generate_main([str(brief), "--out", str(scenario)]), 0)
            self.assertEqual(load(scenario), candidate)
            self.assertEqual(main([str(scenario), "--model", "fake", "--model", "fake-partial",
                                   "--out", str(Path(folder) / "results")]), 0)


if __name__ == "__main__":
    unittest.main()
