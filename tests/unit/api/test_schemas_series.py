"""Tests unitaires des schemas Pydantic `api/v1/schemas/series.py` (ADR-0029).

Les bornes des schemas de reponse recopient les contraintes de la base,
jamais une periode d'instance :

- annee mensuelle bornee comme ``ck_mesures_ressource_mensuelles_annee_valide``
  (1981-2099), plus a partir de 1991 ;
- annees des grandeurs calculees non bornees (aucune contrainte en base) ;
- ``valeur`` d'une grandeur calculee nullable comme la colonne ;
- ``granularite`` exposee au catalogue, ``pagination_mesures`` au detail.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from kuma_data_core.api.v1.schemas.series import (
    ANNEE_MAX_MENSUELLE,
    ANNEE_MIN_MENSUELLE,
    GrandeurMetierValeur,
    MesureMensuelle,
    PaginationMesures,
    SerieDetail,
    SerieListee,
)

pytestmark = pytest.mark.unit


def _mensuelle(annee: int) -> MesureMensuelle:
    return MesureMensuelle(
        annee=annee,
        mois=1,
        valeur=5.0,
        niveau_confiance_derive="B",
        niveau_effectif="B",
        statut="brut",
    )


def _champs_serie(**surcharges: object) -> dict[str, object]:
    champs: dict[str, object] = {
        "id": 1,
        "code": "nasa_power_ghi_mensuel_xxx_point",
        "libelle": "GHI mensuel",
        "localite_id": 10,
        "localite_code": "xxx_point",
        "localite_nom": "Point",
        "localite_iso3": "XXX",
        "grandeur_code": "ghi",
        "grandeur_label": "Irradiation globale horizontale",
        "grandeur_unit": "kWh/m²/jour",
        "source_id": 1,
        "source_code": "nasa_power",
        "source_label": "NASA POWER",
        "source_url": None,
        "periode_debut": date(1991, 1, 1),
        "periode_fin": date(2025, 12, 31),
        "granularite": "mensuel",
        "methode_collecte": "modele_satellitaire",
        "notes_fr": None,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
        "actif": True,
    }
    champs.update(surcharges)
    return champs


def test_bornes_mensuelles_recopient_la_contrainte_de_la_base() -> None:
    assert (ANNEE_MIN_MENSUELLE, ANNEE_MAX_MENSUELLE) == (1981, 2099)


@pytest.mark.parametrize("annee", [1981, 1984, 1990, 2026, 2099])
def test_mesure_mensuelle_accepte_toute_annee_admise_en_base(annee: int) -> None:
    """Une serie meteo debutant en 1981 ne doit pas faire echouer la reponse."""
    assert _mensuelle(annee).annee == annee


@pytest.mark.parametrize("annee", [1980, 2100])
def test_mesure_mensuelle_refuse_une_annee_hors_contrainte(annee: int) -> None:
    with pytest.raises(ValidationError):
        _mensuelle(annee)


def test_grandeur_metier_annees_non_bornees_et_valeur_nullable() -> None:
    valeur = GrandeurMetierValeur(
        periode_type="annuel",
        annee_debut=1984,
        annee_fin=2026,
        version_formule=1,
        valeur=None,
        niveau_confiance_derive="B",
        niveau_effectif="B",
        statut="brut",
    )
    assert valeur.valeur is None
    assert valeur.model_dump(mode="json")["valeur"] is None


def test_serie_listee_expose_la_granularite() -> None:
    assert SerieListee(**_champs_serie()).granularite == "mensuel"  # type: ignore[arg-type]
    # Grandeur calculee : pas de granularite (routage par source).
    calculee = SerieListee(**_champs_serie(granularite=None))  # type: ignore[arg-type]
    assert calculee.granularite is None
    with pytest.raises(ValidationError):
        SerieListee(**_champs_serie(granularite="annuel"))  # type: ignore[arg-type]


def test_serie_detail_porte_la_pagination_des_mesures() -> None:
    detail = SerieDetail(
        **_champs_serie(),  # type: ignore[arg-type]
        unite_code="kwh_par_m2_jour",
        pagination_mesures=PaginationMesures(total=12784, limit=1000, offset=0),
        mesures=[_mensuelle(1991)],
    )
    dump = detail.model_dump(mode="json")
    assert dump["pagination_mesures"] == {"total": 12784, "limit": 1000, "offset": 0}
    assert dump["granularite"] == "mensuel"


@pytest.mark.parametrize(
    "champs",
    [
        {"total": -1, "limit": 1, "offset": 0},
        {"total": 0, "limit": 0, "offset": 0},
        {"total": 0, "limit": 1, "offset": -1},
    ],
)
def test_pagination_mesures_bornes(champs: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        PaginationMesures(**champs)
