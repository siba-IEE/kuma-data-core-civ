"""Tests unitaires de la recherche textuelle de ``GET /v1/localites`` (ADR-0029).

Couvre les deux helpers purs du routeur :

- :func:`normaliser_recherche` : texte saisi -> forme slug des codes
  (minuscules, sans accents, ponctuation -> ``_``).
- :func:`clause_recherche` : clause SQL (nom ``ILIKE`` OU code ``LIKE``)
  et parametres, metacaracteres ``LIKE`` echappes.
"""

from __future__ import annotations

import pytest

from kuma_data_core.api.v1.localites import clause_recherche, normaliser_recherche

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("saisie", "attendu"),
    [
        ("San-Pédro", "san_pedro"),
        ("san pedro", "san_pedro"),
        ("Gôh", "goh"),
        ("N'Zi", "n_zi"),
        ("  Agnéby-Tiassa  ", "agneby_tiassa"),
        ("Côte d'Ivoire", "cote_d_ivoire"),
        ("KORHOGO", "korhogo"),
        ("Zone 4", "zone_4"),
    ],
)
def test_normaliser_recherche_produit_la_forme_des_codes(saisie: str, attendu: str) -> None:
    assert normaliser_recherche(saisie) == attendu


@pytest.mark.parametrize("saisie", ["", "   ", "--", "%", "_", "'"])
def test_normaliser_recherche_sans_lettre_ni_chiffre_est_vide(saisie: str) -> None:
    assert normaliser_recherche(saisie) == ""


def test_clause_recherche_combine_nom_et_code() -> None:
    clause, params = clause_recherche("San-Pédro")
    assert clause == "(L.nom ILIKE :q_nom ESCAPE '\\' OR L.code LIKE :q_code ESCAPE '\\')"
    assert params == {"q_nom": "%San-Pédro%", "q_code": "%san\\_pedro%"}


def test_clause_recherche_sans_slug_cherche_le_nom_seul() -> None:
    """Un texte sans lettre ni chiffre ne doit pas devenir un ``LIKE '%%'``."""
    clause, params = clause_recherche("%")
    assert "q_code" not in params
    assert "L.code" not in clause
    # Le ``%`` saisi est litteral, pas un joker.
    assert params == {"q_nom": "%\\%%"}


def test_clause_recherche_echappe_les_metacaracteres_like() -> None:
    _clause, params = clause_recherche("a_b\\c")
    assert params["q_nom"] == "%a\\_b\\\\c%"
    assert params["q_code"] == "%a\\_b\\_c%"
