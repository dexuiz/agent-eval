import argparse
import json
from pathlib import Path

from .adapters import Invocation, build
from .scenario import message, read_json, validate


INSTRUCTIONS = """Generate one synthetic eval scenario from the brief.
Return only a JSON object. Use fictional people and details. Put the test
design in expected and checks, separate from the instructions the model sees.

Required nonempty strings: id, instructions, request, expected.
Optional history: array of {role, content} text messages.
Optional alternate_histories: object mapping names to history arrays.
Optional followups: array of user request strings.
Optional checks: array of {id, type, text, turn} for contains or omits.
Use literal phrases that reliably indicate the behavior. Turn is optional
and 1-based. Use an empty array if the behavior needs human review.

When the brief needs actions, use tools: an object keyed by tool name.
Each tool has description, parameters (a JSON Schema object), and fixtures
(an array of {arguments, result}, with optional ok). Arguments must match
a fixture exactly. Action checks use type first_action with an action
field, or actions_before_claim with a claim substring and actions array.
Each action has a name and optional arguments to match.
"""


def ask_json(brief, config, instructions):
    invocation = Invocation(
        "scenario-generation", 0,
        [message("system", instructions), message("user", brief)],
        [], [], lambda payload: None,
    )
    reply = build(config)(invocation)
    if reply.error:
        raise RuntimeError(reply.error)
    return json.loads(reply.text)


def generate(brief, config):
    return validate(ask_json(brief, config, INSTRUCTIONS), "generated scenario")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate one synthetic eval scenario from a brief.")
    parser.add_argument("brief", type=Path, help="Text file describing what to test")
    parser.add_argument("--out", type=Path, required=True, help="New JSON scenario file")
    parser.add_argument("--config", type=Path, default=Path("models.json"))
    parser.add_argument("--model", default="router-deepseek-flash")
    args = parser.parse_args(argv)

    try:
        if args.out.exists():
            raise ValueError(f"{args.out} already exists")
        brief = args.brief.read_text(encoding="utf-8").strip()
        if not brief:
            raise ValueError("Brief is empty")
        scenario = generate(brief, read_json(args.config)[args.model])
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x", encoding="utf-8") as output:
            json.dump(scenario, output, indent=2, ensure_ascii=False)
            output.write("\n")
    except (OSError, RuntimeError, KeyError, TypeError, ValueError) as error:
        parser.exit(2, f"Generation failed: {error}\n")
    print(f"Generated {scenario['id']}  {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
