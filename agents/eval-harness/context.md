# Evaluation harness

## Goal and working style

Build a prototype from scratch in this workspace. Use small, readable Python modules, basic data structures, and short code comments where they explain something the code cannot. Keep dependencies and abstraction to a minimum.

The milestone is to add a scenario as data, run it against two named configurations, and explain differences from the saved traces. Persistent memory, simulators, and dashboards are future work.

Use `agents/<project>/context.md` for decisions, major findings, results, and artifacts. Append updates to each project's `work.md` as work progresses.

## Design

- JSON scenarios, model configs, and traces work with the Python standard library. The runner plays scripted turns, selects context, executes local tool fixtures, and calls deterministic checks.
- Use OpenRouter for broad model coverage and native Anthropic Messages for direct Claude runs. Configurations include OpenRouter Sol and Astra, direct OpenAI Responses, scripted fakes, and a small callable interface for custom agents. OpenAI Responses supports tool calls on the Sol and Astra presets. Claude's protocol puts system and developer text in its system field, so traces retain both selected messages and the translated request payload.
- Use DeepSeek to generate candidate scenarios from user-written briefs. Review the generated JSON and checks before running the same file against OpenAI and Anthropic configurations. Generation and evaluation are separate CLI commands.
- The main eval presets are GPT-6.2 Sol and Astra via OpenRouter Responses and Claude Opus 5.5 and Fable 5.2 via Anthropic Messages. GPT-6 Luna and Claude Haiku 5.5 are smaller baselines. All six use catalog-listed IDs and have mocked tool round-trip coverage.
- DeepSeek V4.1 Flash runs through OpenRouter with reasoning enabled and Nebius FP4 pinned. OpenRouter reasoning details carry forward unchanged with selected assistant replies.
- The default context preserves prior messages in order. A recent-message limit trims prior messages, and the actual assistant reply becomes context for the next scripted turn.

## Results and artifacts

- The offline suite distinguishes full completion from a claim missing Gamma, catches the private detail in a reschedule draft, and shows the first action changing across three canary histories.
- Seven offline tests cover history, reply carryover, saved failures, execution errors, and mocked tool round trips for OpenRouter, OpenAI, and Anthropic, DeepSeek reasoning continuity, and the mocked brief-to-scenario-to-eval workflow. The user ran a live hello from their terminal. Saved traces confirm all seven presets, including DeepSeek, returned `Hello!` without execution errors. Live tool calls and DeepSeek scenario generation are still unverified.
- [README](../../readme.md) documents the CLI and scenario format. [Scenarios](../../scenarios/) and [model presets](../../models.json) are the editable inputs. The [partial-completion trace](../../results/c14814c035764f80a31dde33f9008232.json) is a local, Git-ignored run artifact.
- Git uses the standard `.git` directory on `main`.

## Live test worker

The sandbox cannot reach provider hosts or the user service bus. The host worker
runs an installed copy of the harness as a user-level systemd service. Its keys
live outside the workspace, and queued jobs can select installed model presets
and JSON scenarios. The workspace keeps job logs and traces under
`results/live-jobs/`. The user activated the host worker. The queued seven-model hello job passed live, confirming that the sandbox can submit jobs and inspect results through the workspace.

## Native subprocess presets

Claude Code runs in stream-JSON print mode with an isolated config directory.
Codex uses app-server JSON-RPC with an isolated Codex home. Each household and
preset has a persistent project and named session aliases. Fresh sessions reuse
the profile, and resumes reuse the actual native session ID. The current
presets disable native memory so the recall probe measures transcript continuity.

The benchmark supplies per-turn simulated timestamps and local MCP fixtures.
The agent CLI picks tools and manages its transcript. The benchmark records MCP
outcomes, final replies, usage, and session IDs, then scores the trace. A
persistent bank, email, and merchant simulation remains a later step.

Claude Code Opus 5.5 passed the live three-item fixture and recalled the seeded
fact only in the resumed session. Codex Sol 6.2 recalled the fact in a resumed
thread. OpenRouter returned HTTP 429 on later Sol fixture and fresh-thread
attempts. Codex Luna passed the live three-item fixture and reproduced the resumed-versus-fresh recall difference.

## Conversation dataset

The prototype dataset is JSONL with a stable ID, tag, one-line description,
ordered system/human/agent/tool turns, held-out final question, and expected response.
Tool call IDs link structured results to agent actions, including failed and
parallel calls. Optional setup instructions and a rubric support replay and
review without embedding scoring criteria in the dialogue. The DeepSeek
synthesis command accepts a user brief and saves a validated candidate.
The current dataset commands cover generation and validation.
