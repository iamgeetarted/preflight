# preflight

**Concurrent dev-environment health checks with a live Rich dashboard and AI failure analysis.**

`preflight` runs a configurable list of shell commands in parallel, shows real-time pass/fail status in a live terminal table, and — when something breaks — streams a Claude-powered diagnosis and fix straight to your terminal.

---

## Features

- **Full async concurrency** — all checks run simultaneously via `asyncio.TaskGroup` with a configurable concurrency cap
- **Live Rich dashboard** — spinner-animated status table that updates in real-time as checks complete; color-coded green/red/yellow
- **AI failure analysis** — when checks fail, streams `claude-haiku-4-5-20251001`'s concise root-cause + fix suggestion
- **Plugin/extension system** — register custom check types via `importlib.metadata` entry_points (`preflight.checks` group)
- **Tag filtering** — run only the checks you care about with `--tags lint,test`
- **TOML or YAML config** — `preflight.toml` (recommended) or `preflight.yaml`
- **Fail-fast mode** — `--fail-fast` cancels remaining checks once one fails

---

## Install

```bash
pip install preflight
# YAML config support:
pip install "preflight[yaml]"
```

Or from source:

```bash
git clone https://github.com/iamgeetarted/preflight.git
cd preflight && pip install -e ".[dev]"
```

**Requires Python 3.11+.**

---

## Quick Start

Create a `preflight.toml` in your project root:

```toml
[preflight]
max_workers = 8
fail_fast   = false
no_ai       = false

[[checks]]
name    = "Python version"
run     = "python --version"
expect  = "Python 3"
tags    = ["env"]

[[checks]]
name    = "Git status clean"
run     = "git diff --stat"
expect  = ""
tags    = ["git"]

[[checks]]
name    = "Dependencies installed"
run     = "pip check"
tags    = ["env"]

[[checks]]
name    = "Lint"
run     = "ruff check ."
tags    = ["lint"]

[[checks]]
name    = "Tests"
run     = "pytest tests/ -q"
timeout = 120
tags    = ["test"]

[[checks]]
name    = "Typecheck"
run     = "mypy src/"
timeout = 60
tags    = ["test"]
```

Then run:

```bash
preflight
```

---

## Sample Output

```
╭──────────────────────────── preflight ─────────────────────────────╮
│   Check                     Time    Details                         │
│  ✓  Python version          42ms    Python 3.12.2                   │
│  ✓  Git status clean        18ms                                    │
│  ✓  Dependencies installed  1.2s                                    │
│  ✗  Lint                    3.1s    Exit 1 (expected 0)             │
│  ✓  Tests                   8.4s                                    │
│  ◌  Typecheck               ...     mypy src/                       │
╰───────────────────────── 4/6  ✓ 4 passed  ✗ 1 failed ─────────────╯

─────────────────────────── Lint ────────────────────────────────────
Command: ruff check .
Reason: Exit 1 (expected 0)
  src/foo.py:12:5: E501 Line too long (92 > 88 characters)

✗ 1/6 checks failed  5 passed  (12.7s)

──────────────────────── AI Failure Analysis ────────────────────────
**Lint** — `ruff check .` exited with code 1, indicating a style violation.
Line 12 in `src/foo.py` exceeds the 88-character limit. Fix with:
  ruff check . --fix
or add `# noqa: E501` to suppress the specific line.
```

---

## Usage

```
preflight [options]
```

| Option | Description |
|---|---|
| `-c FILE` / `--config FILE` | Config file path (default: search for `preflight.toml` / `preflight.yaml`) |
| `--no-ai` | Skip AI analysis on failure |
| `--fail-fast` | Stop after first failure |
| `--workers N` | Override max concurrent checks |
| `--tags TAGS` | Comma-separated tag filter |
| `--list-plugins` | Show installed check-type plugins |
| `--version` | Show version and exit |

---

## Check Config Reference

```toml
[[checks]]
name        = "My check"       # required — display name
run         = "pytest ."       # required — shell command to execute
expect      = "passed"         # optional — substring required in output
expect_exit = 0                # optional — expected exit code (default: 0)
timeout     = 30.0             # optional — seconds before kill (default: 30)
tags        = ["test", "ci"]   # optional — for --tags filtering
enabled     = true             # optional — set false to skip without removing
[checks.env]                   # optional — extra env vars for this check
  MY_VAR = "value"
```

---

## Plugin System

You can add custom check types by exposing a `preflight.checks` entry_point in your package's `pyproject.toml`:

```toml
[project.entry_points."preflight.checks"]
http = "mypkg.checks:http_check_factory"
```

The factory receives the raw check dict and returns a `CheckSpec`. Preflight loads all installed plugins automatically at startup.

```python
# mypkg/checks.py
from preflight.config import CheckSpec

def http_check_factory(spec_dict: dict) -> CheckSpec:
    url = spec_dict.get("url", "http://localhost")
    return CheckSpec(
        name=spec_dict["name"],
        run=f"curl -sf {url}",
        expect_exit=0,
    )
```

List all installed plugins:

```bash
preflight --list-plugins
```

---

## Architecture

```
preflight/
├── cli.py       # argparse + asyncio.run() entry point, tag filtering
├── config.py    # TOML/YAML loader, CheckSpec dataclass
├── runner.py    # async executor: asyncio.TaskGroup + Semaphore, callbacks
├── display.py   # Rich Live dashboard, failure detail printer, summary
├── advisor.py   # Anthropic streaming API — AI failure diagnosis
└── plugins.py   # importlib.metadata entry_points plugin registry
```

**Breakthrough techniques used:**

| Technique | Where |
|---|---|
| Full async architecture (`asyncio.TaskGroup`) | `runner.py` — all checks run concurrently with structured cancellation |
| Live Rich UI (`Rich.Live` + `Layout`) | `display.py` — real-time spinner + status table |
| LLM integration (Anthropic streaming) | `advisor.py` — streamed failure diagnosis |
| Plugin/extension system (entry_points) | `plugins.py` — custom check types via `preflight.checks` group |

---

## Running Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

---

## License

MIT
