"""Storage contract tests run on SQLite and do not start Postgres."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def postgres_server():
    yield ""
