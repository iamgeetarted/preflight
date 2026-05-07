"""Load and validate preflight check configuration from YAML or pyproject.toml."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CheckSpec:
    name: str
    run: str
    expect: str = ""           # substring that must appear in stdout/stderr
    expect_exit: int = 0       # expected exit code
    timeout: float = 30.0      # seconds
    tags: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True


@dataclass
class Config:
    checks: list[CheckSpec]
    max_workers: int = 8
    fail_fast: bool = False
    no_ai: bool = False
    ai_model: str = "claude-haiku-4-5-20251001"


def _parse_check(raw: dict[str, Any]) -> CheckSpec:
    return CheckSpec(
        name=raw["name"],
        run=raw["run"],
        expect=raw.get("expect", ""),
        expect_exit=int(raw.get("expect_exit", 0)),
        timeout=float(raw.get("timeout", 30.0)),
        tags=list(raw.get("tags", [])),
        env={str(k): str(v) for k, v in raw.get("env", {}).items()},
        enabled=bool(raw.get("enabled", True)),
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        import tomllib  # type: ignore

    try:
        import yaml  # type: ignore
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except ImportError:
        pass

    # Minimal YAML-subset parser: handle simple key-value and list-of-dicts
    # Falls back to toml if available, otherwise errors gracefully
    if path.suffix in (".toml",):
        with open(path, "rb") as f:
            return tomllib.load(f)

    raise ImportError(
        "PyYAML is required to read .yaml/.yml config files: pip install pyyaml"
    )


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore
        except ImportError:
            raise ImportError("Python 3.11+ required, or install tomli: pip install tomli")
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_config(path: Path | None = None) -> Config:
    """Load config from file; search upward from cwd if path is None."""
    search_names = [
        "preflight.toml",
        ".preflight.toml",
        "preflight.yaml",
        ".preflight.yaml",
    ]

    if path is None:
        cwd = Path.cwd()
        for name in search_names:
            candidate = cwd / name
            if candidate.exists():
                path = candidate
                break

    if path is None:
        raise FileNotFoundError(
            "No preflight config found. Create preflight.toml or preflight.yaml.\n"
            "See: https://github.com/iamgeetarted/preflight"
        )

    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        data = _load_yaml(path)
    else:
        data = _load_toml(path)

    raw_checks = data.get("checks", [])
    if not raw_checks:
        raise ValueError(f"No checks defined in {path}")

    checks = [_parse_check(c) for c in raw_checks]
    meta = data.get("preflight", {})

    return Config(
        checks=checks,
        max_workers=int(meta.get("max_workers", 8)),
        fail_fast=bool(meta.get("fail_fast", False)),
        no_ai=bool(meta.get("no_ai", False)),
        ai_model=str(meta.get("ai_model", "claude-haiku-4-5-20251001")),
    )
