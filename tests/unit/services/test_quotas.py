"""Tests unitaires du compteur de quota Redis (ADR-0003, WP7).

Tests sans Redis réel (client factice injecté). Couvrent :

1. Comptage : dans le quota tant que le compte du jour <= quota, refus
   au-delà.
2. Expiration : posée au premier incrément seulement (nettoyage).
3. Fail-open : un Redis injoignable laisse passer (la disponibilité
   des données publiques prime sur la comptabilité du compteur).
4. Le compteur est indexé sur l'empreinte, pas la clé en clair.
"""

from __future__ import annotations

import pytest

from kuma_data_core.services import quotas


class FauxRedis:
    """Client factice : incr/expire en mémoire, interface minimale."""

    def __init__(self) -> None:
        self.valeurs: dict[str, int] = {}
        self.expirations: dict[str, int] = {}

    def incr(self, cle: str) -> int:
        self.valeurs[cle] = self.valeurs.get(cle, 0) + 1
        return self.valeurs[cle]

    def expire(self, cle: str, secondes: int) -> None:
        self.expirations[cle] = secondes


pytestmark = pytest.mark.unit


@pytest.fixture
def faux_redis(monkeypatch: pytest.MonkeyPatch) -> FauxRedis:
    faux = FauxRedis()
    monkeypatch.setattr(quotas, "obtenir_client", lambda: faux)
    return faux


def test_dans_le_quota_puis_refus(faux_redis: FauxRedis) -> None:
    assert quotas.consommer_quota("empreinte_test", quota_journalier=2) is True
    assert quotas.consommer_quota("empreinte_test", quota_journalier=2) is True
    assert quotas.consommer_quota("empreinte_test", quota_journalier=2) is False


def test_expiration_posee_au_premier_increment_seulement(faux_redis: FauxRedis) -> None:
    quotas.consommer_quota("empreinte_test", quota_journalier=10)
    assert len(faux_redis.expirations) == 1
    quotas.consommer_quota("empreinte_test", quota_journalier=10)
    assert len(faux_redis.expirations) == 1


def test_compteur_indexe_sur_l_empreinte(faux_redis: FauxRedis) -> None:
    quotas.consommer_quota("empreinte_a", quota_journalier=10)
    (cle_compteur,) = faux_redis.valeurs.keys()
    assert "empreinte_a" in cle_compteur
    assert cle_compteur.startswith("quota:")


def test_fail_open_si_redis_injoignable(monkeypatch: pytest.MonkeyPatch) -> None:
    def _leve() -> FauxRedis:
        raise ConnectionError("redis injoignable")

    monkeypatch.setattr(quotas, "obtenir_client", _leve)
    assert quotas.consommer_quota("empreinte_test", quota_journalier=1) is True
    assert quotas.consommer_quota("empreinte_test", quota_journalier=1) is True
