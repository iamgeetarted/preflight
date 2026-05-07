"""Async concurrent check executor using asyncio.TaskGroup."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from .config import CheckSpec


class Status(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass
class CheckResult:
    spec: CheckSpec
    status: Status = Status.PENDING
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    elapsed: float = 0.0
    error_msg: str = ""


async def _run_one(
    spec: CheckSpec,
    semaphore: asyncio.Semaphore,
    on_start: Callable[[CheckSpec], None],
    on_done: Callable[[CheckResult], None],
    stop_event: asyncio.Event,
) -> CheckResult:
    result = CheckResult(spec=spec)

    if not spec.enabled:
        result.status = Status.SKIPPED
        on_done(result)
        return result

    if stop_event.is_set():
        result.status = Status.SKIPPED
        on_done(result)
        return result

    async with semaphore:
        if stop_event.is_set():
            result.status = Status.SKIPPED
            on_done(result)
            return result

        on_start(spec)
        result.status = Status.RUNNING
        t0 = time.perf_counter()

        env = {**os.environ, **spec.env}

        try:
            proc = await asyncio.create_subprocess_shell(
                spec.run,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            try:
                raw_out, raw_err = await asyncio.wait_for(
                    proc.communicate(), timeout=spec.timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                result.elapsed = time.perf_counter() - t0
                result.status = Status.ERROR
                result.error_msg = f"Timed out after {spec.timeout}s"
                on_done(result)
                return result

            result.stdout = raw_out.decode(errors="replace").strip()
            result.stderr = raw_err.decode(errors="replace").strip()
            result.exit_code = proc.returncode
            result.elapsed = time.perf_counter() - t0

            # Evaluate pass/fail
            combined = result.stdout + "\n" + result.stderr
            exit_ok = result.exit_code == spec.expect_exit
            expect_ok = (not spec.expect) or (spec.expect in combined)

            if exit_ok and expect_ok:
                result.status = Status.PASSED
            else:
                result.status = Status.FAILED
                if not exit_ok:
                    result.error_msg = (
                        f"Exit {result.exit_code} (expected {spec.expect_exit})"
                    )
                elif not expect_ok:
                    result.error_msg = f"Expected string not found: {spec.expect!r}"

        except Exception as exc:
            result.elapsed = time.perf_counter() - t0
            result.status = Status.ERROR
            result.error_msg = str(exc)[:200]

    on_done(result)
    return result


async def run_checks(
    checks: list[CheckSpec],
    max_workers: int = 8,
    fail_fast: bool = False,
    on_start: Callable[[CheckSpec], None] | None = None,
    on_done: Callable[[CheckResult], None] | None = None,
) -> list[CheckResult]:
    """Run all checks concurrently; return results in original order."""
    semaphore = asyncio.Semaphore(max_workers)
    stop_event = asyncio.Event()

    _on_start = on_start or (lambda s: None)
    _on_done_user = on_done or (lambda r: None)

    def _on_done(result: CheckResult) -> None:
        _on_done_user(result)
        if fail_fast and result.status in (Status.FAILED, Status.ERROR):
            stop_event.set()

    results: list[CheckResult] = []

    async with asyncio.TaskGroup() as tg:
        tasks = [
            tg.create_task(
                _run_one(spec, semaphore, _on_start, _on_done, stop_event)
            )
            for spec in checks
        ]

    results = [t.result() for t in tasks]
    return results
