"""Tests unitaires de la configuration d'édition publique (ADR-0003, WP4).

Tests sans DB, sur ``Settings`` directement. Couvrent :

1. Défauts : ``edition_db`` absent (la référence est servie),
   ``edition_figee`` désactivé - le comportement local/dev est inchangé
   par le chantier édition.
2. Repointage D1 : ``edition_db`` défini prime sur ``postgres_db`` dans
   ``database_url``.
3. QO-3 tranchée : ``api_environnement`` accepte ``integration`` (doc
   de référence §health) et refuse l'ancien ``staging``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kuma_data_core.core.config import Settings

pytestmark = pytest.mark.unit


def test_defauts_edition_inchanges_en_local() -> None:
    s = Settings(postgres_password="mdp")
    assert s.edition_db is None
    assert s.edition_figee is False


def test_database_url_sans_edition_db_sert_la_reference() -> None:
    s = Settings(postgres_password="mdp")
    assert s.database_url.endswith(f"/{s.postgres_db}")


def test_database_url_avec_edition_db_prime_sur_la_reference() -> None:
    s = Settings(postgres_password="mdp", edition_db="kuma_edition_20260702_abcdef123456")
    assert s.database_url.endswith("/kuma_edition_20260702_abcdef123456")
    assert s.postgres_db not in s.database_url.rsplit("/", 1)[1]


def test_api_environnement_accepte_integration() -> None:
    s = Settings(postgres_password="mdp", api_environnement="integration")
    assert s.api_environnement == "integration"


def test_api_environnement_refuse_staging() -> None:
    """QO-3 : l'ancienne valeur ``staging`` (jamais documentée) est rejetée."""
    with pytest.raises(ValidationError):
        Settings(postgres_password="mdp", api_environnement="staging")  # type: ignore[arg-type]


def test_prod_refuse_cle_admin_vide() -> None:
    """Durcissement sécurité : une clé admin vide en prod bloque le démarrage.

    Sans cette garde, ``API_CLE_ADMIN=""`` passe ``is None`` mais rendrait
    un Bearer vide administrateur.
    """
    with pytest.raises(ValidationError):
        Settings(
            postgres_password="mdp",
            api_environnement="prod",
            api_docs_actives=False,
            log_format="json",
            api_cle_admin="",
        )


def test_prod_accepte_cle_admin_non_vide() -> None:
    s = Settings(
        postgres_password="mdp",
        api_environnement="prod",
        api_docs_actives=False,
        log_format="json",
        api_cle_admin="cle_admin_reelle",
    )
    assert s.api_environnement == "prod"


def test_meta_url_retombe_sur_le_couple_principal_sans_identifiants_dedies() -> None:
    """Régime local mono-rôle : pas de meta_user -> couple principal."""
    s = Settings(postgres_password="mdp", postgres_user="kuma_admin", meta_db="kuma_api_meta")
    url = s.database_url_meta
    assert url is not None
    assert "kuma_admin:mdp@" in url
    assert url.endswith("/kuma_api_meta")


def test_meta_url_utilise_les_identifiants_dedies_quand_fournis() -> None:
    """Profil serveur (ADR-0003 D2) : moteur méta = rôle kuma_api_service."""
    s = Settings(
        postgres_password="mdp_ro",
        postgres_user="kuma_api_ro",
        meta_db="kuma_api_meta",
        meta_user="kuma_api_service",
        meta_password="mdp_service",
    )
    url = s.database_url_meta
    assert url is not None
    assert "kuma_api_service:mdp_service@" in url
    # Le couple lecture seule ne fuit pas dans le DSN de la base de service.
    assert "kuma_api_ro" not in url
    assert "mdp_ro" not in url
