"""Fixtures pytest partagees pour les tests unitaires `tests/unit/ingestion/`.

Patch ``time.sleep`` via ``monkeypatch`` autouse pour neutraliser les
backoffs reels du retry transverse (``RETRY_BACKOFF_SECONDES = (1.0,
4.0, 16.0)``). Coherent avec ``tests/unit/external/conftest.py``.

Cible le module ``external._http_retry`` (source canonique du
``time.sleep`` apres extraction du helper).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _neutraliser_time_sleep(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Remplace ``time.sleep`` par un no-op pour acceleration des tests retry."""
    monkeypatch.setattr(
        "kuma_data_core.external._http_retry.time.sleep",
        lambda _seconds: None,
    )
    yield
