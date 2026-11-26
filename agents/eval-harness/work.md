# Work log

## 2026-11-19

- Built the first Python prototype from an empty README. Added the CLI, scenario loading, context selection, provider and fake adapters, deterministic checks, and JSON traces.
- Added three starter scenarios and ran them under both fake configurations. Confirmed that the partial run records two completed items and reports Gamma missing.
- Verified that the canary history changes the first action and that scripted turns retain the real reply. Ran five offline tests, including mocked OpenAI and Anthropic tool calls.
- Initialized the local Git metadata and added this project tracker. Recorded the prototype-first design guidance and removed a redundant runner comment.

- Added OpenRouter with Sol and Astra presets, keeping native Anthropic available. Extended the offline provider test to cover OpenRouter tool calls, reasoning continuation, usage, and credential-free payload traces. No live call was made.
- Added the DeepSeek V4.1 Flash preset with reasoning enabled and Nebius FP4 pinned. Verified offline that the next turn sends unchanged reasoning details when context includes the assistant reply, and drops them with that reply when the limit is zero. Six tests pass. No OpenRouter key was set for a live run.
- Added a generation command for user-written briefs. It requests one synthetic case from DeepSeek, validates the JSON with the scenario loader, and writes a new file for review. Verified offline that the resulting file runs against two configurations with the existing CLI. Seven tests pass.
- Checked the target model IDs against the provider catalogs. Switched the two routed GPT-6.2 presets to OpenRouter Responses for tool calls and added Luna and Haiku baselines. The mocked tool test now covers all six eval presets. All seven tests pass. The environment still has no provider API keys for live verification.
- Prepared a one-turn hello scenario at `/tmp/evalharness-hello.json` and verified it with the fake preset. Live checks for Sol, Astra, Opus, Fable, Luna, Haiku, and DeepSeek are blocked here because provider keys are unset and the sandbox cannot resolve the API hosts.
- Inspected the user's live hello traces. Sol, Astra, Opus, Fable, Luna, Haiku, and DeepSeek all returned `Hello!` with no execution errors.
- Added a host worker and setup script for live tests. Queued a hello job for all seven presets. Verified the queue and log workflow with an offline copy. Host activation is pending the user's terminal.
- Confirmed host activation. The queued live hello job returned exit code 0 and all seven models passed the greeting check. Verified every saved trace.
- Installed Claude Code locally and added actual Claude Code and Codex subprocess presets. Added persistent household profiles, native session resume, simulated timestamps, and a benchmark-owned MCP fixture server. Nine offline tests pass.
- Verified Claude Code's live tool calls, cost deltas, resumed recall, and fresh-session control. Verified Codex Sol session resume and Codex Luna tool calls. OpenRouter rate-limited later Codex Sol runs.
- Completed the Codex Luna recall control. The resumed thread recalled the seeded code, and a fresh thread in the same profile did not.
- Added the conversation JSONL format, validation and DeepSeek synthesis commands, and two starter examples covering privacy and tool grounding.
- Ran DeepSeek synthesis live and validated the generated scheduling sample with human, agent, and tool turns. Both starter samples validate, an incomplete tool exchange is rejected, and all nine existing offline tests pass.
- Added ordered system turns to the conversation dataset and synthesis prompt. Updated the starter sample and verified that validation accepts system text and rejects empty system turns. All nine offline tests pass.

## 2026-11-25

- Reviewed the conversation dataset and system-turn support. Both starter samples validate and all nine offline tests pass.
- Moved Git metadata into the standard `.git` directory and prepared the initial commit on `main`. GitHub remote setup is pending a destination and authenticated access.
