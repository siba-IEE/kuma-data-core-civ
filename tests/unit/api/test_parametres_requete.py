"""Erreurs de validation croisées des paramètres de requête : 422, jamais 500.

Les modèles de paramètres injectés par ``Depends()`` sont construits après la
validation propre de FastAPI ; l'erreur d'un ``model_validator`` sort en
``pydantic.ValidationError``. ``handler_validation_parametres`` la convertit en
422 ``VALIDATION_VALEUR_INVALIDE`` pour les seuls modèles de paramètres.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest
from pydantic import BaseModel, ValidationError
from starlette.requests import Request

from kuma_data_core.api.erreurs import handler_validation_parametres
from kuma_data_core.api.v1.schemas.grandeurs import ParametresPOA, ParametresPRRealiste
from kuma_data_core.api.v1.schemas.horaire import ParametresHoraire
from kuma_data_core.api.v1.schemas.parametres import noms_modeles_parametres

pytestmark = pytest.mark.unit

_REQUETE = Request({"type": "http", "method": "GET", "path": "/v1/test", "headers": []})


def _repondre(exc: ValidationError) -> tuple[int, dict[str, object]]:
    reponse = asyncio.run(handler_validation_parametres(_REQUETE, exc))
    return reponse.status_code, json.loads(bytes(reponse.body))


def _erreur(appel: object) -> ValidationError:
    with pytest.raises(ValidationError) as erreur:
        appel()  # type: ignore[operator]
    return erreur.value


def test_modeles_de_parametres_recenses() -> None:
    noms = noms_modeles_parametres()
    assert {"ParametresHoraire", "ParametresPOA", "ParametresPRRealiste"} <= noms
    assert "ParametresCommunsF2" in noms and ParametresPRRealiste.__name__ in noms


def test_periode_inversee_horaire_422() -> None:
    exc = _erreur(
        lambda: ParametresHoraire(
            localite="civ_dep_abidjan",
            grandeur="ghi",
            periode_debut=date(2022, 2, 1),
            periode_fin=date(2022, 1, 1),
        )
    )
    statut, corps = _repondre(exc)
    assert statut == 422
    assert corps["erreur"]["code"] == "VALIDATION_VALEUR_INVALIDE"  # type: ignore[index]
    assert "periode_fin" in json.dumps(corps, ensure_ascii=False)


def test_plage_horaire_trop_longue_422() -> None:
    exc = _erreur(
        lambda: ParametresHoraire(
            localite="civ_dep_abidjan",
            grandeur="ghi",
            periode_debut=date(2020, 1, 1),
            periode_fin=date(2022, 1, 1),
        )
    )
    assert _repondre(exc)[0] == 422


def test_periode_inversee_f2_422() -> None:
    exc = _erreur(
        lambda: ParametresPOA(
            code_serie_source="nasa_power_ghi_journalier_civ_dep_abidjan",
            periode_debut=date(2022, 2, 1),
            periode_fin=date(2022, 1, 1),
            inclinaison_deg=10,
            orientation_deg=180,
        )
    )
    assert _repondre(exc)[0] == 422


def test_autre_validation_reste_erreur_serveur() -> None:
    """Une ``ValidationError`` hors paramètres de requête n'est pas une 422."""

    class Reponse(BaseModel):
        valeur: int

    exc = _erreur(lambda: Reponse(valeur="pas un entier"))  # type: ignore[arg-type]
    statut, corps = _repondre(exc)
    assert statut == 500
    assert corps["erreur"]["code"] == "SERVEUR_ERREUR_INTERNE"  # type: ignore[index]
