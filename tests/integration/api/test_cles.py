"""Tests d'intégration des endpoints ``/v1/cles`` (ADR-0003, D3 / WP6).

Couvre les deux régimes :

- **Régime local** (``META_DB`` absente) : l'émission renvoie 404
  ``CLES_EMISSION_NON_ACTIVEE``.
- **Régime serveur** (fixture qui pointe la base de service vers la
  base de test et crée ``cles_api`` via ``BaseMeta``) : émission 201,
  la clé émise authentifie réellement un endpoint privé, limite par IP
  en 429, révocation admin (la clé cesse de fonctionner), révocation
  refusée aux non-admin.

La fixture utilise le modèle réel (``BaseMeta.metadata.create_all``) :
le DDL testé est celui que ``python -m kuma_data_core.db.meta``
provisionne sur le serveur.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from kuma_data_core.api.codes_erreur import CodeErreur
from kuma_data_core.core.config import get_settings
from kuma_data_core.db.meta import BaseMeta
from kuma_data_core.db.session import get_engine, get_engine_meta

pytestmark = pytest.mark.integration


@pytest.fixture
def base_service_active(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Active le régime serveur : base de service = base de test."""
    settings = get_settings()
    monkeypatch.setattr(settings, "meta_db", settings.postgres_db)
    BaseMeta.metadata.create_all(get_engine_meta())
    yield
    with get_engine().begin() as connexion:
        connexion.execute(text("DROP TABLE IF EXISTS cles_api"))


def _emettre(client: TestClient, email: str = "dev@exemple.org") -> dict[str, object]:
    r = client.post("/v1/cles", json={"email": email, "usage_prevu": "tests"})
    assert r.status_code == 201, r.text
    return r.json()


def test_emission_sans_base_de_service_renvoie_404(client: TestClient) -> None:
    """Régime local : le self-service est une capacité du serveur public."""
    r = client.post("/v1/cles", json={"email": "dev@exemple.org"})
    assert r.status_code == 404
    assert r.json()["erreur"]["code"] == CodeErreur.CLES_EMISSION_NON_ACTIVEE.value


def test_emission_et_authentification_de_bout_en_bout(
    client: TestClient, base_service_active: None
) -> None:
    """La clé émise ouvre réellement un endpoint privé."""
    payload = _emettre(client)
    cle = str(payload["cle"])
    assert cle.startswith("kuma_")
    assert str(payload["prefixe"]) == cle[:13]
    assert int(str(payload["quota_journalier"])) > 0

    r = client.get("/v1/localites", headers={"Authorization": f"Bearer {cle}"})
    assert r.status_code == 200


def test_email_invalide_rejete(client: TestClient, base_service_active: None) -> None:
    r = client.post("/v1/cles", json={"email": "pas-un-email"})
    assert r.status_code == 422


def test_limite_emission_par_ip(client: TestClient, base_service_active: None) -> None:
    """Au-delà de la limite 24 h, l'émission répond 429."""
    for _ in range(3):
        _emettre(client)
    r = client.post("/v1/cles", json={"email": "dev@exemple.org"})
    assert r.status_code == 429
    assert r.json()["erreur"]["code"] == CodeErreur.CLES_LIMITE_EMISSION_ATTEINTE.value


def test_revocation_admin_coupe_la_cle(
    client: TestClient, base_service_active: None, cle_admin_valide: str
) -> None:
    payload = _emettre(client)
    cle, prefixe = str(payload["cle"]), str(payload["prefixe"])

    r = client.delete(
        f"/v1/cles/{prefixe}", headers={"Authorization": f"Bearer {cle_admin_valide}"}
    )
    assert r.status_code == 200
    assert r.json()["cles_revoquees"] == 1

    r = client.get("/v1/localites", headers={"Authorization": f"Bearer {cle}"})
    assert r.status_code == 401


def test_revocation_refusee_aux_non_admin(
    client: TestClient, base_service_active: None, cle_solar_valide: str
) -> None:
    payload = _emettre(client)
    r = client.delete(
        f"/v1/cles/{payload['prefixe']}",
        headers={"Authorization": f"Bearer {cle_solar_valide}"},
    )
    assert r.status_code == 401


def test_revocation_prefixe_inconnu_renvoie_404(
    client: TestClient, base_service_active: None, cle_admin_valide: str
) -> None:
    r = client.delete(
        "/v1/cles/kuma_inconnu1", headers={"Authorization": f"Bearer {cle_admin_valide}"}
    )
    assert r.status_code == 404


class _FauxRedis:
    """Compteur en mémoire, interface minimale incr/expire (WP7)."""

    def __init__(self) -> None:
        self.valeurs: dict[str, int] = {}

    def incr(self, cle: str) -> int:
        self.valeurs[cle] = self.valeurs.get(cle, 0) + 1
        return self.valeurs[cle]

    def expire(self, cle: str, secondes: int) -> None:  # pragma: no cover - trivial
        pass


def test_quota_journalier_applique_de_bout_en_bout(
    client: TestClient,
    base_service_active: None,
    monkeypatch: pytest.MonkeyPatch,
    headers_auth: dict[str, str],
) -> None:
    """WP7 : au-delà du quota de la clé, 429 CLES_QUOTA_JOURNALIER_DEPASSE.

    Rate limiting activé + compteur Redis remplacé par un compteur en
    mémoire (le chemin HTTP complet reste réel) ; quota réduit à 2 en
    base. Les clés d'environnement ne sont jamais limitées.
    """
    from kuma_data_core.services import quotas

    payload = _emettre(client)
    cle = str(payload["cle"])

    monkeypatch.setattr(get_settings(), "rate_limiting_actif", True)
    faux = _FauxRedis()
    monkeypatch.setattr(quotas, "obtenir_client", lambda: faux)
    with get_engine_meta().begin() as connexion:
        connexion.execute(text("UPDATE cles_api SET quota_journalier = 2"))

    entetes = {"Authorization": f"Bearer {cle}"}
    assert client.get("/v1/localites", headers=entetes).status_code == 200
    assert client.get("/v1/localites", headers=entetes).status_code == 200
    r = client.get("/v1/localites", headers=entetes)
    assert r.status_code == 429
    assert r.json()["erreur"]["code"] == CodeErreur.CLES_QUOTA_JOURNALIER_DEPASSE.value

    # Clé d'environnement (Bridge) : jamais comptée ni limitée.
    assert client.get("/v1/localites", headers=headers_auth).status_code == 200
