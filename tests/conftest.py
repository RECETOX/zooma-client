"""Shared test fixtures. No test talks to the network: all HTTP traffic is
mocked with ``responses``, and payloads come from the captured live
responses in ``tests/fixtures``."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture() -> Callable[[str], object]:
    """Load a captured live payload from tests/fixtures by file name."""

    def load(name: str) -> object:
        with open(FIXTURES_DIR / name, encoding="utf-8") as handle:
            return json.load(handle)

    return load


@pytest.fixture
def read_fixture() -> Callable[[str], str]:
    """Read a captured live payload as text (for non-JSON fixtures)."""

    def read(name: str) -> str:
        return (FIXTURES_DIR / name).read_text(encoding="utf-8")

    return read


@pytest.fixture
def messages() -> tuple[list[str], Callable[[str], None]]:
    """A sink that collects messages, plus the messages it collected."""
    collected: list[str] = []
    return collected, collected.append
