"""Export preflight results to JSON or Markdown."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runner import CheckResult


def to_json(results: list[CheckResult], elapsed: float) -> str:
    """Serialize check results to a JSON string."""
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_elapsed_s": round(elapsed, 3),
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r.status.value == "passed"),
            "failed": sum(1 for r in results if r.status.value in ("failed", "error")),
            "skipped": sum(1 for r in results if r.status.value == "skipped"),
        },
        "checks": [
            {
                "name": r.spec.name,
                "status": r.status.value,
                "elapsed_s": round(r.elapsed, 3),
                "attempts": r.attempts,
                "exit_code": r.exit_code,
                "error": r.error_msg or None,
                "stdout": r.stdout[:500] if r.stdout else None,
                "stderr": r.stderr[:500] if r.stderr else None,
                "tags": r.spec.tags,
            }
            for r in results
        ],
    }
    return json.dumps(data, indent=2)


def to_markdown(results: list[CheckResult], elapsed: float) -> str:
    """Render check results as a Markdown CI report."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    passed = sum(1 for r in results if r.status.value == "passed")
    failed = sum(1 for r in results if r.status.value in ("failed", "error"))
    skipped = sum(1 for r in results if r.status.value == "skipped")
    total = len(results)

    badge = "✅ All checks passed" if failed == 0 else f"❌ {failed}/{total} checks failed"

    lines = [
        f"# preflight report",
        f"",
        f"_{now}_",
        f"",
        f"## {badge}",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total | {total} |",
        f"| Passed | {passed} |",
        f"| Failed | {failed} |",
        f"| Skipped | {skipped} |",
        f"| Elapsed | {elapsed:.1f}s |",
        f"",
        f"## Results",
        f"",
        f"| Check | Status | Time | Attempts | Details |",
        f"|-------|--------|-----:|--------:|---------|",
    ]

    icon_map = {
        "passed": "✅",
        "failed": "❌",
        "error": "⚠️",
        "skipped": "⏭️",
        "pending": "⏳",
        "running": "🔄",
    }

    for r in results:
        icon = icon_map.get(r.status.value, "?")
        detail = (r.error_msg or (r.stdout or r.stderr)[:80].replace("\n", " "))[:80]
        detail = detail.replace("|", "\\|")
        attempts_str = str(r.attempts) if r.attempts > 1 else "1"
        lines.append(
            f"| {r.spec.name} | {icon} {r.status.value} | {r.elapsed:.2f}s"
            f" | {attempts_str} | {detail} |"
        )

    failures = [r for r in results if r.status.value in ("failed", "error")]
    if failures:
        lines += ["", "## Failure Details", ""]
        for r in failures:
            lines.append(f"### {r.spec.name}")
            lines.append(f"")
            lines.append(f"**Command:** `{r.spec.run}`")
            if r.error_msg:
                lines.append(f"**Reason:** {r.error_msg}")
            combined = "\n".join(filter(None, [r.stdout, r.stderr]))
            if combined:
                lines.append(f"")
                lines.append(f"```")
                lines.append(combined[:1000])
                lines.append(f"```")
            lines.append(f"")

    return "\n".join(lines) + "\n"
