"""pluie_chirps_journaliere

Revision ID: 0055
Revises: 0054
Create Date: 2026-10-28

**Pluie journalière CHIRPS v3.0 aux 142 localités** : quatrième source
journalière de la pluie, après NASA POWER (0035, 0047), ERA5 (0050) et GPM
IMERG (0052). CHIRPS fond l'estimation satellitaire infrarouge et les
pluviomètres au pas pentadaire ; son journalier répartit le cumul de chaque
pentade selon les proportions journalières d'ERA5 (désagrégation ``rnl``).

Grave, dans cet ordre :

1. la source ``chirps`` (**id 18**, id figé comme ``gpm_imerg`` en 0052) ;
2. **142 séries** ``chirps_precipitation_journalier_<localité>``
   (``granularite='journalier'``, table ``mesures_ressource``), méthode
   ``modele_satellitaire``, confiance **B** ;
3. leurs mesures, avec l'**audit par série** (ADR-0031).

| Grandeur | Produit | Jour | Unité | Période | Jours par série | Mesures |
|---|---|---|---|---|---:|---:|
| ``precipitation`` | CHIRPS v3.0 final, journalier ``rnl`` | D (00 h UTC D → 00 h UTC D + 1) | mm/jour | 1991-2025 | 12 784 | 1 815 328 |

Contrat : ``pluie_chirps_civ.CONTRAT_PLUIE_CHIRPS``. Valeur de la maille de
0,05° qui contient la localité (``maille_chirps`` ; une localité sur une limite
de maille est rattachée à la maille au sud et à l'est), sans interpolation :
121 mailles pour 142 localités. La somme des jours de chaque mois redonne le
CHIRPS v3.0 mensuel à 0,0001 mm près (50 699 mois-mailles), sauf en février
2000 où 5 mailles diffèrent (jusqu'à 4,1 mm) : incohérence de la source, citée
par la note, non corrigée.

Recoupement aux 142 localités (cité par la note) : aux 25 jours-localités où
NASA POWER dépasse 200 mm, CHIRPS donne au plus 21,2 mm le jour même et 54,8 mm
sur trois jours ; ses jours-localités > 50 mm passent de 89,8 par an
(1991-2015) à 111,0 (2017-2025), ×1,24, contre ×1,67 pour ERA5 et ×12 pour
NASA ; cumul annuel moyen 1998-2025 : 1 387 mm (NASA 1 393, ERA5 1 256, IMERG
1 287).

Valeurs lues hors-ligne dans le CSV gzip committé
(``seeds/donnees/chirps_precipitation_journalier_civ142.csv.gz``, généré par
``scripts/ingest_chirps_journalier.py``) et validées par
``series_csv.lire_series_journalieres``. Insertion par ``COPY`` avec l'audit par
série (``gravure_journaliere``).

Garde-fous : id 18 et code ``chirps`` libres, unité ``mm_par_jour``, 142
localités, aucune série préexistante, 142 séries et 1 815 328 mesures ; identité
de ``sources`` recalée. ``downgrade`` supprime mesures, séries et source.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from kuma_data_core.db.seeds.gravure_journaliere import graver_lot, supprimer_lot
from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.pluie_chirps_civ import (
    CONTRAT_PLUIE_CHIRPS,
    LOT_PLUIE_CHIRPS,
    UNITE_REFERENTIEL,
)
from kuma_data_core.db.seeds.series_csv import ContratSerie

# revision identifiers, used by Alembic.
revision: str = "0055"
down_revision: str | Sequence[str] | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVISION: str = "0055"
NB_POINTS: int = 142
NB_MESURES_ATTENDU: int = 1_815_328  # 142 × 12 784

URL_CHC: str = "https://www.chc.ucsb.edu/data/chirps3"
URL_DONNEES: str = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/"
URL_README: str = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/README-CHIRPSv3.0.txt"
URL_README_JOURNALIER: str = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/readme.txt"
DOI_ARTICLE: str = "10.1038/s41597-026-07096-4"

SOURCE: dict[str, object] = {
    "id": CONTRAT_PLUIE_CHIRPS.source_id,
    "code": CONTRAT_PLUIE_CHIRPS.source_code,
    "titre": (
        "CHIRPS v3.0 (Climate Hazards Center InfraRed Precipitation with Stations) — "
        "précipitations journalières 0,05°, version finale, désagrégation ERA5 (rnl)"
    ),
    "auteurs": ["Funk, C.", "Peterson, P.", "Harrison, L."],
    "organisation": "Climate Hazards Center, University of California Santa Barbara",
    "type_source": "base_donnees",
    "annee_publication": 2025,
    "date_consultation": "2026-10-28",
    "url": URL_DONNEES,
    "doi": "10.15780/G2JQ0P",
    "fiabilite": "haute",
    "langue": "en",
    "metadonnees": {
        "acces": (
            "Serveur HTTP du CHC, COG journaliers quasi globaux "
            "daily/final/rnl/cogs/<année>/chirps-v3.0.rnl.<AAAA.MM.JJ>.cog, lus par plages "
            "d'octets (GDAL /vsicurl/), sans clé"
        ),
        "version": "3.0 (publiée le 2025-01-01) ; la version 2.0 s'arrête en décembre 2026",
        "produit": "final (et non préliminaire)",
        "desagregation": (
            "rnl : proportions journalières d'ERA5 (1981 à nos jours) ; sat : IMERG Late V07 "
            "(depuis 1998), non retenu"
        ),
        "granularite_spatiale": "0,05° (maille contenant la localité)",
        "granularite_temporelle": "journalier, jour D ≈ 00 h UTC D → 00 h UTC D + 1",
        "valeur_ocean": -9999,
        "licence": (
            "domaine public, enregistré auprès de Creative Commons ; Creative Commons "
            "Attribution 4.0 International (page CHIRPS3 du CHC)"
        ),
        "article": f"Funk et al. (2026), Scientific Data 13, 718, doi:{DOI_ARTICLE}",
        "documentation": [URL_CHC, URL_README, URL_README_JOURNALIER],
    },
    "notes": (
        "CHIRPS v3.0 (Climate Hazards Center InfraRed Precipitation with Stations, CHC, "
        "université de Californie à Santa Barbara ; Funk et al. 2026, Scientific Data 13, "
        f"718, doi:{DOI_ARTICLE}). Estimation satellitaire infrarouge (CHIRP3) fondue avec "
        "les pluviomètres (plus de 90 sources de stations, corrigées du sous-captage) au "
        "pas pentadaire et mensuel, sur une grille de 0,05° de 60° N à 60° S ; les lacunes "
        "satellitaires sont comblées par ERA5. Le journalier n'est pas un produit "
        "indépendant : le cumul de chaque pentade est réparti entre ses jours selon les "
        "proportions journalières d'ERA5 (rnl, retenu, 1981 à nos jours) ou d'IMERG Late "
        "(sat, depuis 1998), interpolées bilinéairement sur la grille de 0,05° ; si ERA5 "
        "n'a pas de pluie sur une pentade où CHIRPS en a, le cumul est réparti également, "
        "ce qui peut créer de faux épisodes de jours pluvieux. Le CHC recommande les cumuls "
        "pentadaires ou mensuels quand c'est possible. Version finale (et non "
        "préliminaire). Données dans le domaine public, enregistrées auprès de Creative "
        "Commons, sous licence CC BY 4.0 (page CHIRPS3 du CHC). Citation demandée : « Climate "
        "Hazards Center Infrared Precipitation with Stations version 3 (CHIRPS3) Data "
        "Repository: https://doi.org/10.15780/G2JQ0P (2025). Accessed 2026-10-28. » "
        "Consulté le 2026-10-28."
    ),
}

NOTE: str = (
    "Précipitations journalières CHIRPS v3.0 final (CHC, UCSB ; satellite infrarouge fondu "
    "avec les pluviomètres) : valeur de la maille de 0,05° contenant la localité (une "
    "localité sur une limite de maille est rattachée à la maille au sud et à l'est), jour "
    "D de 00 h UTC D à 00 h UTC D + 1 (jour civil local, UTC+0), en mm/jour, telle que "
    "servie, 1991-2025. Le cumul de chaque pentade est l'information propre de CHIRPS ; "
    "sa répartition entre les jours de la pentade suit ERA5 (désagrégation rnl), avec de "
    "possibles faux épisodes de jours pluvieux quand ERA5 est sec : à utiliser de "
    "préférence en cumuls de pentade ou de mois, pas pour les extrêmes journaliers. "
    "La somme des jours redonne le CHIRPS mensuel à 0,0001 mm près, sauf en février "
    "2000 où 5 mailles diffèrent jusqu'à 4,1 mm (incohérence de la source, non "
    "corrigée). Recoupement aux 142 localités : aux 25 jours-localités où NASA POWER "
    "dépasse 200 mm, CHIRPS donne au plus 21,2 mm le jour même et 54,8 mm sur trois "
    "jours (1,65 mm à San-Pédro le 2022-09-16, contre 726,74 pour NASA) ; ses jours "
    "> 50 mm passent de 89,8 par an en 1991-2015 à 111,0 en 2017-2025 (×1,24, contre "
    "×1,67 pour ERA5 et ×12 pour NASA) ; cumul annuel moyen 1998-2025 de 1 387 mm "
    "(NASA 1 393, ERA5 1 256, IMERG 1 287). Estimation satellitaire, jamais une "
    "mesure au sol. Confiance B "
    "(ADR-0036)."
)


def _codes_localites() -> list[str]:
    return sorted(code for code, _, _, _ in points_nationaux())


def _contrats() -> list[ContratSerie]:
    return [CONTRAT_PLUIE_CHIRPS]


def _note(_contrat: ContratSerie, _serie: dict[str, Any]) -> str:
    return NOTE


def _recaler_sequence_sources(bind: sa.Connection) -> None:
    """Recale l'identité de ``sources`` sur le plus grand id présent (idempotent)."""
    bind.execute(
        sa.text(
            "SELECT setval(pg_get_serial_sequence('sources', 'id'), (SELECT MAX(id) FROM sources))"
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    contrat = CONTRAT_PLUIE_CHIRPS

    # 0. Garde-fous : id et code de la source libres, unité, localités, séries préexistantes.
    occupe = bind.execute(
        sa.text("SELECT id, code FROM sources WHERE id = :i OR code = :c"),
        {"i": contrat.source_id, "c": contrat.source_code},
    ).all()
    if occupe:
        raise RuntimeError(
            f"Migration {REVISION} : source id {contrat.source_id} ou code "
            f"{contrat.source_code!r} déjà pris : {[(r.id, r.code) for r in occupe]!r}."
        )
    unite = bind.execute(
        sa.text(
            "SELECT u.code FROM grandeurs_referentiel g JOIN unites u ON u.id = g.unite_id "
            "WHERE g.code = :g AND g.actif"
        ),
        {"g": contrat.grandeur_code},
    ).scalar_one_or_none()
    if unite != UNITE_REFERENTIEL:
        raise RuntimeError(
            f"Migration {REVISION} : grandeur {contrat.grandeur_code!r} en {unite!r}, "
            f"{UNITE_REFERENTIEL!r} attendue."
        )
    codes_loc = _codes_localites()
    loc = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM localites WHERE code = ANY(:c)"), {"c": codes_loc}
        ).all()
    }
    if len(codes_loc) != NB_POINTS or sorted(loc) != codes_loc:
        raise RuntimeError(
            f"Migration {REVISION} : {len(loc)} localités trouvées sur {len(codes_loc)}, "
            f"{NB_POINTS} attendues."
        )
    preexistantes = bind.execute(
        sa.text("SELECT code FROM series_metadonnees WHERE code = ANY(:c)"),
        {"c": [contrat.code_serie(code) for code in codes_loc]},
    ).all()
    if preexistantes:
        raise RuntimeError(
            f"Migration {REVISION} : séries déjà présentes : {[r.code for r in preexistantes]!r}."
        )

    # 1. Source à id figé (audit ligne à ligne de ``sources`` conservé).
    op.bulk_insert(
        sa.table(
            "sources",
            sa.column("id", sa.BigInteger),
            sa.column("code", sa.String),
            sa.column("titre", sa.Text),
            sa.column("auteurs", ARRAY(sa.Text)),
            sa.column("organisation", sa.String),
            sa.column("type_source", sa.String),
            sa.column("annee_publication", sa.Integer),
            sa.column("date_consultation", sa.Date),
            sa.column("url", sa.Text),
            sa.column("doi", sa.String),
            sa.column("fiabilite", sa.String),
            sa.column("langue", sa.String),
            sa.column("metadonnees", JSONB),
            sa.column("notes", sa.Text),
        ),
        [SOURCE],
    )
    _recaler_sequence_sources(bind)

    # 2. Séries, mesures par COPY et audit par série.
    total = graver_lot(bind, REVISION, _contrats(), LOT_PLUIE_CHIRPS, loc, _note)
    if total != NB_MESURES_ATTENDU:
        raise RuntimeError(
            f"Migration {REVISION} : {total} mesures, {NB_MESURES_ATTENDU} attendues."
        )
    bind.execute(sa.text("ANALYZE sources"))
    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE mesures_ressource"))


def downgrade() -> None:
    bind = op.get_bind()
    contrat = CONTRAT_PLUIE_CHIRPS
    supprimer_lot(bind, REVISION, _contrats(), LOT_PLUIE_CHIRPS, _codes_localites())
    # La source n'est supprimée que si plus aucune série ne la référence (FK RESTRICT).
    bind.execute(
        sa.text("DELETE FROM sources WHERE id = :i AND code = :c"),
        {"i": contrat.source_id, "c": contrat.source_code},
    )
    _recaler_sequence_sources(bind)
    bind.execute(sa.text("ANALYZE sources"))
    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE mesures_ressource"))
