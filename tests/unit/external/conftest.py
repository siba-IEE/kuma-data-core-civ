"""Fixtures pytest partagees pour les tests unitaires `tests/unit/external/`.

Patch ``time.sleep`` en no-op via ``monkeypatch`` autouse pour neutraliser
les backoffs reels du retry transverse de ``external.nasa_power``
(``RETRY_BACKOFF_SECONDES = (1.0, 4.0, 16.0)``). Les tests qui declenchent
les boucles retry (429, 503, TimeoutException) restent corrects sur le
fond mais s'executent immediatement au lieu d'attendre 1+4+16 = 21 s
par cas d'epuisement.

Couvre transparently les tests existants ``test_nasa_power.py`` (cas
429 et timeout) et les tests futurs susceptibles de declencher les
boucles retry sur cette arborescence.

Le module ``test_nasa_power_retry.py`` continue d'utiliser son
parametre ``retry_backoff_seconds=(0.0, 0.0, 0.0)`` pour controle
explicite ; la presente fixture est neutralisante (no-op) et donc
compatible.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _neutraliser_time_sleep(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Remplace ``time.sleep`` par un no-op pour acceleration des tests retry.

    Cible le module ``external._http_retry`` ou ``time.sleep`` est
    effectivement appele par ``executer_get_avec_retry`` (apres
    extraction du helper).
    """
    monkeypatch.setattr(
        "kuma_data_core.external._http_retry.time.sleep",
        lambda _seconds: None,
    )
    yield
