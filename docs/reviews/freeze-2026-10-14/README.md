# Clean-install verification (14 October 2026)

Commit `06a7e00` (cited earlier as `4889bf3`) on `feat/live-grounded-provider` was exported with `git archive` into an empty
directory, so ignored `artifacts/`, `var/`, `.env` and keys were absent. A new virtual
environment was created with Python 3.14.7 on macOS (Apple Silicon), and the README quick start
was followed as written. [Log](clean-install-tests.log).

| Check | Result |
| --- | --- |
| `pip install -r requirements.lock`, then `pip install --no-deps -e .` | Installed; `pip check` clean |
| `init-demo`, `doctor` | Exit 0 |
| Unit and integration tests (`pytest`, default test paths) | **954 passed** |
| Red-team tests (`pytest tests/redteam`) | **93 passed** |
| Statement coverage over `aspire_brain`, all 1,047 tests | **92.37%** (4,288 / 4,642) |
| `ruff check src tests` | Clean |
| `evaluate --offline`, `evaluate-grounding --offline` | Exit 0 |
| `audit-checkpoint`, then `audit-verify` against that checkpoint | Exit 0 |
| `uvicorn` on 127.0.0.1, then `GET /health`, `/cases`, `/ask`, `/audit` | All 200 |

Not covered here: browser end-to-end flows, Windows (the import and ledger-lock paths are
unit-tested with a stand-in, see [docs/pycharm.md](../../pycharm.md)), Python versions other
than 3.14, and any live provider or platform call.

Before publication, the committed history on every branch was also scanned for credential
patterns (Groq, OpenAI, Slack, GitHub, Google and Atlassian token shapes, and private-key
headers). Only documented placeholders matched, such as `FILL-xoxp-user-token` in
[eval/live_access/tokens.example.json](../../../eval/live_access/tokens.example.json). No `.env`,
key or token file has ever been committed.
