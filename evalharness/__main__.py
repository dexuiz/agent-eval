import argparse
import json
from pathlib import Path
from uuid import uuid4

from .runner import run
from .scenario import history_for, load, read_json


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run conversational eval scenarios.")
    parser.add_argument("scenarios", nargs="+", type=Path, help="JSON files or directories")
    parser.add_argument("--model", action="append", required=True, help="Named configuration, repeatable")
    parser.add_argument("--config", type=Path, default=Path("models.json"))
    parser.add_argument("--history", action="append", help="original, none, or an alternate name")
    parser.add_argument("--recent", type=int, help="Keep this many prior conversational messages")
    parser.add_argument("--observe", action="store_true", help="Skip behavior checks")
    parser.add_argument("--household", help="Persistent profile name for agent CLI presets")
    parser.add_argument("--agent-session", help="Name a session for later resume")
    parser.add_argument("--resume-agent", action="store_true", help="Resume the named agent session")
    parser.add_argument("--out", type=Path, default=Path("results"))
    args = parser.parse_args(argv)
    if args.recent is not None and args.recent < 0:
        parser.error("--recent must be nonnegative")
    try:
        configs = read_json(args.config)
        models = [(name, configs[name]) for name in args.model]
        paths = [file for path in args.scenarios
                 for file in (sorted(path.glob("*.json")) if path.is_dir() else [path])]
        if not paths:
            raise ValueError("No scenario files found")
        scenarios = [load(path) for path in paths]
        histories = args.history or ["original"]
        for scenario in scenarios:
            for history in histories:
                history_for(scenario, history)
        if args.resume_agent and not args.agent_session:
            raise ValueError("--resume-agent requires --agent-session")
        native = {"claude-code", "codex-cli"}
        for index, (name, config) in enumerate(models):
            if config["adapter"] not in native:
                continue
            if not args.household:
                raise ValueError(f"--household is required for {name}")
            if args.recent is not None:
                raise ValueError("--recent is unavailable for agent CLI presets")
            if args.agent_session and len(scenarios) * len(histories) != 1:
                raise ValueError("--agent-session requires one scenario and history")
            models[index] = (name, {**config, "household": {
                "name": args.household, "preset": name,
                "session": args.agent_session or uuid4().hex, "resume": args.resume_agent,
            }})
        args.out.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))

    exit_code = 0
    for scenario in scenarios:
        for model, config in models:
            for history in histories:
                result = run(scenario, model, config, history, args.recent, args.observe)
                path = args.out / f"{uuid4().hex}.json"
                with path.open("x", encoding="utf-8") as output:
                    json.dump(result, output, indent=2, ensure_ascii=False)
                    output.write("\n")
                status = result["status"]
                exit_code = max(exit_code, {"error": 2, "fail": 1}.get(status, 0))
                print(f"{status.upper():8} {scenario['id']} / {model} / {history}  {path}")
                if result["error"]:
                    print(f"  {result['error']['message']}")
                for check in result["checks"]:
                    if not check["passed"]:
                        print(f"  Failed {check['id']}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
