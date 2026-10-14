# PyCharm and local setup

Open the repository root containing `pyproject.toml` as a Python project.

## macOS/Linux

Verified on 27 September 2026: **Python 3.14.2**, macOS 15.6.1 on Apple Silicon,
with `.venv/bin/python`. The saved PyCharm project SDK is labelled `Python 3.14`;
select `.venv/bin/python` explicitly to use the verified environment. FastAPI is
0.141.1 and Pydantic is 2.13.5. The package allows Python 3.12 or newer, but other
interpreter versions and Linux have not been verified.

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
python -m aspire_brain.cli init-demo
python -m aspire_brain.cli doctor
```

If `.venv` already exists, skip the creation command and activate it. In PyCharm's
interpreter settings, select `.venv/bin/python`. The `--no-deps` install keeps the
versions installed from `requirements.lock`.

## Windows equivalent

These are equivalent PowerShell commands; Windows execution has not been verified on the macOS development machine. The application imports no POSIX-only module: on Windows the live-provider spend ledger locks with `msvcrt` instead of `fcntl`, and key-file permission checks are skipped because Windows has no POSIX mode bits. Both paths are unit-tested on macOS with a stand-in, not on Windows itself.

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m aspire_brain.cli init-demo
.\.venv\Scripts\python.exe -m aspire_brain.cli doctor
.\.venv\Scripts\python.exe -m uvicorn aspire_brain.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers --no-access-log
```

Select `.venv\Scripts\python.exe` in PyCharm. Direct interpreter calls avoid requiring a PowerShell activation-policy change. Optional activation is `.\.venv\Scripts\Activate.ps1`; in Command Prompt it is `.venv\Scripts\activate.bat`.

## Run/debug configuration

Create a **Python** run configuration with these values:

| Setting | Value |
|---|---|
| Run target | Module name |
| Module | `uvicorn` |
| Parameters | `aspire_brain.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers --no-access-log` |
| Interpreter | Project `.venv` interpreter |
| Working directory | Repository root |

Run `init-demo` first. The application loads `.env` from the working directory; process environment values take precedence. Key path settings point to generated files, not literal secrets. Do not paste secrets into shared run configurations, source files, prompts, screenshots or reports. Keep `.env` and `var/` private and ignored by Git.

Use [http://127.0.0.1:8000](http://127.0.0.1:8000) consistently; switching between `localhost` and `127.0.0.1` changes the cookie/origin context. The selector and query forms manage CSRF tokens automatically. A `403` after manually issuing an API POST can indicate a missing CSRF token or mismatched origin.

Start without reload when debugging. If you add `--reload` during development and breakpoints behave unexpectedly, remove it. Keep one application process; do not expose the listener on `0.0.0.0` or put the demo behind a public proxy.

## Tests and CLI configurations

Select the same project interpreter for a pytest configuration, target `tests`, working directory at the root. Equivalent terminal checks are:

```bash
python -m pytest --cov=aspire_brain --cov-report=term-missing
python -m ruff check src tests
python -m aspire_brain.cli evaluate --offline
```

For CLI actions, a Python module configuration can run `aspire_brain.cli` with parameters such as `doctor` or `evaluate --offline`. A separate runtime directory can be selected using the global option before the command:

```bash
python -m aspire_brain.cli --root /private/tmp/aspire-demo-check init-demo
python -m aspire_brain.cli --root /private/tmp/aspire-demo-check doctor
```

For a server against another runtime root, use that root as its working directory after the package is installed. Templates/static assets resolve from the installed package; configuration and database paths resolve from the runtime root. Keep the source corpus available for imports.

`doctor` reports configuration/schema, FTS5, writable paths and provider mode without printing keys. Missing configuration requires `init-demo`. Incompatible schemas are rejected explicitly; preserve the original database and use a separate runtime root for experiments. If FTS5 is absent, the authorised lexical fallback is labelled. External inference modes remain unavailable in P0.
