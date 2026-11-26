import argparse
import json
from pathlib import Path

from .generate import ask_json
from .scenario import read_json


INSTRUCTIONS = """Create one fictional conversation evaluation sample from the user's brief.
Return only a JSON object with these fields:
- id: a short unique identifier
- tag: one behavior category
- description: a single line describing the behavior under test
- turns: ordered prior conversation, using the roles system, human, agent, tool
- final_question: the held-out human question, separate from turns
- expected_response: a reference answer to the final question
Optional fields: instructions (setup shown to the agent) and rubric (array of
short criteria for judging responses that differ from the reference wording).

System and human turns have role and content (text). Use system turns
for instructions the agent should see at that point in the conversation.
Agent turns have role and content (text) and/or tool_calls (array of objects
with id, name, and arguments, where arguments is a JSON object).
Tool turns have role, call_id, and result (any JSON value). They may include
ok (a boolean) to distinguish a tool error. Each call ID must be unique
within the sample and have exactly one matching tool result. Finish all
pending tool calls before the next human or agent turn.
Keep the reference and scoring criteria out of the conversation.
"""


def text(value):
    return isinstance(value, str) and bool(value.strip())


def validate(sample):
    if not isinstance(sample, dict):
        raise ValueError("Expected a sample object")
    for field in ("id", "tag", "description", "final_question", "expected_response"):
        if not text(sample.get(field)):
            raise ValueError(f"{field} must be nonempty text")
    if len(sample["description"].splitlines()) != 1:
        raise ValueError("description must be a single line")
    if "instructions" in sample and not text(sample["instructions"]):
        raise ValueError("instructions must be nonempty text")
    rubric = sample.get("rubric", [])
    if not isinstance(rubric, list) or not all(text(item) for item in rubric):
        raise ValueError("rubric must be a list of nonempty strings")
    if not isinstance(sample.get("turns"), list):
        raise ValueError("turns must be a list")

    pending = set()
    seen = set()
    for index, turn in enumerate(sample["turns"], 1):
        try:
            validate_turn(turn, pending, seen)
        except ValueError as error:
            raise ValueError(f"turn {index}: {error}") from None
    if pending:
        raise ValueError(f"Missing tool results for {', '.join(sorted(pending))}")
    return sample


def validate_turn(turn, pending, seen):
    if not isinstance(turn, dict):
        raise ValueError("Expected a turn object")
    role = turn.get("role")
    if role == "tool":
        call_id = turn.get("call_id")
        if not text(call_id) or call_id not in pending:
            raise ValueError("Tool result must refer to a pending call")
        if "result" not in turn or not isinstance(turn.get("ok", True), bool):
            raise ValueError("Tool turn needs a result and may include a boolean ok")
        pending.remove(call_id)
        return
    if pending:
        raise ValueError("Finish pending tool calls before the next conversation turn")
    if role in ("system", "human"):
        if not text(turn.get("content")):
            raise ValueError(f"{role} turn needs text content")
        return
    if role != "agent":
        raise ValueError("Expected a system, human, agent, or tool turn")
    calls = turn.get("tool_calls", [])
    if not isinstance(calls, list) or ("content" in turn and not isinstance(turn["content"], str)):
        raise ValueError("Agent content must be text and tool_calls must be a list")
    if not calls and not text(turn.get("content")):
        raise ValueError("Agent turn needs text or at least one tool call")
    for call in calls:
        if not isinstance(call, dict) or not text(call.get("id")) or not text(call.get("name")):
            raise ValueError("Tool call needs an id and name")
        if call["id"] in seen or not isinstance(call.get("arguments"), dict):
            raise ValueError("Tool call needs a unique id and an arguments object")
        seen.add(call["id"])
        pending.add(call["id"])


def load(path):
    samples = []
    ids = set()
    with Path(path).open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                sample = validate(json.loads(line))
                if sample["id"] in ids:
                    raise ValueError(f"Duplicate sample ID {sample['id']!r}")
            except ValueError as error:
                raise ValueError(f"{path}:{line_number}: {error}") from None
            samples.append(sample)
            ids.add(sample["id"])
    if not samples:
        raise ValueError(f"{path}: no samples found")
    return samples


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate or synthesize conversation eval data.")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("validate")
    check.add_argument("dataset", type=Path)
    synthesize = commands.add_parser("synthesize")
    synthesize.add_argument("brief", type=Path)
    synthesize.add_argument("--out", required=True, type=Path)
    synthesize.add_argument("--config", type=Path, default=Path("models.json"))
    synthesize.add_argument("--model", default="router-deepseek-flash")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            print(f"Validated {len(load(args.dataset))} samples in {args.dataset}")
            return 0
        if args.out.exists():
            raise ValueError(f"{args.out} already exists")
        brief = args.brief.read_text(encoding="utf-8").strip()
        if not brief:
            raise ValueError("Brief is empty")
        sample = validate(ask_json(brief, read_json(args.config)[args.model], INSTRUCTIONS))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x", encoding="utf-8") as output:
            output.write(json.dumps(sample, ensure_ascii=False) + "\n")
        print(f"Generated {sample['id']} in {args.out}")
        return 0
    except (OSError, RuntimeError, KeyError, TypeError, ValueError) as error:
        parser.exit(2, f"Dataset error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
