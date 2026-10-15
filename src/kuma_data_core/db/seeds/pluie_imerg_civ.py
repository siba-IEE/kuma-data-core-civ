"""Contrat de la pluie journalière GPM IMERG (servie par NASA POWER) aux 142 localités.

Troisième source journalière de la pluie, à côté de NASA POWER
(``PRECTOTCORR``, MERRA-2, 0035 et 0047) et d'ERA5 (0050) : **IMERG**
(Integrated Multi-satellitE Retrievals for GPM, NASA GSFC, Huffman et al.),
servi par NASA POWER sous le paramètre ``IMERG_PRECTOT``. Décision de
l'utilisateur : le proxy de salissure et le PR réaliste prennent leurs épisodes
de pluie dans IMERG et non plus dans ``PRECTOTCORR``, dont les jours extrêmes
sont fantômes et dont les fortes pluies ont une rupture en 2016-2017
(ADR-0032).

**Produit** (documentation IMERG V07 : *Technical Documentation* du
2023-07-13, *Release Notes* du 2023-12-20 ; fiche GES DISC ``GPM_3IMERGDF``
V07) : estimation multi-satellites (micro-ondes passives calibrées sur
l'algorithme combiné radar-radiomètre de TRMM puis de GPM, infrarouge
géostationnaire, propagation par morphing et filtre de Kalman) sur une grille
de **0,1°**, au pas demi-horaire. Le **Final Run** est calé **mois par mois**
sur l'analyse des pluviomètres du **GPCC** (Full Data jusqu'en 2020, Monitoring
ensuite ; version 2022 en 2023), corrigée du sous-captage : chaque demi-heure
du mois est multipliée par le rapport, borné à [0,2 ; 3], entre la combinaison
mensuelle satellite-pluviomètres et le cumul satellite seul. Ce calage corrige le biais
mais laisse l'occurrence des pluies inchangée. Le journalier GES DISC est la
moyenne des demi-heures valides du **jour UTC** × 24.

**Servi par POWER** (sondage du 2026-10-15, API v2.10.0) : paramètre intégré
le 2025-03-04 (version de données 10.0.5, « IMERG v7B »), journalier et UTC
seulement, à partir du **1998-01-01**, début du record V07 (la page des sources
de POWER indique à tort 2001-01-01), jusqu'au 2026-09-14 au sondage
d'Abidjan ; unité ``mm/day``, 2 décimales, ``"sources": ["IMERG"]``,
``"time_standard": "UTC"``, aucune valeur de remplissage de 1998 à 2025 aux
142 localités. Le jour UTC est le jour civil local en Côte d'Ivoire (UTC+0).

**Fin du Final Run V07** : le record Final V07 (V07B) s'arrête au
**2025-09-30** (``DERNIER_JOUR_FINAL_RUN``) ; ses produits parents passent en
V08 (GPM, « IMERG V08 Transition Schedule », 2026-04-28 ; dernier granule
``GPM_3IMERGDF`` V07B du CMR daté du 2025-09-30). D'après la documentation de
POWER, le **Late Run** prend la suite du Final Run : les 92 derniers jours de la
période (2025-10-01 → 2025-12-31) en viennent, sans calage mensuel sur les
pluviomètres (calage climatologique sur le Final).

Valeur de la maille 0,1° qui contient chaque localité, telle que servie
(2 décimales), sans conversion ni interpolation : 120 séries distinctes pour
142 localités. Période **1998-2025** : 10 227 jours par série. Source
``gpm_imerg`` (id 17, créée en 0052), méthode ``modele_satellitaire``,
confiance B. La borne de sanité est celle de la pluie
journalière NASA POWER (1000 mm/jour), borne basse 0 : un garde-fou, pas une
valeur attendue.
"""

from __future__ import annotations

from datetime import date

from kuma_data_core.db.seeds.meteo_civ import BORNE_PRECIPITATION_JOURNALIERE
from kuma_data_core.db.seeds.series_csv import ContratSerie

SOURCE_CODE: str = "gpm_imerg"
SOURCE_ID: int = 17
"""Id figé de la source, comme ``era5_pvgis`` (16, migration 0012)."""

LOT_PLUIE_IMERG: str = "civ142"
"""Suffixe du CSV : les 142 localités en un seul fichier."""

PARAMETRE_POWER: str = "IMERG_PRECTOT"
COMMUNAUTE_POWER: str = "RE"
STANDARD_TEMPS: str = "UTC"
"""POWER ne sert IMERG qu'en journalier UTC."""
SOURCES_SERVIES: tuple[str, ...] = ("IMERG",)
"""Champ ``header.sources`` attendu dans la réponse JSON de POWER."""
UNITE_SERVIE: str = "mm/day"
UNITE_REFERENTIEL: str = "mm_par_jour"
DECIMALES_SERVIES: int = 2
REMPLISSAGE_POWER: float = -999.0
"""Valeur de remplissage de POWER (``header.fill_value``)."""

ANNEE_DEBUT_IMERG: int = 1998
"""Premier jour servi : 1998-01-01, début du record IMERG V07 (ère TRMM)."""
ANNEE_FIN_IMERG: int = 2025

DERNIER_JOUR_FINAL_RUN: date = date(2025, 9, 30)
"""Dernier jour du Final Run V07 ; le Late Run sert la suite (documentation POWER)."""

DEBUT_CALAGE_GPM: date = date(2014, 6, 1)
"""Calage de la constellation sur TRMM jusqu'en mai 2014, sur GPM ensuite (IMERG V07)."""

CONTRAT_PLUIE_IMERG: ContratSerie = ContratSerie(
    source_code=SOURCE_CODE,
    source_id=SOURCE_ID,
    source_libelle="GPM IMERG (POWER)",
    prefixe_code="gpm_imerg_precipitation_journalier",
    grandeur_code="precipitation",
    methode_collecte="modele_satellitaire",
    annee_debut=ANNEE_DEBUT_IMERG,
    annee_fin=ANNEE_FIN_IMERG,
    borne_max=BORNE_PRECIPITATION_JOURNALIERE,
    granularite="journalier",
    libelle_grandeur="Précipitations",
)
