"""Shared fixtures for the Finoks backend tests.

Tests run against a throwaway SQLite file and never call external services:
no Anthropic, Specter or email credentials are set, so every client falls
back to its offline stub.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# Must be set before database.py / auth.py are imported.
os.environ.setdefault("JWT_SECRET", "test-secret")
for key in ("ANTHROPIC_API_KEY", "SPECTER_API_KEY", "SPECTER_API_URL", "EMAIL_PROVIDER", "RESEND_API_KEY"):
    os.environ.pop(key, None)


@pytest.fixture(autouse=True)
def reset_agent_config():
    """Each test starts from the default autonomy config."""
    import agent

    snapshot = dict(agent.autonomy_config)
    yield
    agent.autonomy_config.clear()
    agent.autonomy_config.update(snapshot)
