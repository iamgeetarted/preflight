"""Tests for config loading."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from preflight.config import Config, CheckSpec, load_config


def _write_toml(tmp: Path, content: str) -> Path:
    p = tmp / "preflight.toml"
    p.write_text(content, encoding="utf-8")
    return p


def test_load_basic_toml(tmp_path):
    cfg_path = _write_toml(tmp_path, """
[[checks]]
name = "echo"
run  = "echo hello"
expect = "hello"
timeout = 5.0
""")
    cfg = load_config(cfg_path)
    assert len(cfg.checks) == 1
    assert cfg.checks[0].name == "echo"
    assert cfg.checks[0].run == "echo hello"
    assert cfg.checks[0].expect == "hello"
    assert cfg.checks[0].timeout == 5.0


def test_load_multiple_checks(tmp_path):
    cfg_path = _write_toml(tmp_path, """
[[checks]]
name = "a"
run = "echo a"

[[checks]]
name = "b"
run = "echo b"
""")
    cfg = load_config(cfg_path)
    assert len(cfg.checks) == 2
    names = [c.name for c in cfg.checks]
    assert "a" in names and "b" in names


def test_load_preflight_section(tmp_path):
    cfg_path = _write_toml(tmp_path, """
[preflight]
max_workers = 4
fail_fast = true

[[checks]]
name = "x"
run = "echo x"
""")
    cfg = load_config(cfg_path)
    assert cfg.max_workers == 4
    assert cfg.fail_fast is True


def test_check_defaults(tmp_path):
    cfg_path = _write_toml(tmp_path, """
[[checks]]
name = "minimal"
run  = "echo"
""")
    cfg = load_config(cfg_path)
    spec = cfg.checks[0]
    assert spec.expect == ""
    assert spec.expect_exit == 0
    assert spec.timeout == 30.0
    assert spec.enabled is True
    assert spec.tags == []


def test_not_found_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nonexistent.toml")


def test_empty_checks_raises(tmp_path):
    cfg_path = _write_toml(tmp_path, "[preflight]\n")
    with pytest.raises(ValueError):
        load_config(cfg_path)
