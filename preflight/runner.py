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
    attempts: int = 1


async def _run_single_attempt(
    spec: CheckSpec,
    env: dict[str, str],
) -> CheckResult:
    """Execute one attempt of a check; does NOT update callbacks or manage semaphore."""
    result = CheckResult(spec=spec, status=Status.RUNNING)
    t0 = time.perf_counter()
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
            return result

        result.stdout = raw_out.decode(errors="replace").strip()
        result.stderr = raw_err.decode(errors="replace").strip()
        result.exit_code = proc.returncode
        result.elapsed = time.perf_counter() - t0

        combined = result.stdout + "\n" + result.stderr
        exit_ok = result.exit_code == spec.expect_exit
        expect_ok = (not spec.expect) or (spec.expect in combined)

        if exit_ok and expect_ok:
            result.status = Status.PASSED
        else:
            result.status = Status.FAILED
            if not exit_ok:
                result.error_msg = f"Exit {result.exit_code} (expected {spec.expect_exit})"
            elif not expect_ok:
                result.error_msg = f"Expected string not found: {spec.expect!r}"

    except Exception as exc:
        result.elapsed = time.perf_counter() - t0
        result.status = Status.ERROR
        result.error_msg = str(exc)[:200]

    return result


async def _run_one(
    spec: CheckSpec,
    semaphore: asyncio.Semaphore,
    on_start: Callable[[CheckSpec], None],
    on_done: Callable[[CheckResult], None],
    stop_event: asyncio.Event,
    global_retry: int = 0,
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
        env = {**os.environ, **spec.env}
        max_attempts = 1 + max(spec.retry, global_retry)

        for attempt in range(1, max_attempts + 1):
            result = await _run_single_attempt(spec, env)
            result.attempts = attempt
            if result.status == Status.PASSED or stop_event.is_set():
                break
            if attempt < max_attempts:
                await asyncio.sleep(min(2 ** (attempt - 1), 8))  # backoff: 1s, 2s, 4s, 8s

    on_done(result)
    return result


async def run_checks(
    checks: list[CheckSpec],
    max_workers: int = 8,
    fail_fast: bool = False,
    on_start: Callable[[CheckSpec], None] | None = None,
    on_done: Callable[[CheckResult], None] | None = None,
    global_retry: int = 0,
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

    async with asyncio.TaskGroup() as tg:
        tasks = [
            tg.create_task(
                _run_one(spec, semaphore, _on_start, _on_done, stop_event, global_retry)
            )
            for spec in checks
        ]

    return [t.result() for t in tasks]
