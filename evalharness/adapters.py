import importlib
import json
import os
from dataclasses import dataclass, field
from typing import Callable, Protocol
from urllib.error import HTTPError
from urllib.request import Request as HTTPRequest, urlopen


@dataclass
class Invocation:
    scenario_id: str
    turn: int
    messages: list[dict]
    tools: list[dict]
    exchanges: list[dict]
    record_payload: Callable[[dict], None]
    fixtures: dict = field(default_factory=dict)
    virtual_time: str | None = None


@dataclass
class Reply:
    text: str = ""
    calls: list[dict] = field(default_factory=list)
    usage: dict | None = None
    continuation: list[dict] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)
    error: str | None = None
    model: str | None = None
    reasoning_details: list[dict] | None = None
    agent_session: str | None = None


class Adapter(Protocol):
    def __call__(self, invocation: Invocation) -> Reply: ...


def post(url, headers, payload, invocation):
    invocation.record_payload(payload)
    request = HTTPRequest(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", **headers}
    )
    try:
        with urlopen(request, timeout=120) as response:
            return json.load(response)
    except HTTPError as error:
        try:
            detail = json.load(error)
            description = detail.get("error", {}).get("message", "")
        except (ValueError, AttributeError):
            description = ""
        raise RuntimeError(f"HTTP {error.code}: {description or error.reason}") from None


class Responses:
    def __init__(self, config):
        self.config = config

    def __call__(self, invocation):
        inputs = list(invocation.messages)
        for exchange in invocation.exchanges:
            inputs.extend(exchange["continuation"])
            inputs.extend(
                {"type": "function_call_output", "call_id": action["id"],
                 "output": json.dumps(action["result"])}
                for action in exchange["actions"]
            )
        payload = {
            "model": self.config["model"],
            "input": inputs,
            "store": False,
            "include": ["reasoning.encrypted_content"],
            "max_output_tokens": self.config.get("max_output_tokens", 4096),
        }
        if "reasoning_effort" in self.config:
            payload["reasoning"] = {"effort": self.config["reasoning_effort"]}
        if invocation.tools:
            payload["tools"] = [
                {"type": "function", "strict": False, **tool} for tool in invocation.tools
            ]
        if self.config["adapter"] == "openrouter-responses":
            url = "https://openrouter.ai/api/v1/responses"
            key = os.environ["OPENROUTER_API_KEY"]
            if invocation.tools:
                payload["provider"] = {"require_parameters": True}
        else:
            url = "https://api.openai.com/v1/responses"
            key = os.environ["OPENAI_API_KEY"]
        data = post(url, {"Authorization": f"Bearer {key}"}, payload, invocation)
        error = None
        if data["status"] != "completed":
            details = data.get("incomplete_details") or data.get("error")
            error = f"Responses API returned {data['status']}: {details}"
        output = data.get("output", [])
        return Reply(
            text="\n".join(part.get("text", part.get("refusal", ""))
                           for item in output if item["type"] == "message"
                           for part in item["content"]),
            calls=[{"id": item["call_id"], "name": item["name"], "arguments": item["arguments"]}
                   for item in output if item["type"] == "function_call"],
            usage=data.get("usage"),
            continuation=output, error=error, model=data.get("model"),
        )


class OpenRouter:
    def __init__(self, config):
        self.config = config

    def __call__(self, invocation):
        messages = list(invocation.messages)
        for exchange in invocation.exchanges:
            messages.extend(exchange["continuation"])
            messages.extend(
                {"role": "tool", "tool_call_id": action["id"],
                 "content": json.dumps(action["result"])}
                for action in exchange["actions"]
            )
        payload = {
            "model": self.config["model"], "messages": messages,
            "max_tokens": self.config.get("max_output_tokens", 4096),
        }
        if "reasoning" in self.config:
            payload["reasoning"] = self.config["reasoning"]
        provider = dict(self.config.get("provider", {}))
        if invocation.tools:
            payload["tools"] = [
                {"type": "function", "function": tool} for tool in invocation.tools
            ]
            provider["require_parameters"] = True
        if provider:
            payload["provider"] = provider
        headers = {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"}
        data = post("https://openrouter.ai/api/v1/chat/completions", headers, payload, invocation)
        if data.get("error"):
            raise RuntimeError(data["error"]["message"])
        choice = data["choices"][0]
        message = choice["message"]
        calls = message.get("tool_calls") or []
        continuation = {"role": "assistant", "content": message.get("content"), "tool_calls": calls}
        reasoning_details = message.get("reasoning_details")
        if reasoning_details is not None:
            continuation["reasoning_details"] = reasoning_details
        finish = choice["finish_reason"]
        error = f"OpenRouter response stopped: {finish}" if finish in {"length", "error"} else None
        return Reply(
            text=message.get("content") or "",
            calls=[{"id": call["id"], "name": call["function"]["name"],
                    "arguments": call["function"]["arguments"]} for call in calls],
            usage=data.get("usage"), continuation=[continuation], error=error,
            model=data.get("model"), reasoning_details=reasoning_details,
        )


class Anthropic:
    def __init__(self, config):
        self.config = config

    def __call__(self, invocation):
        # Claude Messages represents instructions in a top-level system field.
        system = [item["content"] for item in invocation.messages
                  if item["role"] in {"system", "developer"}]
        messages = [item for item in invocation.messages if item["role"] in {"user", "assistant"}]
        for exchange in invocation.exchanges:
            messages.append({"role": "assistant", "content": exchange["continuation"]})
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": action["id"],
                 "content": json.dumps(action["result"]), "is_error": not action["ok"]}
                for action in exchange["actions"]
            ]})
        payload = {
            "model": self.config["model"], "messages": messages, "system": "\n\n".join(system),
            "max_tokens": self.config.get("max_output_tokens", 4096),
        }
        if invocation.tools:
            payload["tools"] = [
                {"name": tool["name"], "description": tool["description"],
                 "input_schema": tool["parameters"]} for tool in invocation.tools
            ]
        headers = {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"}
        if workspace := os.environ.get("ANTHROPIC_WORKSPACE_ID"):
            headers["anthropic-workspace-id"] = workspace
        data = post("https://api.anthropic.com/v1/messages", headers, payload, invocation)
        stop = data["stop_reason"]
        error = f"Anthropic response stopped: {stop}" if stop in {
            "max_tokens", "pause_turn", "model_context_window_exceeded"
        } else None
        return Reply(
            text="\n".join(block["text"] for block in data["content"] if block["type"] == "text"),
            calls=[{"id": block["id"], "name": block["name"], "arguments": block["input"]}
                   for block in data["content"] if block["type"] == "tool_use"],
            usage=data.get("usage"),
            continuation=data["content"], error=error, model=data.get("model"),
        )


class Fake:
    def __init__(self, config):
        self.scripts = config.get("scripts", {})

    def __call__(self, invocation):
        turns = self.scripts.get(invocation.scenario_id, [])
        if invocation.turn >= len(turns):
            return Reply(text=f"Fake reply to: {invocation.messages[-1]['content']}")
        rules = turns[invocation.turn]
        prior = invocation.messages[1:-1]
        for rule in rules:
            match = rule.get("history_match")
            if match:
                count = sum(match["text"].casefold() in item["content"].casefold()
                            for item in prior if item["role"] == match.get("role", "user"))
                if count < match.get("minimum", 1):
                    continue
            step = rule["steps"][len(invocation.exchanges)]
            return Reply(text=step.get("text", ""), calls=[
                {"id": f"fake-{len(invocation.exchanges)}-{index}", **call}
                for index, call in enumerate(step.get("calls", []))
            ])
        raise ValueError("No fake rule matched this turn")


def build(config):
    kind = config["adapter"]
    if kind in ("claude-code", "codex-cli"):
        from .native_agents import NativeAgent

        return NativeAgent(config)
    if kind == "custom":
        module, name = config["factory"].split(":", 1)
        return getattr(importlib.import_module(module), name)(config)
    adapters = {
        "openai": Responses,
        "openrouter-responses": Responses,
        "openrouter": OpenRouter,
        "anthropic": Anthropic,
        "fake": Fake,
    }
    return adapters[kind](config)
