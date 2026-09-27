# Offline scenario evaluation

`cases.jsonl` contains synthetic scenarios with expected outcomes. They cover historical
and current policies, the September version boundary, employee and finance access,
P17 travel limits, exact monetary boundaries, missing terms and inputs, conflicting rules,
jurisdictions, currencies, untrusted text, and tenant and auditor permissions.

After setup, run:

```bash
python -m aspire_brain.cli evaluate --offline
```

The evaluator uses a fresh temporary fixture database, preserving changes to the
interactive demo. It needs no API credentials and makes no outbound model calls.
Results are written to `artifacts/evaluation.json` and `artifacts/evaluation.md` under
the selected runtime root. Read these generated reports for case counts, individual
checks and failures from that run.

## Reading the results

- **Policy correctness:** checks status, outcome, selected cap, applicable version,
  conflicts and missing evidence against fixture expectations.
- **Evidence selection:** checks for expected source IDs and forbidden text. Policy
  rules can supply citations independently of full-text search, so packet citations
  alone do not measure text retrieval. Lexical top-5 retrieval is reported separately,
  and dedicated tests exercise the lexical retriever. General questions about matters
  other than caps return inspected excerpts or abstain.
- **Live answer quality:** remains untested. Fake-provider output and timeout tests
  check how the app handles provider responses; they do not measure Tencent answer
  quality, claim support or resistance to prompt injection.

This small corpus does not establish accuracy or security across other inputs. Sentinel
checks look for specific protected text in tested outputs, context and logs; they cannot
rule out every disclosure. General-cap cases check guidance, not contractor approval.
All decisions depend on the requester's readable evidence and the supplied case details.

## Adversarial seed suite

[`redteam/`](redteam/README.md) holds a versioned, schema-validated deterministic red-team
playbook run against both local query paths (12 cases: 11 valid, 1 deliberate invalid control; 9
valid attacks, 2 benign controls). Run it with:

```bash
.venv/bin/python eval/redteam/harness.py            # writes artifacts/redteam/redteam-report.json
TMPDIR="$PWD/var/pytest-basetemp" .venv/bin/python -m pytest \
  tests/integration/test_redteam_playbook.py --basetemp="$PWD/var/pytest-basetemp"
```

Results and the two recorded open gaps (`/api/queries` has no claim-support gate; exact-span
support is not truth verification) are in
[`docs/redteam-boundary-map-2026-09-27.md`](../docs/redteam-boundary-map-2026-09-27.md).

## Regression checks

```bash
python -m pytest --cov=aspire_brain --cov-report=term-missing
python -m ruff check src tests
```

These checks cover source, history and packet routes; roles and tenants; input and import
validation; revocation and concurrent revisions; audit integrity and checkpoints;
provider handling; and rendered output. `pyproject.toml` sets an 80% coverage floor.
See the [current stage report](../docs/stage-report-2026-09-27.md) for verified results
and remaining gaps. [Progress](../docs/progress.md) records an earlier checkpoint.
Coverage measures exercised code, not security guarantees.

The `artifacts/` directory is ignored by Git. Keep runtime data out of commits, and
review reports before sharing them if future evaluations use private data.
