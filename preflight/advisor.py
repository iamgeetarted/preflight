"""Stream AI-powered failure analysis via the Anthropic API."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runner import CheckResult


def _build_prompt(failures: list[CheckResult]) -> str:
    lines = [
        f"The following {len(failures)} dev-environment check(s) failed. "
        "Give a concise, actionable diagnosis for each one.\n"
    ]
    for r in failures:
        lines.append(f"### Check: {r.spec.name}")
        lines.append(f"Command: `{r.spec.run}`")
        if r.error_msg:
            lines.append(f"Error: {r.error_msg}")
        combined = "\n".join(filter(None, [r.stdout, r.stderr]))
        if combined:
            lines.append(f"Output (truncated):\n```\n{combined[:800]}\n```")
        lines.append("")

    lines += [
        "For each failed check, provide ONE short paragraph:",
        "1. Most likely root cause",
        "2. Exact fix command or action",
        "Keep it technical, brief, and actionable. No fluff.",
    ]
    return "\n".join(lines)


def stream_advice(
    failures: list[CheckResult],
    model: str = "claude-haiku-4-5-20251001",
) -> None:
    """Stream Claude's diagnosis of failed checks to stdout."""
    try:
        import anthropic
    except ImportError:
        print("\n[!] pip install anthropic  # required for AI analysis\n")
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("\n[!] Set ANTHROPIC_API_KEY to enable AI failure analysis.\n")
        return

    if not failures:
        return

    try:
        from rich.console import Console
        from rich.rule import Rule
        c = Console(stderr=True)
        c.print()
        c.print(Rule("[bold cyan]AI Failure Analysis[/bold cyan]"))
    except ImportError:
        print("\n--- AI Failure Analysis ---")

    client = anthropic.Anthropic(api_key=api_key)
    prompt = _build_prompt(failures)

    with client.messages.stream(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
    print()
