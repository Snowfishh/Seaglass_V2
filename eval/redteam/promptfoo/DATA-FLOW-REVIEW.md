# Promptfoo data-flow review — 28 September 2026

**Status: `not_run`.** Promptfoo was neither installed nor executed in this pass. This document is
the reviewed design that a future, explicitly approved run would have to satisfy.

## 1. Why this is `not_run`

| Condition for running | Observed in this checkout |
| --- | --- |
| Available through an approved **pinned** dependency path | **No.** `promptfoo` is not on `PATH`, is absent from `requirements.lock` and `pyproject.toml`, and there is no `node_modules/`. The project's dependency set is Python-only; adding promptfoo would mean an unpinned network install. |
| A fully local static-test configuration is feasible | Only with a **local** generation/attacker provider. This checkout has no model runtime at all — its providers are deterministic offline ones (`offline_extractive`, `fake_grounded`) and the only "live" provider path is an unimplemented entitlement boundary. |
| The network/data flow is reviewed | Reviewed below. The review **fails** the local-only condition on several points. |
| Vendor documentation rechecked | Yes — see §2. |

Two of the three Step 3 preconditions fail, so the honest outcome is `not_run` with the design
preserved rather than an integration claim.

## 2. What the vendor documentation actually says (rechecked 28 September 2026)

Sources: [Data handling and privacy](https://www.promptfoo.dev/docs/red-team/troubleshooting/data-handling/),
[Red team configuration](https://www.promptfoo.dev/docs/red-team/configuration/).

| Concern | Finding | Consequence here |
| --- | --- | --- |
| Generation | Default behaviour without an API key is **hosted inference**: "Without an `OPENAI_API_KEY` or a usable Codex/ChatGPT login, Promptfoo uses hosted inference for test generation and grading", sending the `purpose`, plugin configuration and target setup details to `api.promptfoo.app`. | Would send project configuration off-machine. Not acceptable in this scope. |
| Grading | Same switch. "The `redteam.provider` configuration controls both attack generation and grading." Hosted grading sends "the prompt sent to your target", "your target's response" and "grading criteria". | A model-graded result would require either hosted grading or a local model that does not exist here. |
| `redteam poison` | Documented as sending "**complete document contents** and the requested goal" and: "this command always uses hosted generation, even when your own API key is configured". | **Excluded unconditionally.** It cannot be run locally at all. |
| Remote-only plugins | `harmful:*`, bias, domain-specific, and security plugins including `ssrf`, `bola`, `bfla`, **`indirect-prompt-injection`**, `ascii-smuggling`, plus `competitors`, `hijacking`, `off-topic`, `system-prompt-override`. | `indirect-prompt-injection` is precisely the class this suite covers — and it is remote-only. A local run could not use it. |
| Remote-only strategies | `audio`, **`citation`**, `gcg`, `goat`, `jailbreak:composite`, `jailbreak:goblin`, `jailbreak:hydra`, `jailbreak:likert`, `jailbreak:meta`. | `citation` is the strategy closest to this suite's citation-release boundary, and it is remote-only. |
| Telemetry | On by default: commands run, plugin/strategy types, assertion types; hosted telemetry may include package version, CI status, promptfoo user ID, email, cloud login status and authentication method. Endpoint `a.promptfoo.app` (PostHog). | Must be disabled explicitly (`PROMPTFOO_DISABLE_TELEMETRY=1`) even for a local run. |
| Network requirements | `api.promptfoo.app` (generation/grading), `api.promptfoo.dev` (consent tracking), `a.promptfoo.app` (telemetry). | Three distinct egress destinations by default. |
| Sharing / Cloud | "Credentials, authorization headers, provider config fields, and request examples **are** sent if you paste them into red team target/provider setup or test forms, sharing, Cloud sync, or other Cloud-backed features." | Excluded. No Cloud login, no sharing, no sync. |
| `PROMPTFOO_DISABLE_REMOTE_GENERATION=true` | "It is **not a network isolation guarantee** and does not disable telemetry, account/license checks, sharing, Cloud sync, red team target/provider test requests, red team target/provider setup helpers that do not rely on remote generation, or explicitly configured providers." | The disable flag alone is **not** sufficient evidence of locality. It has to be combined with telemetry-off, no Cloud login, no sharing, and a provider that is genuinely local. |
| Target evaluation | "Your target model is always evaluated locally." | The one reassuring statement — and the only part this design would rely on. |

## 3. Reviewed design (not executed)

The reviewed configuration is `eval/redteam/promptfoo/redteam.local.yaml`, with a fully in-process
synthetic target in `eval/redteam/promptfoo/local_target.py`.

Design constraints it encodes:

1. **Target is in-process and synthetic.** The Python provider imports `aspire_brain` and answers
   from a disposable SQLite database seeded from `data/demo/`. No socket is opened at all — so
   "localhost target" here means *no listener*, which is stronger than binding `127.0.0.1`.
2. **No remote-only plugin or strategy.** Only custom, file-based plugins would be used. In
   particular `indirect-prompt-injection` and the `citation` strategy are **excluded**, even
   though they are the closest matches to this suite's boundaries.
3. **No `redteam poison`.** Excluded unconditionally: it is hosted-only.
4. **Telemetry off, no Cloud login, no sharing, no sync.** `PROMPTFOO_DISABLE_TELEMETRY=1` and no
   authenticated Cloud session.
5. **Deterministic Python assertions remain authoritative.** A Promptfoo run could only ever
   *propose* findings. Nothing from it may block the release gate until a human has triaged it and
   a deterministic, replayable seed has been added to `playbook.v1.json`.
6. **Egress measurement, not egress trust.** Any future run must be executed under the same
   `NetworkGuard` used by `eval/redteam/release_gate.py`, and must record zero IP socket attempts.
   The environment variable is a preference, not a proof.

## 4. What a future approved run would have to show

* A pinned promptfoo version, recorded by exact version and integrity hash.
* `PROMPTFOO_DISABLE_TELEMETRY=1`, `PROMPTFOO_DISABLE_REMOTE_GENERATION=true`,
  `PROMPTFOO_DISABLE_REDTEAM_REMOTE_GENERATION=true`, no Cloud login.
* The `NetworkGuard` transcript showing `network_attempts: []`.
* A local generation/attacker provider that is itself offline — which this checkout does not have.
* Human triage of any model-graded finding, followed by a replayable deterministic seed before it
  can influence the gate.

Until all of that holds, the status stays **`not_run`** and no integration is claimed.

## 5. Prompt 4 correction — 28 September 2026

The earlier requirement for a local attacker model does not apply to a static `eval` with fixed
test inputs and deterministic assertions. The current [configuration reference](https://www.promptfoo.dev/docs/configuration/reference/)
allows inline tests and an optional red-team block; the [Python provider](https://www.promptfoo.dev/docs/providers/python/)
can call the synthetic local target. This is feasible as a design, with no generation or model
grading. It has not been validated by a pinned Promptfoo executable.

**Decision: `not_run`.** The approved pinned dependency path is absent: no PATH executable,
project lock entry or local Node dependency tree. The exact runner's egress behavior is therefore
unverified. No install, CLI evaluation or generation was attempted. The Python `NetworkGuard`
cannot isolate a Node process, its native calls or subprocesses.

The current [privacy documentation](https://www.promptfoo.dev/docs/red-team/troubleshooting/data-handling/)
still describes remote generation/grading and Cloud flows, and explicitly limits the disable flag.
[Telemetry](https://www.promptfoo.dev/docs/configuration/telemetry/) must be disabled separately.
The proposed static config disables sharing and telemetry and uses deterministic checks only;
these settings are design intent, not measured runtime isolation. Hosted generation/grading,
remote-only plugins/strategies, Cloud sync/sharing and `redteam poison` remain excluded. Any
model-graded finding needs human triage and a deterministic replay seed before gate use.
