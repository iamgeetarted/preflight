"""Tests for the plugin registry."""

from __future__ import annotations

from preflight.plugins import register, get, list_plugins, load_entry_points


def test_register_and_get():
    def my_factory(spec_dict):
        return spec_dict

    register("my_type", my_factory)
    assert get("my_type") is my_factory


def test_get_missing_returns_none():
    assert get("nonexistent_type_xyz") is None


def test_list_plugins_includes_registered():
    register("plugin_a", lambda d: d)
    register("plugin_b", lambda d: d)
    plugins = list_plugins()
    assert "plugin_a" in plugins
    assert "plugin_b" in plugins


def test_load_entry_points_no_crash():
    # Should not raise even if no entry_points installed
    load_entry_points()
    # Registry is still accessible
    assert isinstance(list_plugins(), list)


def test_register_overwrites():
    factory1 = lambda d: "first"
    factory2 = lambda d: "second"
    register("overwrite_test", factory1)
    register("overwrite_test", factory2)
    assert get("overwrite_test") is factory2
