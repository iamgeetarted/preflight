"""Command-line interface for preflight."""

from __future__ import annotations

import argparse
import asyncio
import sys
import threading
import time
from pathlib import Path

from . import __version__
from .config import Config, load_config
from .runner import CheckResult, Status, run_checks
from .exporter import to_json, to_markdown as results_to_markdown


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="preflight",
        description="Concurrent dev-environment health checks with live Rich UI and AI analysis.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  preflight                          # run checks from preflight.toml in current dir
  preflight -c myconfig.toml        # use a specific config file
  preflight --no-ai                 # skip AI analysis on failure
  preflight --fail-fast             # stop after first failure
  preflight --workers 4             # limit concurrency
  preflight --tags lint,test        # run only checks with these tags
  preflight --list-plugins          # show installed check-type plugins
  preflight --retry 2               # retry each failed check up to 2 more times
  preflight --watch 60              # re-run all checks every 60 seconds
  preflight --format json           # output JSON report (CI-friendly)
  preflight --format markdown -o report.md  # save Markdown report

config (preflight.toml):
  [preflight]
  max_workers = 8
  fail_fast   = false
  no_ai       = false

  [[checks]]
  name = "Python version"
  run  = "python --version"
  expect = "Python 3"

  [[checks]]
  name = "Tests"
  run  = "pytest tests/ -q"
  timeout = 60
""",
    )
    p.add_argument(
        "-c", "--config",
        metavar="FILE",
        help="Config file path (default: search for preflight.toml / preflight.yaml)",
    )
    p.add_argument(
        "--no-ai",
        action="store_true",
        default=False,
        help="Skip AI analysis on failure",
    )
    p.add_argument(
        "--fail-fast",
        action="store_true",
        default=False,
        help="Stop after the first failure",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        metavar="N",
        help="Max concurrent checks (overrides config)",
    )
    p.add_argument(
        "--tags",
        metavar="TAGS",
        default=None,
        help="Comma-separated tag filter — only run checks matching any listed tag",
    )
    p.add_argument(
        "--list-plugins",
        action="store_true",
        help="Show installed preflight check-type plugins and exit",
    )
    p.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable Rich terminal colors",
    )
    p.add_argument(
        "--retry",
        type=int,
        default=0,
        metavar="N",
        help="Retry each failed/errored check up to N additional times (with exponential backoff)",
    )
    p.add_argument(
        "--watch",
        type=int,
        default=None,
        metavar="SECS",
        help="Re-run all checks every SECS seconds (continuous monitoring mode)",
    )
    p.add_argument(
        "--format",
        choices=["live", "json", "markdown"],
        default="live",
        help="Output format: live (Rich dashboard, default), json, or markdown",
    )
    p.add_argument(
        "--output",
        "-o",
        metavar="FILE",
        default=None,
        help="Write json/markdown output to FILE instead of stdout",
    )
    p.add_argument("--version", action="version", version=f"preflight {__version__}")
    return p


async def _run_once(
    cfg: Config,
    args: argparse.Namespace,
    iteration: int = 0,
) -> tuple[int, list[CheckResult], float]:
    """Execute one full pass of all checks. Returns (exit_code, results, elapsed)."""
    from .display import LiveDashboard, print_failures, print_summary
    from .advisor import stream_advice

    checks = [c for c in cfg.checks if c.enabled]

    if args.tags:
        wanted = {t.strip() for t in args.tags.split(",")}
        checks = [c for c in checks if not c.tags or bool(set(c.tags) & wanted)]

    if not checks:
        print("preflight: no checks to run (check your config or --tags filter).", file=sys.stderr)
        return 2, [], 0.0

    max_workers = args.workers if args.workers is not None else cfg.max_workers
    fail_fast = args.fail_fast or cfg.fail_fast
    no_ai = args.no_ai or cfg.no_ai
    global_retry = args.retry
    fmt = getattr(args, "format", "live")

    if fmt == "live":
        dashboard = LiveDashboard(checks)
        dashboard.start()

        _stop_tick = threading.Event()
        def _ticker():
            while not _stop_tick.is_set():
                dashboard.tick()
                time.sleep(0.1)
        tick_thread = threading.Thread(target=_ticker, daemon=True)
        tick_thread.start()

        t0 = time.perf_counter()
        try:
            results = await run_checks(
                checks,
                max_workers=max_workers,
                fail_fast=fail_fast,
                on_start=dashboard.on_start,
                on_done=dashboard.on_done,
                global_retry=global_retry,
            )
        finally:
            _stop_tick.set()
            tick_thread.join(timeout=0.5)
            dashboard.stop()

        elapsed = time.perf_counter() - t0
        failures = [r for r in results if r.status in (Status.FAILED, Status.ERROR)]
        print_failures(results)
        exit_code = print_summary(results, elapsed)

        if failures and not no_ai:
            stream_advice(failures, model=cfg.ai_model)
    else:
        # Non-interactive: run silently, then emit structured output
        t0 = time.perf_counter()
        results = await run_checks(
            checks,
            max_workers=max_workers,
            fail_fast=fail_fast,
            global_retry=global_retry,
        )
        elapsed = time.perf_counter() - t0
        failures = [r for r in results if r.status in (Status.FAILED, Status.ERROR)]
        exit_code = 1 if failures else 0

    return exit_code, results, elapsed


async def _run(cfg: Config, args: argparse.Namespace) -> int:
    fmt = getattr(args, "format", "live")
    watch_secs = getattr(args, "watch", None)

    if watch_secs and fmt == "live":
        iteration = 0
        while True:
            code, _results, elapsed = await _run_once(cfg, args, iteration)
            wait = max(0.0, watch_secs - elapsed)
            from .display import console as _con
            _con.print(
                f"[dim]  ↻ watch mode — refreshing in {watch_secs}s "
                f"(Ctrl-C to stop)[/dim]"
            )
            try:
                await asyncio.sleep(wait)
            except asyncio.CancelledError:
                break
            iteration += 1
        return 0

    code, results, elapsed = await _run_once(cfg, args)

    if fmt == "json":
        text = to_json(results, elapsed)
        _write_output(text, getattr(args, "output", None))
    elif fmt == "markdown":
        text = results_to_markdown(results, elapsed)
        _write_output(text, getattr(args, "output", None))

    return code


def _write_output(text: str, path: str | None) -> None:
    if path:
        Path(path).write_text(text, encoding="utf-8")
        print(f"Output written to {path}", file=sys.stderr)
    else:
        print(text, end="")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.list_plugins:
        from .plugins import load_entry_points, list_plugins
        load_entry_points()
        plugins = list_plugins()
        if plugins:
            print("Installed preflight check-type plugins:")
            for name in plugins:
                print(f"  {name}")
        else:
            print("No check-type plugins installed.")
            print("Create one by exposing a 'preflight.checks' entry_point in your package.")
        return 0

    config_path = Path(args.config) if args.config else None

    try:
        cfg = load_config(config_path)
    except FileNotFoundError as e:
        print(f"preflight: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"preflight: config error: {e}", file=sys.stderr)
        return 2
    except ImportError as e:
        print(f"preflight: {e}", file=sys.stderr)
        return 2

    try:
        return asyncio.run(_run(cfg, args))
    except KeyboardInterrupt:
        return 0


def entry_point() -> None:
    sys.exit(main())
