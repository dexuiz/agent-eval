import json
import os
import re
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

from .adapters import Reply
from .agent_process import CodexRPC


NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}")
DATA = Path.home() / ".local" / "share" / "evalharness"


class NativeAgent:
    def __init__(self, config):
        self.config = config
        self.kind = config["adapter"]
        settings = config["household"]
        for name in (settings["name"], settings["preset"], settings["session"]):
            if not NAME.fullmatch(name):
                raise ValueError("Household, preset, and session names must be simple identifiers")
        root = Path(os.environ.get("EVALHARNESS_AGENT_HOME", DATA / "households")).resolve()
        self.profile = root / settings["name"] / settings["preset"]
        self.workspace = self.profile / "project"
        self.workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.agent_home = self.profile / "config"
        self.agent_home.mkdir(exist_ok=True, mode=0o700)
        self.session_file = self.profile / f"{settings['session']}.json"
        self.session = {}
        if settings["resume"]:
            self.session = json.loads(self.session_file.read_text(encoding="utf-8"))
        self.timeout = config.get("timeout", 180)

    def prompt(self, invocation):
        parts = []
        if not self.session:
            prior = invocation.messages[1:-1]
            if prior:
                parts.append("Prior conversation:\n" + json.dumps(prior, ensure_ascii=False))
        if invocation.virtual_time:
            parts.append(f"Simulated time: {invocation.virtual_time}")
        parts.append(invocation.messages[-1]["content"])
        return "\n\n".join(parts)

    def __call__(self, invocation):
        env = {key: os.environ[key] for key in (
            "PATH", "HOME", "USER", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR",
        ) if key in os.environ}
        prompt = self.prompt(invocation)
        with TemporaryDirectory(prefix="eval-fixtures-") as temp:
            fixture, journal = (Path(temp) / name for name in ("fixtures.json", "journal.jsonl"))
            fixture.write_text(json.dumps(invocation.fixtures), encoding="utf-8")
            mcp_args = [str(Path(__file__).with_name("fixture_mcp.py")), str(fixture), str(journal)]
            invocation.record_payload({
                "prompt": prompt, "instructions": invocation.messages[0]["content"],
                "profile": str(self.profile), "resume_id": self.session.get("id"),
                "virtual_time": invocation.virtual_time, "tools": invocation.tools,
            })
            try:
                if self.kind == "claude-code":
                    reply = self.claude(prompt, invocation.messages[0]["content"], env, mcp_args)
                else:
                    reply = self.codex(prompt, invocation.messages[0]["content"], env, mcp_args)
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                reply = Reply(error=str(error))
            if journal.exists():
                reply.actions = [json.loads(line) for line in journal.read_text().splitlines()]
            reply.agent_session = self.session.get("id")
            if self.session and not reply.error:
                self.session_file.write_text(json.dumps(self.session), encoding="utf-8")
            return reply

    def claude(self, prompt, instructions, env, mcp_args):
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is required for Claude Code")
        env.update(CLAUDE_CONFIG_DIR=str(self.agent_home), ANTHROPIC_API_KEY=key,
                   CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1")
        if not self.config.get("memory", False):
            env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
        installed = DATA / "cli" / "node_modules" / ".bin" / "claude"
        default_binary = str(installed) if installed.is_file() else "claude"
        binary = os.environ.get("EVALHARNESS_CLAUDE", default_binary)
        mcp = {"mcpServers": {"benchmark": {"command": sys.executable, "args": mcp_args}}}
        argv = [
            binary, "-p", "--output-format", "stream-json", "--verbose",
            "--model", self.config["model"], "--tools", "",
            "--permission-mode", "dontAsk", "--allowedTools", "mcp__benchmark__*",
            "--strict-mcp-config", "--mcp-config", json.dumps(mcp),
            "--append-system-prompt", instructions,
        ]
        if self.session:
            argv.extend(["--resume", self.session["id"]])
        response = subprocess.run(
            argv, input=prompt, capture_output=True, text=True,
            cwd=self.workspace, env=env, timeout=self.timeout,
        )
        events = [json.loads(line) for line in response.stdout.splitlines() if line.startswith("{")]
        result = next((event for event in reversed(events) if event.get("type") == "result"), {})
        if response.returncode or result.get("is_error") or not result:
            errors = result.get("errors") or result.get("result") or response.stderr.strip()
            raise RuntimeError(f"Claude Code failed: {errors or result.get('subtype', 'no result')}")
        usage = dict(result.get("usage") or {})
        prior_cost = self.session.get("cost_usd", 0)
        self.session = {"id": result["session_id"]}
        if "total_cost_usd" in result:
            cost = result["total_cost_usd"]
            usage.update(total_cost_usd=cost, incremental_cost_usd=round(cost - prior_cost, 10))
            self.session["cost_usd"] = cost
        return Reply(text=result.get("result", ""), usage=usage, model=self.config["model"])

    def codex(self, prompt, instructions, env, mcp_args):
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY is required for the Codex agent preset")
        env.update(CODEX_HOME=str(self.agent_home), OPENROUTER_API_KEY=key)
        argv = [
            os.environ.get("EVALHARNESS_CODEX", "codex"), "app-server",
            "--disable", "shell_tool", "-c", 'web_search="disabled"',
            "-c", f"features.memories={json.dumps(self.config.get('memory', False))}",
            "-c", 'model_provider="eval_router"',
            "-c", 'model_providers.eval_router.name="OpenRouter"',
            "-c", 'model_providers.eval_router.base_url="https://openrouter.ai/api/v1"',
            "-c", 'model_providers.eval_router.env_key="OPENROUTER_API_KEY"',
            "-c", 'model_providers.eval_router.wire_api="responses"',
            "-c", 'model_providers.eval_router.requires_openai_auth=false',
            "-c", 'mcp_servers.benchmark.default_tools_approval_mode="approve"',
            "-c", f"mcp_servers.benchmark.command={json.dumps(sys.executable)}",
            "-c", f"mcp_servers.benchmark.args={json.dumps(mcp_args)}",
        ]
        params = {"cwd": str(self.workspace), "sandbox": "read-only", "approvalPolicy": "never",
                  "model": self.config["model"], "developerInstructions": instructions}
        with CodexRPC(argv, self.workspace, env, self.timeout) as rpc:
            rpc.request("initialize", {
                "clientInfo": {"name": "evalharness", "title": "Eval Harness", "version": "0.1"},
                "capabilities": {"experimentalApi": True},
            })
            rpc.send({"method": "initialized"})
            if self.session:
                thread = rpc.request("thread/resume", {**params, "threadId": self.session["id"]})
            else:
                thread = rpc.request("thread/start", params)
            thread_id = thread["thread"]["id"]
            self.session = {"id": thread_id}
            turn = rpc.request("turn/start", {
                "threadId": thread_id, "input": [{"type": "text", "text": prompt}],
            })
            turn_id = turn["turn"]["id"]
            return self.codex_reply(rpc, thread_id, turn_id)

    def codex_reply(self, rpc, thread_id, turn_id):
        usage = None
        texts = []
        deadline = monotonic() + self.timeout
        while True:
            event = rpc.next(deadline)
            if "id" in event:
                rpc.deny(event)
                continue
            params = event.get("params", {})
            if params.get("threadId") != thread_id:
                continue
            method = event.get("method")
            if method == "item/completed" and params["turnId"] == turn_id:
                item = params["item"]
                if item["type"] == "agentMessage":
                    texts.append(item["text"])
            elif method == "thread/tokenUsage/updated" and params["turnId"] == turn_id:
                usage = params["tokenUsage"]
            elif method == "turn/completed" and params["turn"]["id"] == turn_id:
                turn = params["turn"]
                error = None if turn["status"] == "completed" else str(turn.get("error") or turn["status"])
                return Reply(text=texts[-1] if texts else "", usage=usage,
                             model=self.config["model"], error=error)
