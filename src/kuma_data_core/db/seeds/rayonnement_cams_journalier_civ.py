"""Contrats du rayonnement journalier CAMS Radiation (GHI, DNI, DHI) aux 142 localités.

Deuxième source journalière du rayonnement, à côté de NASA POWER (0026, 0046) :
**CAMS Radiation** (Copernicus Atmosphere Monitoring Service ; méthode
Heliosat-4, McClear pour le ciel clair), dont les moyennes mensuelles sont
gravées aux 142 localités (0018, 0027, 0031 ; ADR-0011, ADR-0013, ADR-0018).
NASA POWER sert le rayonnement sur une maille de 0,5° × 0,625° et ne distingue
que 35 séries pour 142 localités (ADR-0027) ; CAMS le calcule au point demandé,
depuis les images Meteosat (environ 3 à 5 km au sol en Côte d'Ivoire).

**Produit** : jeu ADS ``cams-solar-radiation-timeseries``, ``sky_type`` =
``observed_cloud`` (tous ciels), ``time_step`` = ``1day``,
``time_reference`` = ``universal_time``, CSV ``;``-séparé, en-têtes ``#``.
Chaque ligne couvre un jour UTC (``AAAA-MM-JJT00:00/AAAA-MM-J+1T00:00``), jour
civil local en Côte d'Ivoire (UTC+0). Colonnes **repérées par nom** :
``GHI``, ``BNI`` (= DNI) et ``DHI``, en **Wh/m² intégrés au jour** ; la colonne
``Reliability`` donne la part des pas de 15 min fiables dans le jour (0 à 1),
non gravée.

**Conversion** vers ``kwh_par_m2_jour`` : Wh/m²/jour ÷ 1000 (``kwh_par_jour``),
arrondi à 4 décimales à l'écriture du CSV. Aucune interpolation, aucune
valeur bouchée.

**Lacunes** : CAMS ne sert pas de valeur (``nan``) les jours où il manque une
partie des images Meteosat (fiabilité voisine de 0,52) : 2005-01-11, 2005-01-12,
2006-01-10 et 2006-01-11 partout, 2006-09-23 dans 54 localités (sondage du
2026-10-28). Ces jours figurent dans le CSV avec une valeur vide
(``lacunes_admises``) et ne sont pas gravés : la série a un trou, jamais une
valeur inventée.

**Révision 2021-2025** : la moyenne des jours redonne le mensuel CAMS gravé à
0,0001 kWh/m²/jour près de 2005 à 2020, mais CAMS a révisé 2021-2025 depuis la
gravure de son mensuel (sondage du 2026-09-30) : le journalier suit la
révision (ADR-0035).

Coordonnées demandées : celles du référentiel, au point (CAMS ne travaille pas
sur une grille de points prédéfinis), comme pour le mensuel. Période
**2005-2025** (le service commence en février 2004), source
``cams_radiation`` (id 13), méthode ``modele_satellitaire``, confiance B. Les
bornes de sanité sont celles du rayonnement journalier NASA POWER
(``lots_civ.CONTRATS_NASA_JOURNALIERS``), borne basse 0.
"""

from __future__ import annotations

from kuma_data_core.db.seeds.lots_civ import CONTRATS_NASA_JOURNALIERS
from kuma_data_core.db.seeds.meteo_civ import LOT_METEO_MENSUEL
from kuma_data_core.db.seeds.series_csv import ContratSerie

LOT_CAMS_JOURNALIER: str = LOT_METEO_MENSUEL
"""Suffixe des CSV : les 142 localités en un seul fichier par grandeur (``civ142``)."""

JEU_ADS: str = "cams-solar-radiation-timeseries"
ANNEE_DEBUT_CAMS_JOURNALIER: int = 2005
ANNEE_FIN_CAMS_JOURNALIER: int = 2025
WH_PAR_KWH: float = 1000.0

GRANDEURS_CAMS: tuple[str, ...] = ("ghi", "dni", "dhi")
COLONNES_CAMS: dict[str, str] = {"ghi": "GHI", "dni": "BNI", "dhi": "DHI"}
"""Grandeur → nom de la colonne CAMS (tous ciels, Wh/m² intégrés sur le pas)."""


def _contrat(grandeur: str) -> ContratSerie:
    return ContratSerie(
        source_code="cams_radiation",
        source_id=13,
        source_libelle="CAMS Radiation",
        prefixe_code=f"cams_{grandeur}_journalier",
        grandeur_code=grandeur,
        methode_collecte="modele_satellitaire",
        annee_debut=ANNEE_DEBUT_CAMS_JOURNALIER,
        annee_fin=ANNEE_FIN_CAMS_JOURNALIER,
        borne_max=CONTRATS_NASA_JOURNALIERS[grandeur].borne_max,
        granularite="journalier",
        lacunes_admises=True,
    )


CONTRATS_CAMS_JOURNALIERS: dict[str, ContratSerie] = {g: _contrat(g) for g in GRANDEURS_CAMS}


def kwh_par_jour(wh_par_m2: float) -> float:
    """Irradiation du jour : Wh/m² → kWh/m²/jour."""
    return wh_par_m2 / WH_PAR_KWH
