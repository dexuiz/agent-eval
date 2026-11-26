import json
from copy import deepcopy
from time import perf_counter

from .adapters import Invocation, build
from .checks import evaluate
from .scenario import history_for, message, select_context


def execute_call(call, tools):
    action = {"id": call["id"], "name": call["name"], "arguments": call["arguments"]}
    try:
        arguments = call["arguments"]
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be an object")
        action["arguments"] = arguments
        tool = tools[call["name"]]
        match = next(
            (fixture for fixture in tool["fixtures"] if fixture["arguments"] == arguments), None
        )
        if match is None:
            raise ValueError("No tool fixture matches these arguments")
        ok = match.get("ok", True)
        return {**action, "ok": ok, "result": match["result"]}
    except (ValueError, KeyError) as error:
        return {**action, "ok": False, "result": {"error": str(error)}}


def play(adapter, scenario, history, recent, result):
    tools = scenario.get("tools", {})
    definitions = [{"name": name, "description": tool["description"], "parameters": tool["parameters"]}
                   for name, tool in tools.items()]
    requests = [scenario["request"], *scenario.get("followups", [])]
    virtual_times = scenario.get("virtual_times", [None] * len(requests))
    for turn_index, request in enumerate(requests):
        messages = select_context(scenario["instructions"], history, request, recent)
        turn = {"request": request, "response": None, "invocations": []}
        result["turns"].append(turn)
        exchanges = []
        for _ in range(12):
            step = {"messages": deepcopy(messages), "actions": []}
            turn["invocations"].append(step)

            def record_payload(payload):
                step["payload"] = deepcopy(payload)

            invocation = Invocation(
                scenario["id"], turn_index, deepcopy(messages), deepcopy(definitions),
                deepcopy(exchanges), record_payload, deepcopy(tools), virtual_times[turn_index],
            )
            start = perf_counter()
            try:
                reply = adapter(invocation)
            finally:
                step["latency_ms"] = round((perf_counter() - start) * 1000, 3)
            step.update(response=reply.text, usage=reply.usage, model=reply.model,
                        tool_calls=reply.calls, adapter_actions=reply.actions)
            if reply.agent_session:
                step["agent_session"] = reply.agent_session
            step["actions"].extend(reply.actions)
            if reply.error:
                raise RuntimeError(reply.error)
            if not reply.calls:
                turn["response"] = reply.text
                assistant = message("assistant", reply.text)
                if reply.reasoning_details is not None:
                    assistant["reasoning_details"] = reply.reasoning_details
                history = [*history, message("user", request), assistant]
                break
            executed = [execute_call(call, tools) for call in reply.calls]
            step["actions"].extend(executed)
            exchanges.append({"continuation": reply.continuation, "actions": executed})
        else:
            raise RuntimeError("Tool invocation limit reached")


def run(scenario, name, config, history_name="original", recent=None, observe=False):
    start = perf_counter()
    result = {
        "schema_version": 1,
        "scenario": scenario,
        "configuration": {"name": name, "settings": config},
        "context": {"history": history_name, "recent": recent},
        "status": "error",
        "turns": [],
        "checks": [],
        "error": None,
    }
    phase = "execution"
    try:
        play(build(config), scenario, history_for(scenario, history_name), recent, result)
        phase = "checks"
        if observe or not scenario.get("checks"):
            result["status"] = "observed"
        else:
            result["checks"] = evaluate(scenario["checks"], result["turns"])
            result["status"] = "pass" if all(check["passed"] for check in result["checks"]) else "fail"
    except Exception as error:
        result["error"] = {"phase": phase, "type": type(error).__name__, "message": str(error)}
    result["latency_ms"] = round((perf_counter() - start) * 1000, 3)
    return result
