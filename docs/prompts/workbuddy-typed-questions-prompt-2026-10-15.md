# WorkBuddy tasks — typed four-platform questions (15 October 2026)

Two tasks, sent separately. **Task A** can start now. Send **Task B** only after the owner has
committed the backend change and Task A.

Shared background for both tasks:

- Until now, the Case demo page (`/cases`) ran only fixed demo questions. Typed questions on
  `/ask` reached only the travel-policy store.
- A new endpoint now answers **typed** questions across all four simulated platforms
  (Confluence, Jira, Slack, Drive). It uses the fictional fintech fixture in
  `data/fixtures/fintech_operations/`, a fixed fixture clock of `2026-10-12T03:00:00+00:00`, and
  always uses the `offline_extractive` provider. It never calls a live model or a live platform.
- Two new demo personas exist for that fixture (tenant `fintech-demo`):
  - `user-a` can read ordinary records **and** the restricted case and restricted invoice.
  - `user-b` can read ordinary records only.
  - Every other persona (`employee`, `auditor`, …) has no access to this fixture and gets
    `abstained`. That is correct behaviour, not a bug.
- The backend (`src/aspire_brain/main.py`, `src/aspire_brain/web/cases.py`,
  `src/aspire_brain/platforms/`) and its tests are being finished separately. Some answers may
  change while that work lands. Do not hard-code any expected answer or status in the UI.

### Endpoint contract

`POST /api/four-platform/queries`

- Headers: `Content-Type: application/json` and `X-CSRF-Token` set to the `csrf_token` returned by
  `GET /api/session`. The browser sends `Origin` itself; same-origin `fetch` is enough.
- Body: `{"question": "<text>"}`. The question must be 1–2000 characters and not blank. No other
  fields are allowed.
- `200` returns:
  `{query, principal, platforms, packet, time_scope, time_scope_note, provider_note}`.
  - `packet` has the same shape as the fixed cases' packets: `query_status`, `answer`,
    `citations`, `routing`, `source_status`, `context_budget`, `retrieval`,
    `incomplete_platforms`, `audit_event_id` and so on.
  - `time_scope_note` is a string when the question contains a relative date ("last week",
    "past 3 days", "today", …) and `null` otherwise.
- Errors return `{detail}` with one of these statuses:
  - `401` no persona chosen
  - `403` request verification failed
  - `409` access changed; retry
  - `422` invalid question, or a time window outside 1–365 days
  - `502` provider answer refused
  - `503` unavailable

---

## Task A — typed-question card on the Case demo page

### Scope (the only files you may change)

- `src/aspire_brain/web/templates/cases.html`
- `src/aspire_brain/web/static/cases.js`
- `src/aspire_brain/web/static/app.css` (only if an existing class cannot be reused)
- `tests/integration/test_web.py` (add tests; do not change existing ones)

Do not touch any other file. In particular, do not touch `main.py`, `cases.py`, anything under
`platforms/`, `data/`, README or `docs/`. Other work is in progress in those files.

### What to build

1. **Add a new panel at the top of `#cases`, before Case 1:**
   - Kicker `<b>New</b> Typed question`.
   - Heading "Ask across all four platforms".
   - A one-line description: typed questions run against a fictional fintech operations
     fixture on a fixed fixture clock (12 October 2026, 03:00 UTC), and are answered by
     `offline_extractive`.
   - A labelled `<textarea>` (maxlength 2000, required) prefilled with
     "How many supplier payments need manual review in the 09:30 handover?".
   - A submit button "Run typed query" and a `.case-result` container with `aria-live="polite"`.
2. **Add a short persona hint inside the panel.** Choose **user-a** or **user-b** in the
   travel-policy demo first. user-a can also read a restricted case and invoice; user-b cannot.
   Other personas have no access to this fixture.
3. **Add three or four example-question buttons that only fill the textarea** (they must not
   submit):
   - "Why is Cedar Quay's payment held?"
   - "What is being done about processing payments in OPS-DEMO-01 and what evidence remains missing?"
   - "What blockers were raised in Slack last week?"
4. **Wire it up in `cases.js`.** On submit, fetch `/api/session`. If there is no principal, show
   the same "choose a persona" note the other cards use. Otherwise POST to the endpoint above
   and render the result with the existing `renderResult()`. Also show `provider_note` and
   `time_scope_note` when present; `renderResult` already prints both. Disable the button while
   the request runs, and show `detail` for non-200 responses through `escapeHtml`.
5. **Keep the existing fixed-case click handler from catching the new button.** It currently
   binds every `[data-case] button`, so either give the panel no `data-case` attribute or scope
   the selector.

### Rules

- The page has a strict Content-Security-Policy (`script-src 'self'`). Use no inline scripts, no
  inline event handlers and no `style=` attributes. Bind everything from `cases.js`.
- Every value from the server goes through `escapeHtml()` before it reaches `innerHTML`.
- Keep the wording honest: say "simulated", "fictional fixture" and "fixed fixture clock". Do not
  say or imply live data, real platforms, real customers or measured latency.
- Match the existing card markup, class names and tone. Plain English, no exclamation marks.
- Do not mention any AI assistant, coding tool or model name in code, comments, markup, test
  names or the proposed commit message. Add no commit trailers.
- Do not add dependencies. Do not make network calls other than the local test server.
- Do not commit or push. The owner commits.

### Tests to add (`tests/integration/test_web.py`)

- `GET /cases` contains the new panel: the textarea, the submit button and the persona hint.
  Follow the TestClient setup that file already uses.
- `POST /api/four-platform/queries` as `user-a` with the prefilled question returns 200, and
  `packet.query_status` is one of `answered`, `partial`, `abstained`.
- Without a persona the endpoint returns 401. With a blank question it returns 422.

### Verify

- Run `python -m pytest tests/integration/test_web.py -q`, then the full
  `python -m pytest -q`. This sandbox may need pytest run outside it; see your own 15 October
  memory note about `pytest-of-*` directories.
- Run `python -m ruff check src tests`.
- Start the app (README "Start locally"), choose `user-a` on `/ask`, open `/cases`, run the
  prefilled question and one example, then repeat as `user-b`. Check the browser console for
  CSP errors.

### Report when done

1. `git diff --stat`. Only the files in scope should appear.
2. The pytest summary line (passed/failed counts) and the ruff result.
3. For each browser run: persona, question, `query_status`, number of citations.
4. Any problem with the endpoint contract. Report it; do not work around it in the backend.
5. A proposed commit message: one conventional-commit subject line under 72 characters, such as
   `feat(web): ask typed questions across the four simulated platforms`, plus an optional short
   body. No trailers and no tool names.

---

## Task B — documentation (send after the backend and Task A are committed)

### Scope (the only files you may change)

- `README.md`
- `docs/submission/SUBMISSION.md`
- `docs/submission/DEMO-WALKTHROUGH.md`
- `docs/demo.md`
- `docs/fintech-connector-fixtures.md`

### What to change

1. **Remove or rewrite every statement that typed questions cannot reach the four-platform
   index.** Find them with
   `grep -rn "typed" README.md docs/submission docs/demo.md docs/fintech-connector-fixtures.md`.
   Known places:
   - README, the limits paragraph ("The four-platform page runs fixed demo questions; typed
     questions on `/ask` reach the travel-policy store only").
   - SUBMISSION.md, the Case 1 row in the scenario table ("A fixed demo question; typed questions
     on `/ask` reach the travel-policy store…").
   - SUBMISSION.md, §3.4 "Honest scope statement" ("Two interface limits remain: the
     four-platform page runs the fixed demo questions above rather than typed ones…").
   - Keep the officer-inquiry limit ("one platform at a time"). It still holds.
2. **Replace each removed statement with an accurate one.** Typed questions on the Case demo
   page now run against the fictional fintech fixture across all four platforms. They use
   question-driven keyword routing and a fixed fixture clock (12 October 2026, 03:00 UTC), and
   are always answered by `offline_extractive`. The fixed cases still use their own small
   fixtures. Routing remains a keyword heuristic and ranking remains lexical.
   Also state the new completeness rule once, in SUBMISSION.md next to the routing description:
   - When a question has no platform signal, or is broad, every platform is queried as a
     precaution. A platform with no permitted match then marks the answer `partial`, lists that
     platform as incomplete and asks for human review. Before this change, the whole answer
     was withheld.
   - Platforms that are named explicitly or picked by a keyword signal still cause an
     abstention when they have no permitted match.
   - The fixed cases and the explicit four-platform requirement in
     `test_connector_fintech_workflow.py` are unchanged. So the "Missing budget" row in
     `docs/fintech-connector-fixtures.md` stays true; add only that a typed question with the
     same wording comes back `partial` with unrelated permitted evidence and human review, not
     an approved budget.
3. **README "Start locally":** one or two sentences saying that typed four-platform questions
   need the `user-a` or `user-b` persona. Also say that an existing database needs
   `python -m aspire_brain.cli import-fixtures --fixtures data/demo` or a fresh `init-demo` to add those personas.
4. **DEMO-WALKTHROUGH.md:** a short "Typed question" step. Run the same question as user-a and
   as user-b and show the permission difference. Use only results you actually observed in the
   running app, and state the persona, question, status and cited source IDs.
5. **`docs/fintech-connector-fixtures.md`:** one sentence saying the fixture now also backs the
   typed-question card. It is still offline, fictional and not live-verified.

### Rules

- Change only the sentences listed above, plus the minimum around them needed for grammar. Do
  not reword, reorder or "improve" other text.
- Do not add, remove or change any text about which tools, assistants or people built the
  project. That includes SUBMISSION.md §3.3, §5 and everything under `docs/reviews/`.
- Do not mention any AI assistant, coding tool or model name in new text or in the proposed
  commit message. Add no trailers.
- Do not change measured numbers (test counts, coverage, 16/16, and so on) unless you re-ran the
  command yourself. In that case, report the command and its output.
- Do not claim live data, real platforms, semantic understanding or measured latency.
- Do not commit or push.

### Report when done

1. `git diff --stat`. Only the files in scope should appear.
2. Each changed sentence, before and after.
3. The browser observations used in the walkthrough: persona, question, status, citations.
4. A proposed commit message such as
   `docs: describe typed four-platform questions and their limits`. No trailers and no tool names.
