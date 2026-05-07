"""Plugin registry — load custom check types from importlib.metadata entry_points."""

from __future__ import annotations

from typing import Callable

# Registry: check-type-name → callable(spec_dict) -> CheckSpec
_REGISTRY: dict[str, Callable] = {}


def register(name: str, factory: Callable) -> None:
    """Register a custom check factory under the given type name."""
    _REGISTRY[name] = factory


def get(name: str) -> Callable | None:
    """Return the factory for a check type, or None if not registered."""
    return _REGISTRY.get(name)


def load_entry_points() -> None:
    """Discover and load all preflight check plugins via entry_points."""
    try:
        from importlib.metadata import entry_points
    except ImportError:
        return

    eps = entry_points(group="preflight.checks")
    for ep in eps:
        try:
            factory = ep.load()
            register(ep.name, factory)
        except Exception:
            pass  # Skip broken plugins silently


def list_plugins() -> list[str]:
    """Return names of all registered check-type plugins."""
    return list(_REGISTRY.keys())
