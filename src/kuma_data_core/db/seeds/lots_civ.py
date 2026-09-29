"""Lots de couverture nationale CIV : points et contrats de séries (ADR-0015).

Un **lot** est un ensemble de localités du référentiel (niveau administratif)
interrogées aux 4 sources solaires, au même contrat que les 3 points pilotes
(ADR-0007 à ADR-0013) :

- ``regions`` : les 31 régions (niveau générique ``prefecture``, coordonnées
  Wikidata ``P625`` gravées en 0006) ;
- ``departements`` : les 108 départements (niveau ``commune``, 0007) **hors les 3
  points pilotes**, déjà gravés dans leurs propres seeds (Abidjan, Yamoussoukro,
  Korhogo) — les codes de série resteraient sinon en double.

Les contrats reprennent exactement ceux des séries pilotes (source, méthode,
période, conversion) ; seules les localités changent.
"""

from __future__ import annotations

from kuma_data_core.db.seeds.localites_civ_seed_data import LOCALITES_SEED
from kuma_data_core.db.seeds.series_csv import ContratSerie
from kuma_data_core.db.seeds.series_nasa_power_ghi_mensuel_civ import SERIES as _SERIES_PILOTES

# Niveau administratif du référentiel couvert par chaque lot.
NIVEAUX_LOTS: dict[str, str] = {"regions": "prefecture", "departements": "commune"}

# Les 3 points pilotes (départements), gravés en seeds Python : exclus des lots.
POINTS_PILOTES: frozenset[str] = frozenset(s["localite_code"] for s in _SERIES_PILOTES)


def points_lot(lot: str) -> list[tuple[str, str, float, float]]:
    """Localités d'un lot : ``(code, nom, latitude, longitude)``, triées par code."""
    niveau = NIVEAUX_LOTS[lot]
    entrees = [
        e
        for e in LOCALITES_SEED
        if e["type_localite"] == niveau and e["code"] not in POINTS_PILOTES
    ]
    sans_coord = [e["code"] for e in entrees if e["latitude"] is None or e["longitude"] is None]
    if sans_coord:
        raise ValueError(f"Lot {lot!r} : localité(s) sans coordonnées : {sans_coord!r}.")
    return sorted(
        (e["code"], e["nom"], float(e["latitude"]), float(e["longitude"])) for e in entrees
    )


def _nasa(grandeur: str, debut: int, borne: float) -> ContratSerie:
    return ContratSerie(
        source_code="nasa_power",
        source_id=1,
        source_libelle="NASA POWER",
        prefixe_code=f"nasa_power_{grandeur}_mensuel",
        grandeur_code=grandeur,
        methode_collecte="modele_satellitaire",
        annee_debut=debut,
        annee_fin=2020,
        borne_max=borne,
    )


def _pvgis(
    source: str, sid: int, libelle: str, prefixe: str, methode: str, grandeur: str, borne: float
) -> ContratSerie:
    return ContratSerie(
        source_code=source,
        source_id=sid,
        source_libelle=libelle,
        prefixe_code=f"{prefixe}_{grandeur}_mensuel",
        grandeur_code=grandeur,
        methode_collecte=methode,
        annee_debut=2005,
        annee_fin=2020,
        borne_max=borne,
    )


def _cams(grandeur: str, borne: float) -> ContratSerie:
    return ContratSerie(
        source_code="cams_radiation",
        source_id=13,
        source_libelle="CAMS Radiation",
        prefixe_code=f"cams_{grandeur}_mensuel",
        grandeur_code=grandeur,
        methode_collecte="modele_satellitaire",
        annee_debut=2005,
        annee_fin=2020,
        borne_max=borne,
    )


# Contrats par source, alignés sur les séries pilotes (mêmes périodes et bornes).
CONTRATS_NASA: dict[str, ContratSerie] = {
    "ghi": _nasa("ghi", 1991, 7.0),  # ADR-0007
    "dni": _nasa("dni", 2001, 9.0),  # DNI servi depuis 2001
    "dhi": _nasa("dhi", 2001, 6.0),  # rupture avant 2001 (ADR-0013)
}
CONTRATS_SARAH3: dict[str, ContratSerie] = {
    g: _pvgis("sarah3_monthly", 11, "SARAH-3 (PVGIS)", "sarah3", "modele_satellitaire", g, b)
    for g, b in (("ghi", 7.0), ("dni", 9.0))
}
CONTRATS_ERA5: dict[str, ContratSerie] = {
    g: _pvgis("era5_pvgis", 16, "ERA5 (PVGIS)", "era5", "reanalyse", g, b)
    for g, b in (("ghi", 7.0), ("dni", 9.0))
}
CONTRATS_CAMS: dict[str, ContratSerie] = {
    g: _cams(g, b) for g, b in (("ghi", 9.0), ("dni", 12.0), ("dhi", 6.0))
}

# Tous les contrats d'un lot mensuel, dans l'ordre d'insertion des migrations.
CONTRATS_MENSUELS: tuple[ContratSerie, ...] = (
    *CONTRATS_NASA.values(),
    *CONTRATS_SARAH3.values(),
    *CONTRATS_ERA5.values(),
    *CONTRATS_CAMS.values(),
)
