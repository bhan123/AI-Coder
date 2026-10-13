"""Shared test fixtures.

Every test runs against the shipped ``ai-news`` pack unless it explicitly
loads another one. Installing it at import time keeps ``active_pack()`` valid
for the deep validation helpers that don't take a pack argument.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.pack import load_pack, set_active_pack

PACK_ROOT = Path(__file__).resolve().parents[2] / "packs" / "ai-news"

# Installed at import time, not just as a fixture: conftest is imported before
# test modules are collected, and some modules read the template registry in
# @parametrize decorators, which run during collection.
_PACK = load_pack(PACK_ROOT)
set_active_pack(_PACK)


@pytest.fixture(scope="session")
def pack():
    """The default content pack used across the suite."""
    return _PACK


@pytest.fixture(autouse=True)
def _install_pack():
    """Re-install the pack in case a test swapped it out."""
    set_active_pack(_PACK)
    return _PACK
