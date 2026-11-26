import json
from pathlib import Path


def read_json(path):
    with Path(path).open(encoding="utf-8") as source:
        return json.load(source)


def load(path):
    return validate(read_json(path), path)


def validate(scenario, path):
    if not isinstance(scenario, dict):
        raise ValueError(f"{path}: expected a JSON object")
    for field in ("id", "instructions", "request", "expected"):
        if not isinstance(scenario.get(field), str) or not scenario[field].strip():
            raise ValueError(f"{path}: {field} must be a nonempty string")
    followups = scenario.get("followups", [])
    if not isinstance(followups, list) or any(
        not isinstance(request, str) or not request.strip() for request in followups
    ):
        raise ValueError(f"{path}: followups must be an array of nonempty strings")
    times = scenario.get("virtual_times")
    if times is not None and (not isinstance(times, list) or len(times) != len(followups) + 1
                              or any(not isinstance(time, str) for time in times)):
        raise ValueError(f"{path}: virtual_times must contain one string per turn")
    alternates = scenario.get("alternate_histories", {})
    if not isinstance(alternates, dict) or {"original", "none"} & alternates.keys():
        raise ValueError(f"{path}: alternate histories must have names other than original and none")
    for history in [scenario.get("history", []), *alternates.values()]:
        if not isinstance(history, list):
            raise ValueError(f"{path}: history must be an array")
        for message in history:
            if not isinstance(message, dict):
                raise ValueError(f"{path}: history messages must be objects")
            if message.get("role") not in ("system", "developer", "user", "assistant"):
                raise ValueError(f"{path}: unsupported history role {message.get('role')!r}")
            if not isinstance(message.get("content"), str):
                raise ValueError(f"{path}: history content must be text")
    checks = scenario.get("checks", [])
    if not isinstance(checks, list) or any(not isinstance(check, dict) for check in checks):
        raise ValueError(f"{path}: checks must be an array of objects")
    for check in checks:
        kind = check.get("type")
        turn = check.get("turn", len(followups) + 1)
        if type(turn) is not int or not 1 <= turn <= len(followups) + 1:
            raise ValueError(f"{path}: check turn is outside the scenario")
        if kind in ("contains", "omits") and isinstance(check.get("text"), str) and check["text"]:
            continue
        if kind == "first_action" and valid_action(check.get("action")):
            continue
        if kind == "actions_before_claim" and (
            isinstance(check.get("claim"), str) and check["claim"]
            and isinstance(check.get("actions"), list) and check["actions"]
            and all(valid_action(action) for action in check["actions"])
        ):
            continue
        raise ValueError(f"{path}: invalid check {check.get('id', kind)!r}")
    tools = scenario.get("tools", {})
    if not isinstance(tools, dict):
        raise ValueError(f"{path}: tools must be an object")
    for name, tool in tools.items():
        if not isinstance(tool, dict) or not isinstance(tool.get("description"), str) or (
            not isinstance(tool.get("parameters"), dict) or not isinstance(tool.get("fixtures"), list)
        ):
            raise ValueError(f"{path}: invalid tool {name!r}")
        for fixture in tool["fixtures"]:
            if not isinstance(fixture, dict) or not isinstance(fixture.get("arguments"), dict) or (
                "result" not in fixture or not isinstance(fixture.get("ok", True), bool)
            ):
                raise ValueError(f"{path}: invalid fixture for {name!r}")
    return scenario


def valid_action(action):
    return (
        isinstance(action, dict) and isinstance(action.get("name"), str)
        and isinstance(action.get("arguments", {}), dict)
    )


def history_for(scenario, name):
    if name == "original":
        return scenario.get("history", [])
    if name == "none":
        return []
    return scenario["alternate_histories"][name]


def message(role, content):
    return {"role": role, "content": content}


def select_context(instructions, history, request, recent):
    if recent is not None:
        history = history[-recent:] if recent else []
    return [message("system", instructions), *history, message("user", request)]
