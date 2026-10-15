# Clean-install verification (14–15 October 2026)

**Final verification, 15 October 2026.** Commit `94a42e9` on `main` was exported with
`git archive` into an empty directory, so ignored `artifacts/`, `var/`, `.env` and keys were
absent. A new virtual environment was created with Python 3.14.7 on macOS (Apple Silicon), and
the README quick start was followed as written. Later commits change documentation only.
[Log](clean-install-tests-2026-10-15.log).

| Check | Result |
| --- | --- |
| `pip install -r requirements.lock`, then `pip install --no-deps -e .` | Installed; `pip check` clean |
| `init-demo`, `doctor` | Exit 0 |
| Unit and integration tests (`pytest`, default test paths) | **958 passed**, and again in 5 further full runs |
| Red-team tests (`pytest tests/redteam`) | **93 passed** |
| Statement coverage over `aspire_brain`, all 1,051 tests | **92.38%** (4,290 / 4,644) |
| `ruff check src tests` | Clean |
| `evaluate --offline`, `evaluate-grounding --offline` | Exit 0 |
| `audit-checkpoint`, then `audit-verify` against that checkpoint | Exit 0 |
| `eval/live_model/run.py` dry run (fake model, no key, no network) | Exit 0 |
| `uvicorn` on 127.0.0.1, then `GET /health`, `/cases`, `/ask`, `/audit` | All 200 |

**Earlier verification, 14 October 2026.** Commit `06a7e00` (cited earlier as `4889bf3`; see the
[commit map](../assistant-attribution-2026-10-15/commit-map.txt)) passed the same checks with
954 unit/integration and 93 red-team tests and 92.37% coverage. [Log](clean-install-tests.log).
The four tests added since cover the forbidden-text check and the live-evaluation verdicts.

Not covered here: browser end-to-end flows, Windows (the import and ledger-lock paths are
unit-tested with a stand-in, see [docs/pycharm.md](../../pycharm.md)), Python versions other
than 3.14, and any live provider or platform call.

Before publication, the committed history on every branch was also scanned for credential
patterns (Groq, OpenAI, Slack, GitHub, Google and Atlassian token shapes, and private-key
headers). Only documented placeholders matched, such as `FILL-xoxp-user-token` in
[eval/live_access/tokens.example.json](../../../eval/live_access/tokens.example.json). No `.env`,
key or token file has ever been committed.
