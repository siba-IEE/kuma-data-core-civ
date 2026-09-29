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

from dataclasses import dataclass, replace

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


# --- Lot 3 : NASA POWER journalier (table ``mesures_ressource``) ------------------

LOT_JOURNALIER: str = "pilotes_regions"
"""Périmètre du journalier : 3 points pilotes + 31 régions (décision 2026-09-29)."""


def points_journalier() -> list[tuple[str, str, float, float]]:
    """Les 34 localités du lot journalier : pilotes puis régions, triées par code."""
    pilotes = [
        (e["code"], e["nom"], float(e["latitude"]), float(e["longitude"]))
        for e in LOCALITES_SEED
        if e["code"] in POINTS_PILOTES
    ]
    return sorted(pilotes + points_lot("regions"))


def _nasa_jour(grandeur: str, debut: int, borne: float) -> ContratSerie:
    return ContratSerie(
        source_code="nasa_power",
        source_id=1,
        source_libelle="NASA POWER",
        prefixe_code=f"nasa_power_{grandeur}_journalier",
        grandeur_code=grandeur,
        methode_collecte="modele_satellitaire",
        annee_debut=debut,
        annee_fin=2020,
        borne_max=borne,
        granularite="journalier",
    )


# Paramètre NASA POWER de chaque grandeur, et contrat (mêmes périodes que le mensuel).
PARAMETRES_NASA: dict[str, str] = {
    "ghi": "ALLSKY_SFC_SW_DWN",
    "dni": "ALLSKY_SFC_SW_DNI",
    "dhi": "ALLSKY_SFC_SW_DIFF",
}
CONTRATS_NASA_JOURNALIERS: dict[str, ContratSerie] = {
    "ghi": _nasa_jour("ghi", 1991, 9.0),  # bornes journalières plus larges que mensuelles
    "dni": _nasa_jour("dni", 2001, 12.0),
    "dhi": _nasa_jour("dhi", 2001, 7.0),  # rupture DHI avant 2001 (ADR-0013)
}


# --- Grandeurs dérivées étendues aux lots (ADR-0017) --------------------------------


@dataclass(frozen=True)
class EcartInterSource:
    """Un écart relatif inter-source ``(comparée − nasa) / nasa × 100`` (ADR-0009)."""

    grandeur_code: str  # ex. "ecart_relatif_ghi_sarah3_nasa"
    prefixe_serie: str  # ex. "ecart_ghi_sarah3_nasa"
    grandeur_brute: str  # "ghi", "dni" ou "dhi"
    source_comparee: str  # code de la source au numérateur
    libelle_source: str  # pour les libellés de série

    def code_serie(self, localite_code: str) -> str:
        return f"{self.prefixe_serie}_{localite_code}"


# Les 7 écarts gravés aux pilotes (0011, 0013, 0015, 0016, 0019, 0020, 0023).
ECARTS_INTER_SOURCES: tuple[EcartInterSource, ...] = (
    EcartInterSource(
        "ecart_relatif_ghi_sarah3_nasa", "ecart_ghi_sarah3_nasa", "ghi", "sarah3_monthly", "SARAH-3"
    ),
    EcartInterSource(
        "ecart_relatif_ghi_era5_nasa", "ecart_ghi_era5_nasa", "ghi", "era5_pvgis", "ERA5"
    ),
    EcartInterSource(
        "ecart_relatif_ghi_cams_nasa", "ecart_ghi_cams_nasa", "ghi", "cams_radiation", "CAMS"
    ),
    EcartInterSource(
        "ecart_relatif_dni_cams_nasa", "ecart_dni_cams_nasa", "dni", "cams_radiation", "CAMS"
    ),
    EcartInterSource(
        "ecart_relatif_dni_sarah3_nasa", "ecart_dni_sarah3_nasa", "dni", "sarah3_monthly", "SARAH-3"
    ),
    EcartInterSource(
        "ecart_relatif_dni_era5_nasa", "ecart_dni_era5_nasa", "dni", "era5_pvgis", "ERA5"
    ),
    EcartInterSource(
        "ecart_relatif_dhi_cams_nasa", "ecart_dhi_cams_nasa", "dhi", "cams_radiation", "CAMS"
    ),
)


def points_lots_mensuels() -> list[tuple[str, str, float, float]]:
    """Les 139 localités des lots mensuels (31 régions + 108 départements)."""
    return sorted(points_lot("regions") + points_lot("departements"))


# --- Extension temporelle 2021-2025 (ADR-0018) ---------------------------------------

LOT_EXTENSION: str = "ext_2021_2025"
"""Suffixe des CSV d'extension : années 2021+ des séries déjà gravées (mêmes codes)."""

ANNEE_DEBUT_EXTENSION: int = 2021

# Dernière année servie par chaque source (sondage du 2026-09-30) : PVGIS s'arrête
# en 2023 ; NASA POWER et CAMS couvrent 2025 en entier.
FIN_EXTENSION: dict[str, int] = {
    "nasa_power": 2025,
    "cams_radiation": 2025,
    "sarah3_monthly": 2023,
    "era5_pvgis": 2023,
}


def contrat_extension(contrat: ContratSerie) -> ContratSerie:
    """Même contrat (source, préfixe, bornes), période 2021 → fin servie par la source."""
    return replace(
        contrat,
        annee_debut=ANNEE_DEBUT_EXTENSION,
        annee_fin=FIN_EXTENSION[contrat.source_code],
    )


CONTRATS_EXTENSION: tuple[ContratSerie, ...] = tuple(
    contrat_extension(c) for c in CONTRATS_MENSUELS
)
CONTRATS_NASA_JOURNALIERS_EXTENSION: dict[str, ContratSerie] = {
    g: contrat_extension(c) for g, c in CONTRATS_NASA_JOURNALIERS.items()
}


def points_nationaux() -> list[tuple[str, str, float, float]]:
    """Les 142 localités des séries mensuelles : 3 pilotes + 31 régions + 108 départements."""
    pilotes = [
        (e["code"], e["nom"], float(e["latitude"]), float(e["longitude"]))
        for e in LOCALITES_SEED
        if e["code"] in POINTS_PILOTES
    ]
    return sorted(pilotes + points_lots_mensuels())
