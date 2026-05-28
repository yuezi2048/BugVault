"""Pytest configuration — register custom markers and shared fixtures."""

from __future__ import annotations

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "e2e: marks end-to-end MCP protocol tests that start a real subprocess (slow).",
    )
