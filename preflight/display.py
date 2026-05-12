"""Live Rich terminal dashboard for preflight check results."""

from __future__ import annotations

import threading
from typing import Callable

from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .config import CheckSpec
from .runner import CheckResult, Status

console = Console(stderr=True, highlight=False)

_STATUS_STYLE: dict[Status, tuple[str, str]] = {
    Status.PENDING:  ("○", "dim"),
    Status.RUNNING:  ("◌", "bold cyan"),
    Status.PASSED:   ("✓", "bold green"),
    Status.FAILED:   ("✗", "bold red"),
    Status.ERROR:    ("!", "bold yellow"),
    Status.SKIPPED:  ("–", "dim"),
}

_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def _status_cell(status: Status, frame: int = 0) -> Text:
    icon, style = _STATUS_STYLE[status]
    if status == Status.RUNNING:
        icon = _SPINNER_FRAMES[frame % len(_SPINNER_FRAMES)]
    return Text(icon, style=style)


def _elapsed_str(secs: float) -> str:
    if secs < 0.001:
        return ""
    if secs < 1:
        return f"{secs * 1000:.0f}ms"
    return f"{secs:.1f}s"


class LiveDashboard:
    """Thread-safe Rich Live dashboard that updates as checks complete."""

    def __init__(self, checks: list[CheckSpec]) -> None:
        self._results: dict[str, CheckResult] = {
            c.name: CheckResult(spec=c, status=Status.PENDING) for c in checks
        }
        self._order = [c.name for c in checks]
        self._lock = threading.Lock()
        self._frame = 0
        self._live = Live(
            self._render(),
            console=console,
            refresh_per_second=10,
            transient=False,
        )

    def start(self) -> None:
        self._live.start()

    def stop(self) -> None:
        self._live.update(self._render())
        self._live.stop()

    def on_start(self, spec: CheckSpec) -> None:
        with self._lock:
            self._results[spec.name].status = Status.RUNNING
        self._live.update(self._render())

    def on_done(self, result: CheckResult) -> None:
        with self._lock:
            self._results[result.spec.name] = result
        self._live.update(self._render())

    def tick(self) -> None:
        """Advance spinner frame — call periodically from a timer thread."""
        self._frame += 1
        self._live.update(self._render())

    def _render(self) -> Panel:
        t = Table(
            box=box.SIMPLE,
            show_header=True,
            header_style="bold cyan",
            pad_edge=False,
            expand=True,
        )
        t.add_column("", width=2, no_wrap=True)
        t.add_column("Check", style="white")
        t.add_column("Time", justify="right", width=7, style="dim")
        t.add_column("Details", style="dim", ratio=1)

        passed = failed = running = pending = skipped = 0

        with self._lock:
            for name in self._order:
                r = self._results[name]
                icon = _status_cell(r.status, self._frame)

                detail = ""
                if r.status == Status.RUNNING:
                    detail = r.spec.run[:80]
                elif r.status == Status.PASSED:
                    out = (r.stdout or r.stderr)[:80].replace("\n", " ")
                    detail = out
                elif r.status in (Status.FAILED, Status.ERROR):
                    retry_tag = f" [dim](attempt {r.attempts})[/dim]" if r.attempts > 1 else ""
                    base = r.error_msg or (r.stderr or r.stdout)[:80].replace("\n", " ")
                    detail = base + retry_tag

                elapsed = _elapsed_str(r.elapsed)
                t.add_row(icon, name, elapsed, detail)

                if r.status == Status.PASSED:
                    passed += 1
                elif r.status in (Status.FAILED, Status.ERROR):
                    failed += 1
                elif r.status == Status.RUNNING:
                    running += 1
                elif r.status == Status.PENDING:
                    pending += 1
                elif r.status == Status.SKIPPED:
                    skipped += 1

        total = len(self._order)
        done = passed + failed + skipped
        summary_parts: list[str] = [f"[dim]{done}/{total}[/dim]"]
        if passed:
            summary_parts.append(f"[green]{passed} passed[/green]")
        if failed:
            summary_parts.append(f"[red]{failed} failed[/red]")
        if running:
            summary_parts.append(f"[cyan]{running} running[/cyan]")
        if pending:
            summary_parts.append(f"[dim]{pending} pending[/dim]")

        border = "red" if failed else ("green" if done == total else "cyan")
        return Panel(
            t,
            title="[bold]preflight[/bold]",
            subtitle="  ".join(summary_parts),
            border_style=border,
            box=box.ROUNDED,
        )


def print_failures(results: list[CheckResult]) -> None:
    """Print detailed stderr/stdout for each failed check."""
    failures = [r for r in results if r.status in (Status.FAILED, Status.ERROR)]
    if not failures:
        return

    from rich.rule import Rule
    from rich.syntax import Syntax

    console.print()
    for r in failures:
        console.print(Rule(f"[bold red]{r.spec.name}[/bold red]", style="red"))
        console.print(f"[dim]Command:[/dim] {r.spec.run}")
        if r.error_msg:
            console.print(f"[bold yellow]Reason:[/bold yellow] {r.error_msg}")
        combined = "\n".join(filter(None, [r.stdout, r.stderr]))
        if combined:
            console.print(
                Syntax(combined[:2000], "text", theme="ansi_dark", line_numbers=False)
            )
        console.print()


def print_summary(results: list[CheckResult], elapsed: float) -> int:
    """Print final pass/fail summary. Returns 0 if all passed, 1 otherwise."""
    passed = sum(1 for r in results if r.status == Status.PASSED)
    failed = sum(1 for r in results if r.status in (Status.FAILED, Status.ERROR))
    skipped = sum(1 for r in results if r.status == Status.SKIPPED)
    total = len(results)

    if failed == 0:
        console.print(
            f"\n[bold green]✓ All {passed} checks passed[/bold green]"
            f"  [dim]({elapsed:.1f}s)[/dim]"
        )
        return 0
    else:
        console.print(
            f"\n[bold red]✗ {failed}/{total} checks failed[/bold red]"
            f"  [green]{passed} passed[/green]"
            + (f"  [dim]{skipped} skipped[/dim]" if skipped else "")
            + f"  [dim]({elapsed:.1f}s)[/dim]"
        )
        return 1
