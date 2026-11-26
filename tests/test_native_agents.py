import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evalharness.adapters import Reply
from evalharness.native_agents import NativeAgent
from evalharness.runner import run
from evalharness.scenario import load


class NativeAgentTest(unittest.TestCase):
    def test_profile_resume_and_fresh_session(self):
        scenario = load("scenarios/native/recall-check.json")
        config = {"adapter": "claude-code", "model": "test", "household": {
            "name": "cedar", "preset": "claude-code", "session": "seed", "resume": False,
        }}

        def claude(agent, prompt, instructions, env, mcp_args):
            self.assertIn("Simulated time: 2030-04-02T09:00:00Z", prompt)
            agent.session = agent.session or {"id": agent.session_file.stem}
            return Reply(text=agent.session["id"])

        with tempfile.TemporaryDirectory() as folder, patch.dict(
            os.environ, {"EVALHARNESS_AGENT_HOME": folder}
        ), patch.object(NativeAgent, "claude", claude):
            first = run(scenario, "claude-code", config, observe=True)
            config["household"]["resume"] = True
            resumed = run(scenario, "claude-code", config, observe=True)
            config["household"].update(resume=False, session="fresh")
            fresh = run(scenario, "claude-code", config, observe=True)

        def invocation(result):
            self.assertIsNone(result["error"])
            return result["turns"][0]["invocations"][0]

        self.assertEqual(invocation(first)["agent_session"], invocation(resumed)["agent_session"])
        self.assertEqual(invocation(resumed)["payload"]["resume_id"], "seed")
        self.assertIsNone(invocation(fresh)["payload"]["resume_id"])
        self.assertEqual(invocation(first)["payload"]["profile"], invocation(fresh)["payload"]["profile"])

    def test_mcp_records_fixture_calls_and_rejects_unconfigured_arguments(self):
        tools = load("scenarios/complete-scope.json")["tools"]
        requests = [
            {"id": 1, "method": "tools/list"},
            *({"id": index, "method": "tools/call", "params": {
                "name": "process_item", "arguments": {"item": item},
            }} for index, item in enumerate(("Gamma", "unknown"), 2)),
        ]
        with tempfile.TemporaryDirectory() as folder:
            fixture = Path(folder) / "fixture.json"
            journal = Path(folder) / "journal.jsonl"
            fixture.write_text(json.dumps(tools))
            result = subprocess.run(
                [sys.executable, "evalharness/fixture_mcp.py", str(fixture), str(journal)],
                input="".join(json.dumps(request) + "\n" for request in requests),
                capture_output=True, text=True, check=True, timeout=5,
            )
            responses = [json.loads(line)["result"] for line in result.stdout.splitlines()]
            actions = [json.loads(line) for line in journal.read_text().splitlines()]
        self.assertEqual(responses[0]["tools"][0]["name"], "process_item")
        self.assertEqual([response["isError"] for response in responses[1:]], [False, True])
        self.assertEqual([action["ok"] for action in actions], [True, False])
