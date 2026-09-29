"""Mesures mensuelles brutes de référence pour les tests de grandeurs dérivées.

Réunit, pour une (source, grandeur), les **seeds pilotes** (modules Python, 3
points) et les **CSV des lots nationaux** (31 régions + 108 départements,
ADR-0015), relus indépendamment de la base. Sert au recalcul en boucle fermée
des écarts et de la fraction diffuse sur les 142 localités (ADR-0017).
"""

from __future__ import annotations

from types import ModuleType

from kuma_data_core.db.seeds.lots_civ import (
    CONTRATS_CAMS,
    CONTRATS_ERA5,
    CONTRATS_NASA,
    CONTRATS_SARAH3,
)
from kuma_data_core.db.seeds.series_csv import ContratSerie, lire_series

LOTS_MENSUELS: tuple[str, ...] = ("regions", "departements")

_CONTRATS_PAR_SOURCE: dict[str, dict[str, ContratSerie]] = {
    "nasa_power": CONTRATS_NASA,
    "sarah3_monthly": CONTRATS_SARAH3,
    "era5_pvgis": CONTRATS_ERA5,
    "cams_radiation": CONTRATS_CAMS,
}


def mesures_mensuelles(seed_pilote: ModuleType) -> dict[str, dict[tuple[int, int], float]]:
    """``{localité: {(année, mois): valeur}}`` pour les pilotes et les lots nationaux."""
    contrat = _CONTRATS_PAR_SOURCE[seed_pilote.SOURCE_CODE][seed_pilote.GRANDEUR_CODE]
    series = list(seed_pilote.SERIES)
    for lot in LOTS_MENSUELS:
        series += lire_series(contrat, lot)
    out: dict[str, dict[tuple[int, int], float]] = {}
    for s in series:
        assert s["localite_code"] not in out, s["localite_code"]  # lots disjoints des pilotes
        out[s["localite_code"]] = {(a, m): v for a, m, v in s["mesures"]}
    return out
