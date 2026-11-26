# Evaluation harness

Run conversational scenarios against model or agent configurations and inspect the evidence for each result. Requires Python 3.10+ and has no third-party dependencies. Run the commands from this directory.

## Run and inspect

Run a single scenario, then run the starter suite against two offline configurations:

```sh
python3 -m evalharness scenarios/complete-scope.json --model fake
python3 -m evalharness scenarios --model fake --model fake-partial
```

The second command intentionally produces failed checks. Each summary line prints the path to its trace. Open that file directly or format it in the terminal:

```sh
python3 -m json.tool results/<trace-id>.json
```

Each trace records the scenario, configuration, context settings, turn responses, and individual checks with evidence. Look in `turns[].invocations[]` for the selected messages, provider request body when sent, tool calls and results, latency, and reported token usage. Request bodies exclude authentication headers. Traces contain the scenario's original text and any alternate histories, so handle them as you would the source interaction.

Compare all three histories without scoring:

```sh
python3 -m evalharness scenarios/canary-preference.json --model fake \
  --history original --history none --history one-off --observe
```

The fake starts with a canary for repeated history and a full run for the other two. Omit `--observe` to score each run against the same canary-first expectation. Add `--recent N` to keep only the last N prior conversational messages, including replies from earlier scripted turns. Instructions and the current request are always included. Earlier tool exchanges stay in the trace. The final assistant reply carries forward to the next scripted turn. The Anthropic adapter places system and developer text in Claude's top-level system field. The trace retains the original selected messages and the translated request body.

CLI exit codes are 0 for passing or observation-only runs, 1 for behavioral failures, and 2 for execution errors or invalid CLI inputs. A suite continues through individual execution errors and exits with the highest code.

## Provider configurations

OpenRouter uses `OPENROUTER_API_KEY`. Native Anthropic uses `ANTHROPIC_API_KEY` and accepts `ANTHROPIC_WORKSPACE_ID` when your key requires it. The direct OpenAI presets `sol` and `astra` use `OPENAI_API_KEY`.

```sh
python3 -m evalharness scenarios --model router-sol --model router-astra
python3 -m evalharness scenarios --model opus --model fable
python3 -m evalharness scenarios/discreet-reschedule.json --model router-deepseek-flash --observe
```

Use `router-luna` (GPT-6 Luna) and `haiku` (Claude Haiku 5.5) for smaller baselines.
To smoke-test the four main presets with local fixture tools, set the provider keys and run:

```sh
python3 -m evalharness scenarios/complete-scope.json --observe \
  --model router-sol --model router-astra --model opus --model fable
```

The [DeepSeek preset](https://openrouter.ai/deepseek/deepseek-v4.1-flash-1017) enables reasoning and uses only Nebius FP4 with fallback disabled. OpenRouter reasoning details travel with the assistant reply when that reply is selected for the next turn.

To evaluate another OpenRouter model, add a named entry in [models.json](models.json) with `"adapter": "openrouter"` and its catalog ID in `"model"`. Tool scenarios require a route that accepts tool calls. Use `--config path/to/models.json` to load a different configuration file. Live responses may vary between runs. [OpenRouter models](https://openrouter.ai/models) · [Claude models](https://platform.claude.com/docs/en/about-claude/model-deprecations)

## Generate a scenario from a brief

Write a short brief describing the behavior to test, the prior context it
depends on, and what would count as success or failure. With
`OPENROUTER_API_KEY` set, generate a candidate using DeepSeek:

```sh
python3 -m evalharness.generate brief.txt --out scenarios/generated-example.json
```

Review the saved scenario and its checks before evaluating it. Generation
validates the file structure and requires a new output path. With
`ANTHROPIC_API_KEY` also set, pass the same file to the evaluation models:

```sh
python3 -m evalharness scenarios/generated-example.json \
  --model router-sol --model router-astra --model opus --model fable
```

## Add a scenario

Add a JSON file under `scenarios/` and point the CLI to it. For example:

```json
{
  "id": "meal-plan",
  "instructions": "Give a short answer.",
  "history": [{"role": "user", "content": "I prefer bean dishes."}],
  "alternate_histories": {"lentils": [{"role": "user", "content": "I prefer lentils."}]},
  "request": "Suggest a dinner.",
  "expected": "The suggestion accounts for the user's preference.",
  "checks": [{"id": "uses-beans", "type": "contains", "text": "bean"}]
}
```

Add `followups` as a list of user requests to make it multi-turn. Checks default to the last turn. Use the 1-based `turn` field to check an earlier one. The built-in checks are:

- `contains` and `omits` match case-insensitive substrings in the final reply for the selected turn. They are literal checks and can miss paraphrases.
- `first_action` matches the first attempted action by name and argument subset, and requires it to succeed.
- `actions_before_claim` requires a claim substring and each listed successful action to precede it. Calls requested in the same reply as the claim execute after that claim.

See [complete-scope.json](scenarios/complete-scope.json) for a tool example. Each tool declares its input schema and local fixtures keyed by exact arguments. An undeclared tool or unmatched argument produces an unsuccessful action with an error result. Checks and fixture results are evaluation data. Models receive the conversation and tool definitions. Omit checks or pass `--observe` for exploratory runs. The fake adapter echoes requests for new scenarios by default. To script its behavior, add an entry by scenario ID in the fake configuration. Each scripted turn contains rules tried in order, with an optional history match and one step per model invocation.

For a custom agent, set `"adapter": "custom"` and `"factory": "your_module:build_agent"` in a named configuration. The factory receives that configuration and returns a callable taking an [Invocation](evalharness/adapters.py) and returning a `Reply`. Supply text, token usage when available, and optional callable tool requests or completed action records. Completed action records have `name`, `arguments`, `ok`, and `result` fields and are treated as occurring before the returned text. Tool requests have `id`, `name`, and `arguments`. The next invocation of that turn includes prior tool exchanges. Use `record_payload` to capture the request body if your adapter wraps a remote model. Keep credentials in the environment since configuration settings are saved in traces.

Run the offline verification:

```sh
python3 -m unittest discover -s tests -v
```

## Live tests from a network-restricted session

Run this once from your regular, network-enabled terminal in this directory:

```sh
bash scripts/setup-live-worker.sh
```

Enter replacement OpenRouter and Anthropic keys at the hidden prompts. The
script stores them in a private file outside the repository and starts a
user-level systemd service. The worker uses an installed copy of the harness.

Queue a job by placing a JSON file with a unique name in
`results/live-jobs/inbox/`. An empty object runs the hello check against all
seven live presets. To run another scenario, use its filename stem and optionally
choose models, for example
`{"scenario":"complete-scope","models":["router-sol","opus"]}`.
The worker writes a job log and trace files under `results/live-jobs/`.
The log ends with `exit_code=` when the job finishes. Run the setup script
again to refresh the installed copy after code changes.

## Run actual agent CLIs

`claude-code` runs Claude Code with Opus 5.5 using `ANTHROPIC_API_KEY`.
`codex-cli` runs Codex app-server with GPT-6.2 Sol using
`OPENROUTER_API_KEY`. `codex-cli-luna` uses GPT-6 Luna.
Use a current CLI on PATH or set `EVALHARNESS_CLAUDE` or
`EVALHARNESS_CODEX` to its path. The Claude preset also checks the local
installation at `~/.local/share/evalharness/cli/node_modules/.bin/claude`.

```sh
python3 -m evalharness scenarios/complete-scope.json \
  --model claude-code --model codex-cli --household cedar
```

Each household and preset gets its own config directory and workspace under
`~/.local/share/evalharness/households`. Override the root with
`EVALHARNESS_AGENT_HOME`. The benchmark exposes scenario fixture tools over
MCP, logs their outcomes, and scores the final reply. These fixtures have no
real app side effects. A scenario can set `virtual_times` with one simulated
timestamp per turn. The CLI owns its own transcript and context compaction.
The trace shows the prompt supplied to the CLI and its session ID, while its
internal model prompts remain in the CLI's control.

To compare resumed and fresh sessions in the same profile:

```sh
python3 -m evalharness scenarios/native/recall-seed.json \
  --model claude-code --household cedar --agent-session seed
python3 -m evalharness scenarios/native/recall-check.json \
  --model claude-code --household cedar --agent-session seed --resume-agent
python3 -m evalharness scenarios/native/recall-check.json \
  --model claude-code --household cedar --agent-session fresh
```

Native memory is disabled in these presets, so the fresh recall check is
expected to fail. Scripted follow-ups within one run automatically resume.
For an opt-in memory comparison, copy a preset under a new name and set
`"memory": true`. Recall in a fresh session with that setting still needs
to be verified. Codex shell and web search are disabled, and Claude Code
exposes the benchmark MCP tools through its permission allowlist.

## Conversation eval datasets

Use JSONL with one sample per line. Each sample has `id`, `tag`, a
one-line `description`, ordered `turns`, a `final_question`, and an
`expected_response`. Optional `instructions` provide agent setup.
Optional `rubric` criteria let a reviewer accept equivalent responses.

| Role | Fields |
| --- | --- |
| `system` | `content` with instructions at that point in the conversation |
| `human` | `content` |
| `agent` | `content` and/or `tool_calls` with `id`, `name`, and `arguments` |
| `tool` | Matching `call_id`, JSON `result`, and optional boolean `ok` |

All calls in an agent turn need a result before the next conversational
turn or final question. The agent input for a future replay consists of the
optional instructions, prior turns, and final question. The reference answer
and rubric are for evaluation.

```sh
python3 -m evalharness.dataset validate datasets/starter.jsonl
python3 -m evalharness.dataset synthesize brief.txt --out datasets/generated.jsonl
```

Synthesis uses DeepSeek through OpenRouter by default. It generates one
fictional candidate per brief. Review the candidate before adding it to
a benchmark. The existing scenario runner still uses its scenario JSON
format. Dataset replay is a separate step.
