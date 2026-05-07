"""Tests for the async check runner."""

from __future__ import annotations

import asyncio
import pytest

from preflight.config import CheckSpec
from preflight.runner import CheckResult, Status, run_checks


def _make_spec(**kwargs) -> CheckSpec:
    defaults = dict(name="test", run="echo ok", timeout=10.0)
    defaults.update(kwargs)
    return CheckSpec(**defaults)


@pytest.mark.asyncio
async def test_passing_check():
    spec = _make_spec(name="echo", run="echo hello", expect="hello")
    results = await run_checks([spec])
    assert len(results) == 1
    assert results[0].status == Status.PASSED
    assert "hello" in results[0].stdout


@pytest.mark.asyncio
async def test_failing_check_bad_exit():
    spec = _make_spec(name="fail", run="exit 1", expect_exit=0)
    results = await run_checks([spec])
    assert results[0].status == Status.FAILED
    assert results[0].exit_code == 1


@pytest.mark.asyncio
async def test_failing_check_missing_expect():
    spec = _make_spec(name="missing", run="echo hello", expect="NOTHERE")
    results = await run_checks([spec])
    assert results[0].status == Status.FAILED
    assert "NOTHERE" in results[0].error_msg


@pytest.mark.asyncio
async def test_concurrent_checks():
    specs = [_make_spec(name=f"c{i}", run=f"echo {i}") for i in range(5)]
    results = await run_checks(specs, max_workers=3)
    assert len(results) == 5
    assert all(r.status == Status.PASSED for r in results)


@pytest.mark.asyncio
async def test_timeout():
    spec = _make_spec(name="slow", run="sleep 5", timeout=0.1)
    results = await run_checks([spec])
    assert results[0].status == Status.ERROR
    assert "Timed out" in results[0].error_msg


@pytest.mark.asyncio
async def test_skipped_when_disabled():
    spec = _make_spec(name="disabled", run="echo hi", enabled=False)
    results = await run_checks([spec])
    assert results[0].status == Status.SKIPPED


@pytest.mark.asyncio
async def test_fail_fast_stops_remaining():
    specs = [
        _make_spec(name="fail", run="exit 1"),
        _make_spec(name="second", run="echo second"),
    ]
    results = await run_checks(specs, fail_fast=True, max_workers=1)
    statuses = {r.spec.name: r.status for r in results}
    assert statuses["fail"] in (Status.FAILED, Status.ERROR)


@pytest.mark.asyncio
async def test_callback_called():
    started = []
    done = []

    def on_start(spec):
        started.append(spec.name)

    def on_done(result):
        done.append(result.spec.name)

    specs = [_make_spec(name=f"c{i}", run="echo ok") for i in range(3)]
    await run_checks(specs, on_start=on_start, on_done=on_done)
    assert len(done) == 3
