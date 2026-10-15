"""Erreurs de validation croisées des paramètres de requête : 422, jamais 500.

Les modèles de paramètres injectés par ``Depends()`` sont construits après la
validation propre de FastAPI ; une erreur de leur ``model_validator`` doit
ressortir en ``RequestValidationError`` (réponse 422 ``VALIDATION_VALEUR_INVALIDE``).
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.exceptions import RequestValidationError

from kuma_data_core.api.v1.schemas.grandeurs import ParametresPOA
from kuma_data_core.api.v1.schemas.horaire import ParametresHoraire

pytestmark = pytest.mark.unit


def test_periode_inversee_horaire() -> None:
    with pytest.raises(RequestValidationError) as erreur:
        ParametresHoraire(
            localite="civ_dep_abidjan",
            grandeur="ghi",
            periode_debut=date(2022, 2, 1),
            periode_fin=date(2022, 1, 1),
        )
    assert "periode_fin" in str(erreur.value.errors())


def test_plage_horaire_trop_longue() -> None:
    with pytest.raises(RequestValidationError, match="366"):
        ParametresHoraire(
            localite="civ_dep_abidjan",
            grandeur="ghi",
            periode_debut=date(2020, 1, 1),
            periode_fin=date(2022, 1, 1),
        )


def test_periode_inversee_f2() -> None:
    with pytest.raises(RequestValidationError):
        ParametresPOA(
            code_serie_source="nasa_power_ghi_journalier_civ_dep_abidjan",
            periode_debut=date(2022, 2, 1),
            periode_fin=date(2022, 1, 1),
            inclinaison_deg=10,
            azimut_deg=180,
        )
