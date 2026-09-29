"""Mesures mensuelles brutes de référence pour les tests de grandeurs dérivées.

Réunit, pour une (source, grandeur), les **seeds pilotes** (modules Python, 3
points), les **CSV des lots nationaux** (31 régions + 108 départements,
ADR-0015) et les **CSV d'extension 2021+** (142 localités, ADR-0018), relus
indépendamment de la base. Sert au recalcul en boucle fermée
des écarts et de la fraction diffuse sur les 142 localités (ADR-0017).
"""

from __future__ import annotations

from types import ModuleType

from kuma_data_core.db.seeds.lots_civ import (
    CONTRATS_CAMS,
    CONTRATS_ERA5,
    CONTRATS_NASA,
    CONTRATS_SARAH3,
    LOT_EXTENSION,
    contrat_extension,
)
from kuma_data_core.db.seeds.series_csv import ContratSerie, lire_series

LOTS_MENSUELS: tuple[str, ...] = ("regions", "departements")

_CONTRATS_PAR_SOURCE: dict[str, dict[str, ContratSerie]] = {
    "nasa_power": CONTRATS_NASA,
    "sarah3_monthly": CONTRATS_SARAH3,
    "era5_pvgis": CONTRATS_ERA5,
    "cams_radiation": CONTRATS_CAMS,
}


def contrat_de(seed_pilote: ModuleType) -> ContratSerie:
    """Contrat des lots (période de base) correspondant à un seed pilote."""
    return _CONTRATS_PAR_SOURCE[seed_pilote.SOURCE_CODE][seed_pilote.GRANDEUR_CODE]


def mesures_mensuelles(seed_pilote: ModuleType) -> dict[str, dict[tuple[int, int], float]]:
    """``{localité: {(année, mois): valeur}}`` : pilotes, lots nationaux et extension 2021+."""
    contrat = contrat_de(seed_pilote)
    series = list(seed_pilote.SERIES)
    for lot in LOTS_MENSUELS:
        series += lire_series(contrat, lot)
    out: dict[str, dict[tuple[int, int], float]] = {}
    for s in series:
        assert s["localite_code"] not in out, s["localite_code"]  # lots disjoints des pilotes
        out[s["localite_code"]] = {(a, m): v for a, m, v in s["mesures"]}
    for s in lire_series(contrat_extension(contrat), LOT_EXTENSION):
        base = out[s["localite_code"]]  # l'extension ne crée aucune localité
        for a, m, v in s["mesures"]:
            assert (a, m) not in base, (s["localite_code"], a, m)  # aucun recouvrement
            base[(a, m)] = v
    return out
