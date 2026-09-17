"""Tests unitaires du service de clés API (ADR-0003, D3 / WP6).

Tests sans DB, sur la génération et le hachage. Couvrent :

1. Format : préfixe ``kuma_``, longueur suffisante (256 bits d'entropie
   via ``token_urlsafe(32)``), préfixe public = ``kuma_`` + 8 caractères.
2. Empreinte : SHA-256 hex (64 caractères), déterministe, et distincte
   de la clé (jamais le secret en clair).
3. Unicité : deux générations ne se ressemblent pas.
"""

from __future__ import annotations

import hashlib

import pytest

from kuma_data_core.services.cles import (
    LIMITE_EMISSIONS_PAR_IP_24H,
    PREFIXE_CLE,
    generer_cle,
    hacher_cle,
)

pytestmark = pytest.mark.unit


def test_format_de_la_cle_generee() -> None:
    cle, prefixe, empreinte = generer_cle()
    assert cle.startswith(PREFIXE_CLE)
    assert len(cle) >= len(PREFIXE_CLE) + 43  # token_urlsafe(32) -> 43 caractères
    assert prefixe == cle[: len(PREFIXE_CLE) + 8]
    assert empreinte == hacher_cle(cle)


def test_empreinte_sha256_hex_deterministe() -> None:
    empreinte = hacher_cle("kuma_exemple")
    assert empreinte == hashlib.sha256(b"kuma_exemple").hexdigest()
    assert len(empreinte) == 64
    assert empreinte == hacher_cle("kuma_exemple")


def test_empreinte_ne_contient_pas_le_secret() -> None:
    cle, _, empreinte = generer_cle()
    assert cle not in empreinte


def test_deux_generations_distinctes() -> None:
    cle_a, _, empreinte_a = generer_cle()
    cle_b, _, empreinte_b = generer_cle()
    assert cle_a != cle_b
    assert empreinte_a != empreinte_b


def test_limite_emission_est_bornee() -> None:
    """La limite par IP existe et reste volontairement basse."""
    assert 1 <= LIMITE_EMISSIONS_PAR_IP_24H <= 10
