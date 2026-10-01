# Groq provider preparation — design and feasibility (28 September 2026)

Stage **5A** of the Groq sequence: documentation, specification and read-only reconnaissance only.
This document designs the `GroqGroundedProvider` and the contracts around it. It implements
nothing, installs nothing, retrieves no credential and makes no inference request. **No Groq API
call was attempted in this stage.** Stage 5B needs the human-approved contract direction recorded
in [the review packet](../artifacts/prompt5a-groq-preparation-2026-09-28/human-review-packet.md).

Machine-readable companions (all under `artifacts/prompt5a-groq-preparation-2026-09-28/`):
[acceptance-test-matrix.json](../artifacts/prompt5a-groq-preparation-2026-09-28/acceptance-test-matrix.json),
[groq-vendor-facts-2026-09-28.json](../artifacts/prompt5a-groq-preparation-2026-09-28/groq-vendor-facts-2026-09-28.json),
[provenance.json](../artifacts/prompt5a-groq-preparation-2026-09-28/provenance.json), [source-hashes-before.json](../artifacts/prompt5a-groq-preparation-2026-09-28/source-hashes-before.json),
[schemas/](../artifacts/prompt5a-groq-preparation-2026-09-28/schemas/), [checks.json](../artifacts/prompt5a-groq-preparation-2026-09-28/checks.json).

---

## 1. Snapshot, scope and what was not done

| Item | Observed value |
|---|---|
| HEAD | `81c4836fd5fc7532c2df3b146203e2a3f1e72624` |
| Dirty paths | ` M docs/workbuddy-red-team-prompt-sequence.md`; untracked `eval/redteam/gate-baseline.json`, `eval/redteam/release_gate.py`, `eval/redteam/promptfoo/` |
| Required PDF | `becf449ce534fab6507f85f38aa50b85b210774cd578cdd2880c4240f71ab785` (3 213 145 bytes) — unchanged |
| Authored files hashed | 131 (`src/`, `tests/`, `eval/`, `data/`, `docs/`, `pyproject.toml`, `requirements.lock`, `README.md`, `plan.md`, `prompt.md`) |

All 103 hashes recorded by the preceding prompt-revision snapshot
(`artifacts/prompt5-groq-preparation-2026-09-28/reconnaissance.json`) were recomputed. **101
matched; 2 differed, and both are explained by that revision pass itself, not by drift in
application code:**

- `docs/workbuddy-red-team-prompt-sequence.md` — the recorded hash is the **HEAD blob**
  (`b1247d62…`), i.e. the value before the pointer-synchronisation edit at 17:30. It is the single
  tracked modification in the working tree.
- `artifacts/redteam-prompt4-2026-09-28/PROMPT5.md` — the recorded hash (`47442f46…`) is the
  pre-revision draft; the current bytes (`923083a4e3da6f34188c6d886f1feb6fe78ddb495f126b57a5d7d5abc1b22aad`)
  equal the `final_draft_sha256` that `agent-draft-review.json` records for the reviewed final draft.

Every application, test, evaluation, fixture, configuration and lock file hash matched. **The
Prompt 4 verification results remain attributable to the current application snapshot.**

**Snapshot attribution note.** Stage report §18 states "HEAD remains `14923c56f51f934cd8fb781eb9bc14fab81e70c5`".
That was true when §18 was written; `14923c5` is an ancestor of the current HEAD, and the
documentation commit `81c4836` (17:17:35) committed §18 together with the harness/playbook/test
changes it describes. §18's evidence hashes are unaffected, but its HEAD sentence describes its
own writing-time snapshot, not the current tree.

**Not done in this stage** (explicit): no adapter code, no dependency installation, no credential
retrieval or storage, no Groq API request, no discovery call against `/openai/v1/models`, no push,
deployment, publication or submission, nothing deleted, no existing report or package rewritten.

---

## 2. Preceding stage: actual human findings

Read before any dependent design work, and treated as evidence, not instruction.

| Packet item | Human finding (own words, verbatim in `HUMAN-FOLLOWUP-FINDINGS-2026-09-28.md`) | Scope limit the reviewer stated |
|---|---|---|
| A | Pass (scoped) | Packet-level |
| B | Pass, extended to one real-path `offline_extractive` normal request | One synthetic extractive request only; no synthesis, no source conflict |
| C | Pass, extended to the same packet's pre/post-revocation comparison | Causal dependency explicitly **unclosed** at the time of review |
| D | Pass (scoped) — the observed HTTP unsupported-claim refusal (502, nothing released, audited `unsupported_claim → controlled_failure`) | "forged" label not supported by audit; live model not covered; packet-not-saved not directly observed *at review time* |

Status: **human scoped review has occurred; no sign-off covers all acceptance criteria.** Items the
reviewer listed as still needed: the saved packet's version-ID list (closing C's causal chain), the
full 29 audit rows including `seq 17`, the notice-generation method, and — for a defensible
"forged" label — a hash or digest of the rejected claim. The closing addendum supplies several of
these **as new local observations that the reviewer's sign-off does not cover**, and the reviewer's
own words are preserved rather than upgraded.

Consequence for this stage: **no dependent work is advanced on the strength of those addenda.**
G0/G4/G5 remain open for their own remaining criteria. Agent review, automated tests and a webpage
are not human sign-off, and neither is this document.

---

## 3. Groq vendor facts, refreshed 28 September 2026

Full provenance, URLs and per-claim status: [groq-vendor-facts-2026-09-28.json](../artifacts/prompt5a-groq-preparation-2026-09-28/groq-vendor-facts-2026-09-28.json).
Public official documentation only; no authenticated console access.

### 3.1 Verified from public documentation

| Fact | Value |
|---|---|
| `openai/gpt-oss-20b` | **Production.** Context 131 072; max completion 65 536; $0.075 input / $0.037 cached input / $0.30 output per 1M |
| `openai/gpt-oss-120b` | **Production.** Context 131 072; max completion 65 536; $0.15 input / $0.60 output per 1M |
| `openai/gpt-oss-safeguard-20b` | **Preview** ("Safety GPT OSS 20B"). Context 131 072; max completion 65 536; $0.075 input / $0.037 cached / $0.30 output |
| Strict Structured Outputs (`strict: true`) | Exactly `openai/gpt-oss-20b`, `openai/gpt-oss-120b`, `qwen/qwen3.8-27b`. Safeguard is **best-effort only** |
| Strict-mode requirement | "All fields must be `required` and objects must set `additionalProperties: false`" |
| Structured Outputs restriction | "Streaming and tool use are not currently supported with Structured Outputs." |
| Unsupported-model behaviour | Not a silent downgrade — strict mode on an unsupported model is associated with **400 errors**; unlisted models fall back manually to JSON Object Mode |
| Rate limits | Apply **at the organization level, not per user**. Free plan for all three models: 30 RPM / 1K RPD / 8K TPM / 200K TPD. Developer-plan base: 20B and 120B 250K TPM / 1K RPM; Safeguard 150K TPM / 1K RPM |
| Optional ITPM/OTPM | "some organizations are also subject to separate per-minute limits on input tokens (ITPM) and output tokens (OTPM)" — shown as "X in / Y out" on the account limits page |
| Exceeding limits | HTTP `429`; `retry-after` set only on 429 |
| Reasoning (`reasoning_effort`) | `low`/`medium`/`high`, GPT-OSS only |
| Reasoning exposure | `reasoning_format` is **not supported** for GPT-OSS. Reasoning is returned in a `reasoning` field by default; `include_reasoning: false` excludes it |
| `max_completion_tokens` default | 1024 |
| Data retention default | "By default, Groq does not retain customer data for inference requests." |
| Retention exception | System reliability and abuse monitoring — "retained for up to **30 days**", opt-out available |
| ZDR | "All customers may enable Zero Data Retention (ZDR) in Data Controls settings." Disables retention-dependent features |
| Data location | "All customer data is retained in Google Cloud Platform (GCP) buckets located in the **United States**." |
| Server-error billing | "You will not be charged for requests that return server error codes." (500/502/503) |
| Deprecation notice | No fixed period published; observed history ranges ~1 week to ~3 months, announced per model by email |
| Preview deprecation | "Preview models may be discontinued at short notice with limited advance warning." |
| SDK | Python `pip install groq` (`from groq import Groq`), JS `npm install --save groq-sdk`; base host `api.groq.com`, path `/openai/v1/chat/completions` |

### 3.2 Recorded as UNKNOWN — not verified in this stage

- **Account entitlement and model permissions** for the selected subset. No authenticated access was
  used. `openai/` is model provenance, not an OpenAI API destination; nothing here confirms which
  models this account may call.
- **Exact account rate limits** and whether separate ITPM/OTPM limits apply (account limits page only).
- **ZDR setting** for this account (Data Controls page only).
- **Whether client-side timeout/cancellation is billed.** The docs state that 5xx are not charged and
  that `499` marks caller-cancelled requests in the logs page; they do **not** state the billing
  outcome of a caller-side abort. Treated as **may already be billed**.
- **Whether reasoning tokens are billed as completion tokens** — not stated on the reasoning page.
- **Measured end-to-end latency.** Vendor "~1000 tps" is a generation-speed reference, not a
  measured round-trip for this application, and must not be quoted as one.
- **Correlated-error behaviour across the family** in practice (see §5.4).

### 3.3 Facts that changed since the preceding snapshot

- The catalog now also lists `qwen/qwen3.8-27b` and `minimaxai/minimax-m2.7`, and the deprecation
  history now records `llama-guard-4-12b → openai/gpt-oss-safeguard-20b` (5 March 2026) and
  `llama-3.1-8b-instant → openai/gpt-oss-20b` / `llama-3.3-70b-versatile → openai/gpt-oss-120b`
  (16 August 2026). GPT-OSS is now the documented migration target for retired Llama models.
- The rate-limit page now presents Free-plan and Developer-plan tables explicitly; the earlier
  "30 RPM / 8K TPM" reference corresponds to the **Free plan**, and Developer-plan base limits are
  higher. Both are recorded above rather than one being quoted as "the" limit.

---

## 4. Feasibility: single-model route versus optional stages

The minimal route is **5A → 5B → 5C → 5D → 5E → 5F → 5J**. Stages 5G, 5H and 5I are independently
skippable.

| Route | Live spending envelopes | What it adds | Honest cost |
|---|---|---|---|
| **Minimal (recommended)** — one target, `openai/gpt-oss-20b` | **1** (5E one-attempt pilot; 5F fixed replay) | A real, bounded, synthetic quotation-only target that satisfies G4's "real synthetic model request" criterion | One model, one contract, one budget. Quotation-compliance and latency remain unmeasured until 5E |
| `openai/gpt-oss-120b` as the selected target instead | 1 | Same, with a larger model | Same shape; a **substitution**, not an addition. One selected 20B *or* 120B target is sufficient |
| **+5G** local evaluation-role contracts and mocks | 0 (local only) | Local contracts for the generator/classifier roles without any network | Pure preparation; no live evidence. Safe to do, but adds contract surface with no feasibility signal |
| **+5H** Safeguard advisory calibration | +1, separate approval | Advisory policy classification on synthetic cases | Preview-status model, best-effort schema, and a standing risk that model labels get treated as release authority. The stage rules already forbid that, which limits the value |
| **+5I** inert attack-candidate generation | +1, separate approval | Broader synthetic attack coverage | Model may **refuse** to generate attack candidates (rate unknown), output is untrusted and must be quarantined, human-promoted, and turned into a new fixed replay before it can affect anything |

**Recommendation: run the minimal route; skip 5G/5H/5I by default.** Do not require all three
models. Adding 5H and 5I buys marginal coverage at the cost of two more live envelopes and a second
and third member of the *same* model family in the trust path.

### 4.1 Feasibility risks, stated plainly

1. **Exact-quotation compliance is the central risk.** The release gate requires each claim to be a
   contiguous token span of exactly one cited source. Language models paraphrase by default. A model
   that paraphrases will be refused — correctly — and the observed effect will be availability loss,
   not a security failure. **The gate must not be weakened to make a model pass**; free
   paraphrase/synthesis needs a later, separately designed and tested contract.
2. **Latency against a fixed 5 s service timeout.** `QueryService.timeout_seconds` is hard-coded
   (see §7.1). A reasoning model with `max_completion_tokens` default 1024 plus queueing and prompt
   processing may exceed 5 s. Unmeasured until 5E.
3. **Reasoning/completion token accounting.** Reasoning is returned by default and its billing
   treatment is undocumented. `include_reasoning: false` must be set so no private chain of thought
   is returned, stored or treated as evidence.
4. **Correlated errors across the family.** See §5.4.
5. **Preview withdrawal.** Safeguard is Preview and may be discontinued at short notice. 20B/120B
   are Production with a stated migration path, but GPT-OSS is a young family and the deprecation
   history shows the whole family can be re-pointed at once.
6. **Shared organization limits.** All roles share organization-level RPM/TPM/RPD. A pilot that
   consumes the envelope can starve nothing else here, but a *second* role would compete with the
   first for the same organization budget — another reason to keep one live role.
7. **Context is not allowance.** The listed 131 072-token model context is a model property. It is
   not a permission to send 300 000 tokens, and the application already bounds retrieval far below
   it (`top_k=5`, `max_context_chars=10000`, search `min(5000, max_context_chars)`). The 300 000
   figure is the *agent task* ceiling and is unrelated to inference.

---

## 5. Proposed provider

### 5.1 `GroqGroundedProvider`

| Property | Proposed value |
|---|---|
| `service` | `"groq"` |
| `mode` / `provider_mode` | `"live_grounded"` (already a member of `LIVE_PROVIDER_MODES`) |
| Endpoint | fixed `https://api.groq.com/openai/v1/chat/completions` — bare HTTPS, host `api.groq.com`, no query, no fragment, no credentials. Accepted unchanged by `ProviderRuntimeConfig.bare_https_endpoint` |
| Model (initial) | `openai/gpt-oss-20b` — **quotation-only target** |
| Alternative | `openai/gpt-oss-120b` as an explicitly selected substitute target, or as an optional generator/analyst |
| Optional classifier | `openai/gpt-oss-safeguard-20b` — evaluation/advisory only |
| Dependency | Python SDK `groq`, **pinned to an exact version with a recorded integrity hash, human-approved before installation** |
| Region | recorded as `null`/unknown until the account's processing location is confirmed. GCP US buckets are the documented *retention* location and are not inference-region evidence |

**The dependency path does not exist yet.** `groq` appears in neither `pyproject.toml` nor
`requirements.lock`, and no lock entry or local package provides it. This is the same class of gap
that keeps Promptfoo `not_run`. **No install was attempted in this stage**, and 5B must not install
one without an approved pinned version.

### 5.2 Three separate roles, three separate contracts

Generation, target answering and advisory classification each get their **own client, contract,
request record, payload approval and budget**. They share dispatch controls only — never
conversations, never mutable last-call state.

| Role | Model | Contract | Live stage | Notes |
|---|---|---|---|---|
| **Target answering** | `openai/gpt-oss-20b` (or 120B) | strict JSON, §5.3 | 5E/5F | The only role needed for G4 |
| **Candidate generation** | 20B or 120B | strict JSON, §5.3 | 5I (optional) | Untrusted proposal; no tools; no automatic promotion |
| **Advisory classification** | `openai/gpt-oss-safeguard-20b` | best-effort JSON + local validation, §5.3 | 5H (optional) | Advisory only; never release authority |

### 5.3 Schemas

Machine-readable: [schemas/target-answer.schema.json](../artifacts/prompt5a-groq-preparation-2026-09-28/schemas/target-answer.schema.json),
[schemas/candidate.schema.json](../artifacts/prompt5a-groq-preparation-2026-09-28/schemas/candidate.schema.json),
[schemas/classifier.schema.json](../artifacts/prompt5a-groq-preparation-2026-09-28/schemas/classifier.schema.json).

**Target answer** (strict; all fields required, `additionalProperties: false`):

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["answer", "citation_ids", "abstain"],
  "properties": {
    "answer": {"type": "string", "minLength": 1, "maxLength": 16000},
    "citation_ids": {"type": "array", "maxItems": 50, "items": {"type": "string"}},
    "abstain": {"type": "boolean"}
  }
}
```

`answer`/`citation_ids` mirror the existing `ProviderOutput`. `abstain` is an addition whose only
purpose is to let a refusal be a **first-class, gate-safe** outcome instead of a fabricated
quotation. Semantics:

- `abstain: false` → `answer` must consist of literal quotations from the cited evidence. The
  existing `exact_cited_span` gate then decides support; a non-quotation is refused with the
  existing `unsupported_claim` → 502 path.
- `abstain: true` → the service **discards the model's `answer` text** and substitutes its own
  service-authored abstention notice, with `citation_ids` empty. No model-authored prose is released.

Structured Outputs controls *shape*, not citation authorization, factual support or source truth.
Satisfying this schema is not evidence of anything.

**Candidate** (strict; optional role):

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["carrier", "payload", "goal"],
  "properties": {
    "carrier": {"type": "string"},
    "payload": {"type": "string"},
    "goal": {"type": "string"}
  }
}
```

Untrusted proposal. Quarantined, never executed, never automatically promoted into the playbook; a
human promotes a frozen seed and a new fixed replay is designed before it can influence anything.

**Classifier** (best-effort; local validation mandatory):

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["policy_version", "decision", "rule_ids", "explanation", "assessed_unit",
               "assessed_direction", "limitation"],
  "properties": {
    "policy_version": {"type": "string"},
    "decision": {"enum": ["violates", "safe", "unresolved"]},
    "rule_ids": {"type": "array", "items": {"type": "string"}},
    "explanation": {"type": "string", "maxLength": 600},
    "assessed_unit": {"type": "string"},
    "assessed_direction": {"enum": ["input", "output"]},
    "limitation": {"type": "string"}
  }
}
```

Because Safeguard supports only **best-effort** schema, every response is validated locally and any
parse, shape or enum failure is **`unresolved` — never `safe`**. Safeguard checks a *supplied policy*;
it does not check factual entailment, retrieval permissions, source truth or whether an attack
succeeded. Classifier labels can never overwrite a Python check or enable release.

### 5.4 Correlated failure across the family

20B, 120B and Safeguard are all GPT-OSS derivatives hosted on the same infrastructure under the same
organization-level limits. Running two or three of them does **not** give independent verification:

- one organization-level `429` or capacity event affects every role at once;
- a Harmony-format or tokenizer-level change affects all three;
- a family-level deprecation can re-point or retire all three together.

This is the main reason the minimal single-model route is recommended, and it must be stated
wherever multi-model results are reported.

---

## 6. Release pipeline map

The required order, with the guard at each step. Steps 5–7 are the ones most easily got wrong.

| # | Step | Guard |
|---|---|---|
| 1 | Authorized retrieval | Tenant/ACL predicates execute before ranking and top-k |
| 2 | Bounded `ProviderInput` | ≤ 40 evidence items and ≤ `max_context_chars`; over-bound raises |
| 3 | Capacity/budget reservation | Atomic global **and** tenant reservation for request count, input tokens, output tokens and USD |
| 4 | Permission/source recheck | Fresh principal + revisions compared to the snapshot |
| 5 | Durable minimized send-intent record | Written **before** transport; carries evidence IDs, version IDs, content hashes, canonical wire-payload fingerprint, question fingerprint and a correlation ID |
| 6 | **Final source-bound authorization check after any audit/capacity await** | Re-reads permissions *after* steps 3–5, because those steps can await |
| 7 | Transport | Fixed host, redirects off, proxies off, retries off |
| 8 | Response validation | Strict local validation; refusal → abstention or controlled failure |
| 9 | Permission recheck | Before persistence |
| 10 | Packet persistence | Packet and successful audit event commit together |
| 11 | Release | Only after 8–10 pass |
| 12 | Future packet reads | Re-checks every saved dependency; revoked dependency denies the whole packet |

### 6.1 What must be recorded

- **Evidence identity**: chunk ID, document version ID, chunk `content_hash`, source locator.
- **Canonical wire-payload fingerprint**: SHA-256 over a canonicalised (sorted keys, fixed
  separators) serialisation of the exact request body.
- **Question fingerprint**: SHA-256 of the question text — so the question can be correlated without
  storing it in plaintext in the record.
- **Request correlation**: our own correlation ID, plus the vendor request ID when a response is
  received.
- **Dispatch timestamps and state.**

### 6.2 Four states that must stay distinct

| State | Meaning | Evidence it requires |
|---|---|---|
| **Intent** | A send-intent row is durable | The row exists. **Proves nothing about the vendor** |
| **Dispatch / possible send** | The request left our process | Transport started |
| **Response received** | A vendor response arrived | A correlation ID / vendor request ID |
| **Released** | Content was released to the requester | Steps 8–10 all passed |

**An intent row alone does not prove vendor receipt.** Conversely, a later revocation can **deny
release but cannot retract content already transmitted** — once a request is dispatched, the
evidence in it has left our boundary. That is an **irreversible external disclosure**, and it is the
single most important thing for the reviewer to accept before any live stage.

### 6.3 Concurrency and lease boundary — the honest version

A correct design needs a **lease** that covers steps 3–10 for one request, so two concurrent requests
cannot both pass the final authorization check against a snapshot that one of them then invalidates.
Proposed boundary: the lease is taken with the capacity reservation and released after persistence;
the final check at step 6 runs *inside* the lease.

**Remaining race, stated honestly:** the lease bounds our own concurrent writers. It does **not**
make the pre-audit check permanently fresh, because a revocation committed by another process (or by
the database directly) between step 6 and step 7 can still land after the check. The claim to make
is "the final check runs after every await in our own path and inside our own lease", **not** "the
check cannot become stale". Any stronger wording would be false.

---

## 7. Gaps in the current checkout

Verified by direct inspection on this snapshot. These are the changes 5B/5C/5D must make; none was
made here.

| # | Gap | Exact location | Consequence |
|---|---|---|---|
| 7.1 | **Service timeout fixed at 5 s** | `src/aspire_brain/answers/service.py:37` (`self.timeout_seconds = 5.0`), used at `:108`, reported at `:150`. `ProviderRuntimeConfig.timeout_seconds` exists at `src/aspire_brain/providers/runtime.py:39` but is **never read** | No way to configure a live timeout without editing code or reaching into a private attribute (only `tests/integration/test_answers.py:206` does) |
| 7.2 | **Environment parsing does not populate cost or timeout** | `src/aspire_brain/config.py:85-97` (`_provider_runtime`) constructs `ProviderRuntimeConfig` with `service`, `model`, `endpoint`, `region`, `enabled`, `entitlement` — **no `max_cost_usd`, no `timeout_seconds`** | Both fall back to defaults (`0` and `5.0`); no spend ceiling can be expressed today |
| 7.3 | **Live factory refuses** | `src/aspire_brain/providers/__init__.py:105-110` — after `require_entitled_runtime`, it unconditionally raises `ExternalProviderUnavailable` | Correct fail-closed behaviour today; 5D replaces it with the reviewed live path |
| 7.4 | **Shared last-runtime callback** | `src/aspire_brain/providers/grounded.py:41` stores one record (`self._runtime`) at construction; `:55-56` returns it; `runtime_record_for` (`runtime.py:91-98`) calls it with **no request scope** | A single mutable last-call record. Under concurrent live requests it can report **another request's** service/model/cost/latency/outcome. Unsuitable for live use |
| 7.5 | **`max_cost_usd` declared but unused** | `runtime.py:38` | No reservation, no ceiling, no accounting |
| 7.6 | **Runtime record has no correlation field** | `ProviderRuntimeRecord` (`runtime.py:58-71`) has `service`, `model`, `endpoint_host`, `region`, `cost_usd`, `latency_ms`, `error_category` — no request ID, question fingerprint or payload fingerprint | A live record cannot be tied to the request that produced it |
| 7.7 | **Abstention-with-evidence would be refused** | `service.py:113-114` — `if evidence and not output.citation_ids: raise ValueError(...)` | A model abstention while evidence exists would become a 502 instead of the service-authored abstention §5.3 defines. 5D must relax this **only** for an explicit abstention, without weakening support checks |
| 7.8 | **No `groq` dependency** | absent from `pyproject.toml` and `requirements.lock` | Nothing can be installed or imported until a pinned version is approved |
| 7.9 | **No credential present** | `.env` contains only `ASPIRE_DEMO_MODE`, `ASPIRE_PROVIDER_MODE`, `ASPIRE_DB_PATH`, `ASPIRE_SESSION_KEY_PATH`, `ASPIRE_AUDIT_KEY_PATH`; no `GROQ_API_KEY` anywhere in the tree | Expected; credential provisioning is a later, separately authorised step |

---

## 8. Budget, capacity and cancellation

- **Atomic reservations** for request count, input tokens, output tokens and USD — global **and**
  per tenant. A reservation that cannot be satisfied denies the send.
- **Unknown or zero limits deny sends.** An unset limit is not an unlimited limit.
- **Default SDK retries off.** Vendor retries multiply spend and blur correlation. No automatic
  attack-to-target loops.
- **Timeout/cancellation may already be billed.** The docs state 5xx are not charged and mark
  caller-cancelled requests as `499`; they do **not** state the billing outcome of a caller-side
  abort. Any cancelled or timed-out attempt is recorded as a possible charge, not a free one.
- **Estimates versus observed.** `cost_usd` stays `null` until a response provides usage. Estimated
  cost is labelled as an estimate; observed usage comes from the vendor response. Region and cost
  stay `null`/unknown when not observed.
- **Budget approval is not granted by this document.** Code enablement, entitlement and a stored key
  do not authorise transmission or spending. Only 5E/5F (and optional 5H/5I) may make explicitly
  approved, capped synthetic requests, each with its own payload approval and budget.

---

## 9. Transport, host and disabled surfaces

| Control | Setting |
|---|---|
| Host allowlist | `api.groq.com` only. The endpoint is a fixed constant, not environment-supplied |
| Scheme | HTTPS only; `ProviderRuntimeConfig.bare_https_endpoint` already rejects credentials, query and fragment |
| Redirects | **Disabled.** A redirect is a controlled failure, not a followed hop |
| Proxies | **Disabled.** No `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` inheritance; environment proxies are ignored |
| TLS verification | On, using the platform trust store |
| Retries | Off by default |
| Streaming | **Off** — Structured Outputs does not support streaming, and streaming release is prohibited |
| Tools / function calling | **Disabled.** No tools, no filesystem, no action channel |
| Browser search / code execution | **Disabled.** Both are advertised capabilities of these models; neither is used |
| Telemetry / tracing | **Disabled.** No analytics SDK, no trace exporter |
| `include_reasoning` | **`false`** — no private chain of thought is returned, stored or treated as evidence |
| Timeout | Configurable (see §7.1/§7.2); must not remain hard-coded for live use |

Note on `NetworkGuard`: it is a **Python IP-socket connect guard**, not process-wide isolation. It
covers guarded `connect`/`connect_ex`/`create_connection` calls only; DNS, UDP, native code and
subprocesses are not comprehensively intercepted. The ordinary deterministic gate stays offline and
is not a substitute for process-level egress control in a live stage.

---

## 10. Data handling and the irreversible disclosure boundary

**Retention.** Inference requests are not retained by default; the documented exception is
reliability/abuse logging for up to 30 days, opt-out available. ZDR is available to all customers in
Data Controls. **Whether this account has ZDR enabled is unknown and must be verified before any
live request.** Customer data is documented as retained in GCP buckets in the United States; that is
a *retention* location, not proof of the *inference* region.

**Minimisation.** The outbound payload carries only what the model needs: the question, the bounded
permitted evidence, and the service-authored decision summary. It carries **no** credentials, no
tenant or principal identifiers, no ACLs, no audit data, no packet IDs and no source URL paths.

**The boundary.** From the moment a request is dispatched, the evidence inside it has left our
control. A later revocation, ACL change or source deletion can **deny release** of a packet but
**cannot retract** what was already transmitted. This is the decision the reviewer is being asked to
accept explicitly, once, before any live stage.

---

## 11. One exact synthetic minimised outbound payload

Synthetic fixture data only — the demo corpus is fictional. This is the shape and the minimisation
level proposed for approval; it is **not** a request that was made.

Fixture provenance (all values recomputed from this snapshot):

| Field | Value |
|---|---|
| Question (synthetic) | `What is the general travel cap?` |
| Version | `sg-travel-v2`, state `approved`, `valid_from 2026-09-01` |
| Content hash | `5f9fc0771a29ff4716f42c7ac3a22decdda5b852b32ce53f15bc7bb86458d012` |
| Chunk | `sg-travel-v2:p2` |
| Chunk content hash | SHA-256 of the paragraph below |
| Source locator | `Fictional demo: sg-travel (sg-travel-v2) · paragraph 2` |

Request body (canonicalised for fingerprinting; pretty-printed here for review):

```json
{
  "model": "openai/gpt-oss-20b",
  "messages": [
    {"role": "system", "content": "<fixed service contract: quote the supplied evidence verbatim; cite only supplied ids; set abstain=true if you cannot quote>"},
    {"role": "user", "content": "QUESTION: What is the general travel cap?\n\nEVIDENCE (cite by id, quote verbatim):\n[sg-travel-v2:p2] Singapore contractor travel cap: SGD 250 per claim from 1 September 2026. This approved version explicitly supersedes v1 for its effective dates. Contractor claims additionally require project contract verification and receipts."}
  ],
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "target_answer",
      "strict": true,
      "schema": {
        "type": "object",
        "additionalProperties": false,
        "required": ["answer", "citation_ids", "abstain"],
        "properties": {
          "answer": {"type": "string"},
          "citation_ids": {"type": "array", "items": {"type": "string"}},
          "abstain": {"type": "boolean"}
        }
      }
    }
  },
  "include_reasoning": false,
  "max_completion_tokens": 1024,
  "temperature": 0.6,
  "stream": false
}
```

**Present in the payload:** the synthetic question, one permitted synthetic evidence paragraph with
its chunk ID, and a fixed service contract string.
**Absent by construction:** API key, tenant/principal ID, ACLs, audit rows, packet IDs, source URL
paths, other tenants' data, any real user prompt or answer.

**Unresolved before approval:** the exact system-contract wording (must be frozen and reviewed), the
final `max_completion_tokens`/`temperature`/`reasoning_effort` values, and whether the fixed
timeout is raised from 5 s for the pilot.

---

## 12. Acceptance and test matrix

Machine-readable, with requirement → planned test/observation → owner → status:
[acceptance-test-matrix.json](../artifacts/prompt5a-groq-preparation-2026-09-28/acceptance-test-matrix.json).

Summary of what it covers: snapshot/hash integrity and human-review gating; the three role contracts
and their schemas; the twelve-step pipeline including the post-await authorization check; the four
dispatch states and the non-retractability of transmitted content; concurrency/lease honesty;
budget/capacity/cancellation; transport and disabled-surface controls; classifier discipline
(unresolved ≠ safe, labels never enable release, frozen calibration labels, benign-quoted-injection
distinct from instruction-following); and the verification-surface requirements for the later
executable stages.

**Status vocabulary** used in the matrix:

- `existing_evidence` — already demonstrated in the saved Prompt 4 results; reused, not re-run.
- `planned` — a test or observation 5B/5C/5D/5E/5F must produce; nothing is claimed now.
- `blocked_pending_human` — cannot proceed until an attributed human decision exists.

**No implementation pass is claimed anywhere in this matrix.** Every `planned` row is a requirement,
not a result.

---

## 13. Human review packet

The concrete packet is
[human-review-packet.md](../artifacts/prompt5a-groq-preparation-2026-09-28/human-review-packet.md).
It asks for an **attributed design decision**, not permission to spend.

Decisions requested:

1. Selected Groq subset, role and exact model ID(s) — and confirmation that one target is enough.
2. Endpoint constant `https://api.groq.com/openai/v1/chat/completions` and host allowlist `api.groq.com`.
3. Dependency path: exact pinned `groq` version + integrity hash, approved before installation.
4. Data handling: accept or reject the retention/ZDR/region position in §10, including the explicit
   unknown.
5. The one minimised outbound payload in §11.
6. The quote/abstention contract in §5.3, including the `abstain` field and the §7.7 change.
7. **The irreversible external disclosure boundary in §10** — accept that transmitted evidence
   cannot be retracted by a later revocation.
8. Budget/capacity/cancellation rules in §8, including that an unknown limit denies the send and
   that a cancelled request may already be billed.
9. The test matrix in §12.
10. **Measurable pilot thresholds agreed before any measurement**: availability (minimum successful
    quotation-only answers), quotation acceptance rate, latency (p95 against the configured
    timeout), and classification error rates for the optional classifier.
11. The optional-stage skip decisions (5G/5H/5I) — confirm skip, or select with separate envelopes.

Missing facts or unsigned decisions keep preparation open. 5B does not start on an unsigned packet.

---

## 14. What this stage did not establish

- No live provider observation, no live connector acceptance, no product-use proof and no submission
  readiness. These four states remain distinct from *simulated source implementation*.
- A live response over synthetic sources would not verify live connectors or source truth.
- Account entitlement, exact rate limits, ZDR, inference region, measured latency and measured cost
  all remain **unknown**.
- G0/G4/G5 acceptance gaps are unchanged by this document. G4's "real synthetic model request"
  criterion is *designed for*, not met.
- Promptfoo remains `not_run`: no approved pinned dependency path, and the exact runner's egress is
  unverified.
- The human review of this design has not happened yet.

---

## 15. Next stage prerequisite

**5B (typed contracts and local tests) requires the human-approved contract direction** recorded in
the review packet. Until that exists, preparation stays open: no dependency installation, no
credential retrieval, no adapter implementation and no live request.
