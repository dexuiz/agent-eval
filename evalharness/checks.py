def matching_action(action, spec):
    return (
        action["ok"]
        and action["name"] == spec["name"]
        and all(action["arguments"].get(key) == value
                for key, value in spec.get("arguments", {}).items())
    )


def evaluate(checks, turns):
    results = []
    for check in checks:
        kind = check["type"]
        turn_number = check.get("turn", len(turns))
        if not 1 <= turn_number <= len(turns):
            raise ValueError(f"Check turn {turn_number} is outside the run")
        turn = turns[turn_number - 1]
        if kind in {"contains", "omits"}:
            text = turn["response"]
            found = check["text"].casefold() in text.casefold()
            passed = found if kind == "contains" else not found
            evidence = {"turn": turn_number, "text": check["text"], "found": found}
        elif kind == "first_action":
            actions = [action for step in turn["invocations"] for action in step["actions"]]
            first = next(iter(actions), None)
            passed = first is not None and matching_action(first, check["action"])
            evidence = {"turn": turn_number, "first_action": first}
        elif kind == "actions_before_claim":
            actions = []
            claim_at = None
            for index, step in enumerate(turn["invocations"], 1):
                if check["claim"].casefold() in step.get("response", "").casefold():
                    claim_at = index
                    actions.extend(step["adapter_actions"])
                    break
                actions.extend(step["actions"])
            missing = [spec for spec in check["actions"]
                       if not any(matching_action(action, spec) for action in actions)]
            passed = claim_at is not None and not missing
            evidence = {"turn": turn_number, "claim": check["claim"], "claim_at": claim_at,
                        "missing_actions": missing, "observed_actions": actions}
        else:
            raise ValueError(f"Unknown check type {kind!r}")
        results.append({"id": check.get("id", kind), "type": kind,
                        "passed": passed, "evidence": evidence})
    return results
