"""pluie_imerg_journaliere

Revision ID: 0052
Revises: 0051
Create Date: 2026-10-15

**Pluie journalière GPM IMERG aux 142 localités** : source des épisodes de
pluie journaliers (lessivage : proxy de salissure, PR réaliste), à la place de
la pluie NASA POWER ``PRECTOTCORR`` (MERRA-2 recalée sur CMAP), dont les jours
extrêmes sont fantômes et dont les fortes pluies ont une rupture en 2016-2017
(ADR-0032 ; décision de l'utilisateur, ADR-0033). Troisième source journalière
de la pluie, après NASA POWER (0035, 0047) et ERA5 (0050).

Grave, dans cet ordre :

1. la source ``gpm_imerg`` (**id 17**, id figé comme ``era5_pvgis`` en 0012) :
   IMERG V07 (NASA GPM, Huffman et al. ; archive NASA GES DISC), servi par
   NASA POWER sous le paramètre ``IMERG_PRECTOT`` ;
2. **142 séries** ``gpm_imerg_precipitation_journalier_<localité>``
   (``granularite='journalier'``, table ``mesures_ressource``), méthode
   ``modele_satellitaire``, confiance **B** ;
3. leurs mesures, avec l'**audit par série** (ADR-0031).

| Grandeur | Paramètre POWER | Jour | Unité | Période | Jours par série | Mesures |
|---|---|---|---|---|---:|---:|
| ``precipitation`` | ``IMERG_PRECTOT`` | UTC (= local, UTC+0) | mm/day, 2 décimales | 1998-2025 | 10 227 | 1 452 234 |

Contrat : ``pluie_imerg_civ.CONTRAT_PLUIE_IMERG``. Produit satellite
multi-capteurs sur une grille de 0,1°. Le Final Run est calé mois par mois sur
les pluviomètres du GPCC ; il s'arrête au 2025-09-30 (fin du record Final V07,
passage à V08) et POWER sert ensuite le Late Run, sans calage mensuel : les
92 derniers jours (2025-10-01 → 2025-12-31) en viennent, ce que disent la note
de la source et celle des séries. Valeur de la maille 0,1° contenant la
localité, telle que servie : 120 séries distinctes pour 142 localités.

Valeurs lues hors-ligne dans le CSV gzip committé
(``seeds/donnees/gpm_imerg_precipitation_journalier_civ142.csv.gz``, généré par
``scripts/ingest_imerg_journalier.py``) et validées par
``series_csv.lire_series_journalieres`` (tous les jours civils, bornes, doublons,
localités). Insertion par ``COPY`` avec l'**audit par série**
(``audit_par_serie``) : audit ligne à ligne de ``mesures_ressource`` suspendu le
temps de l'insertion, puis une entrée d'audit par série (code, nombre de
mesures, bornes, fichier et empreinte SHA-256, révision) ; la source et les
séries gardent l'audit ligne à ligne.

Garde-fous : id 17 et code ``gpm_imerg`` libres, unité ``mm_par_jour`` de la
grandeur au référentiel, 142 localités, **aucune série préexistante** (ni ces
codes, ni série journalière de pluie de la source), couverture exacte du CSV,
142 séries et 1 452 234 mesures. ``ANALYZE`` en fin de migration.
``downgrade`` écrit l'audit par série de la suppression, puis supprime les
mesures (audit ligne à ligne suspendu), les séries et la source.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from kuma_data_core.db.seeds.audit_par_serie import (
    audit_ligne_suspendu,
    auditer_series,
    empreinte_fichier,
)
from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.pluie_imerg_civ import (
    CONTRAT_PLUIE_IMERG,
    LOT_PLUIE_IMERG,
    UNITE_REFERENTIEL,
)
from kuma_data_core.db.seeds.series_csv import lire_series_journalieres, nb_jours

# revision identifiers, used by Alembic.
revision: str = "0052"
down_revision: str | Sequence[str] | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVISION: str = "0052"
NB_POINTS: int = 142
NB_JOURS: int = 10_227  # 1998-01-01 → 2025-12-31
NB_MESURES_ATTENDU: int = 1_452_234  # 142 × 10 227

URL_POWER_SOURCES: str = "https://power.larc.nasa.gov/docs/methodology/data/sources/"
URL_POWER_VERSIONS: str = "https://power.larc.nasa.gov/docs/release-guide/"
URL_POWER_PARAMETRE: str = (
    "https://power.larc.nasa.gov/api/system/manager/parameters/IMERG_PRECTOT"
    "?community=RE&temporal=daily"
)
URL_GES_DISC: str = "https://disc.gsfc.nasa.gov/datacollection/GPM_3IMERGDF_07.html"
URL_DOC_TECHNIQUE: str = (
    "https://arthurhou.pps.eosdis.nasa.gov/Documents/IMERG_TechnicalDocumentation_final.pdf"
)
URL_NOTES_V07: str = (
    "https://gpm.nasa.gov/sites/default/files/2024-02/IMERG_V07_ReleaseNotes_240221.pdf"
)
URL_TRANSITION_V08: str = "https://gpm.nasa.gov/data/news/imerg-v08-transition-schedule"

SOURCE: dict[str, object] = {
    "id": CONTRAT_PLUIE_IMERG.source_id,
    "code": CONTRAT_PLUIE_IMERG.source_code,
    "titre": (
        "GPM IMERG V07 (Integrated Multi-satellitE Retrievals for GPM) — précipitations "
        "journalières 0,1°, Final Run (Late Run après le 2025-09-30), servies par "
        "NASA POWER (paramètre IMERG_PRECTOT)"
    ),
    "auteurs": ["Huffman, G.J.", "Stocker, E.F.", "Bolvin, D.T.", "Nelkin, E.J.", "Tan, J."],
    "organisation": (
        "NASA Goddard Space Flight Center (mission GPM, algorithme IMERG ; archive "
        "NASA GES DISC) ; service NASA POWER, NASA Langley Research Center"
    ),
    "type_source": "base_donnees",
    "annee_publication": 2023,
    "date_consultation": "2026-10-15",
    "url": "https://power.larc.nasa.gov/api/temporal/daily/point",
    "doi": "10.5067/GPM/IMERGDF/DAY/07",
    "fiabilite": "haute",
    "langue": "en",
    "metadonnees": {
        "acces": (
            "API REST NASA POWER, journalier ponctuel, gratuite et sans clé : "
            "parameters=IMERG_PRECTOT, community=RE, time-standard=UTC, format=JSON"
        ),
        "parametre_power": "IMERG_PRECTOT",
        "definition_power": "The average IMERG total precipitation at the surface of the earth.",
        "reponse_power": (
            'header.sources = ["IMERG"], time_standard = "UTC", fill_value = -999.0, '
            "unité mm/day, 2 décimales (POWER Daily API v2.10.0, sondage du 2026-10-15)"
        ),
        "granularite_spatiale": "0,1° × 0,1° (maille IMERG contenant le point demandé)",
        "granularite_temporelle": "journalier, jour UTC (POWER ne sert IMERG qu'ainsi)",
        "couverture_temporelle_debut": "1998-01-01",
        "fin_final_run_v07": "2025-09-30",
        "late_run": "à partir du 2025-10-01, d'après la documentation de POWER",
        "integration_power": "2025-03-04, version de données POWER 10.0.5 (« IMERG v7B »)",
        "calage_pluviometres": (
            "Final Run : mensuel, analyses GPCC Full Data (jusqu'en 2020) puis Monitoring, "
            "version 2022 d'après la documentation technique du 2023-07-13, corrigées du "
            "sous-captage ; Late Run : climatologique"
        ),
        "debut_documente_power": (
            "2001-01-01 selon la page des sources de POWER ; l'API sert pourtant depuis le "
            "1998-01-01, début du record IMERG V07 (CMR, GPM_3IMERGDF V07)"
        ),
        "produit_reference": "GPM_3IMERGDF V07 (GES DISC), DOI 10.5067/GPM/IMERGDF/DAY/07",
        "documentation": [
            URL_POWER_SOURCES,
            URL_POWER_VERSIONS,
            URL_POWER_PARAMETRE,
            URL_GES_DISC,
            URL_DOC_TECHNIQUE,
            URL_NOTES_V07,
            URL_TRANSITION_V08,
        ],
    },
    "notes": (
        "Précipitations IMERG V07 (Integrated Multi-satellitE Retrievals for GPM, NASA "
        "GSFC ; Huffman et al. 2023, GES DISC, DOI 10.5067/GPM/IMERGDF/DAY/07), servies par "
        "NASA POWER sous le paramètre IMERG_PRECTOT. Produit satellite multi-capteurs : "
        "micro-ondes passives calibrées sur l'algorithme combiné radar-radiomètre de TRMM "
        "(jusqu'en mai 2014) puis de GPM, infrarouge géostationnaire, morphing et filtre de "
        "Kalman, grille de 0,1°, pas demi-horaire. Le Final Run est calé mois par mois sur "
        "les pluviomètres du GPCC (Full Data jusqu'en 2020, Monitoring ensuite, corrigés du "
        "sous-captage) : chaque demi-heure est multipliée par un rapport mensuel "
        "borné à [0,2 ; 3], ce qui corrige le cumul sans toucher à l'occurrence des pluies. "
        "Le journalier est la moyenne des demi-heures du jour UTC × 24 ; la Côte d'Ivoire "
        "étant en UTC+0, c'est le jour civil local. POWER l'a intégré le 2025-03-04 "
        "(version de données 10.0.5, « IMERG v7B ») et ne le sert qu'en journalier UTC, "
        "depuis le 1998-01-01, début du record V07 (sa page des sources indique 2001-01-01). "
        "Le record Final V07 s'arrête au 2025-09-30 (passage des produits parents à V08, "
        "GPM 2026-04-28) ; d'après POWER, le Late Run prend la suite, sans calage mensuel "
        "sur les pluviomètres. Limites documentées (notes de version V07) : fréquence des "
        "extrêmes et des pluies un peu différente entre les ères de calage TRMM et GPM ; "
        "saut d'environ 10 % sur les terres tropicales en août 2001 dans l'algorithme "
        "combiné qui sert d'étalon (relèvement de l'orbite de TRMM) ; habileté moindre en "
        "zone côtière ; "
        "l'évolution de la constellation peut créer des artefacts dans les tendances "
        "pluriannuelles (GES DISC). L'en-tête du format CSV de POWER libelle à tort ce "
        "paramètre « MERRA-2 Total Precipitation » : la réponse JSON (sources IMERG) et le "
        "dictionnaire des paramètres font foi. Source des épisodes de pluie journaliers de "
        "Kuma (ADR-0032, ADR-0033). Consulté le 2026-10-15. Références demandées par "
        "POWER : « The data was obtained from National Aeronautics and Space "
        "Administration (NASA) Langley Research Center's Prediction Of Worldwide Energy "
        "Resources (POWER) project funded through the NASA Earth Science Division. » et "
        "« The data was obtained from the POWER Project's Daily 2.10.0 version on "
        "2026/10/15. »"
    ),
}

NOTE: str = (
    "Précipitations journalières IMERG V07 (NASA GPM, Huffman et al. ; estimation "
    "satellitaire multi-capteurs), servies par NASA POWER (paramètre IMERG_PRECTOT) : "
    "valeur de la maille 0,1° contenant la localité, jour UTC (jour civil local, UTC+0), "
    "en mm/jour à 2 décimales, telle que servie, 1998-2025. Final Run jusqu'au "
    "2025-09-30, calé mois par mois sur les pluviomètres GPCC (le calage corrige le "
    "cumul, pas l'occurrence des pluies) ; du 2025-10-01 au 2025-12-31, Late Run, sans "
    "calage mensuel sur les pluviomètres (fin du Final Run V07). Source des épisodes de "
    "pluie journaliers (lessivage : proxy de salissure, PR réaliste), à la place de la "
    "pluie NASA POWER PRECTOTCORR, dont les jours extrêmes sont fantômes et les fortes "
    "pluies en rupture en 2016-2017 (ADR-0032, ADR-0033). Recoupement en base aux 142 "
    "localités : aux 25 jours-localités où NASA POWER dépasse 200 mm, IMERG donne au plus "
    "59,4 mm le jour même et 107,9 mm sur trois jours ; ses jours-localités > 50 mm restent "
    "stables (325,5 par an en 1998-2015, 322,1 en 2017-2025, contre 22,4 puis 247,6 pour "
    "NASA). Limites documentées : calage sur TRMM jusqu'en mai 2014 puis sur GPM, avec une "
    "fréquence des extrêmes un peu différente entre les deux ères ; habileté moindre en "
    "zone côtière. Estimation satellitaire, jamais une mesure au sol. Confiance B."
)


def _codes_localites() -> list[str]:
    return sorted(code for code, _, _, _ in points_nationaux())


def _fichiers() -> dict[str, tuple[str, str]]:
    """Code de série → (CSV, empreinte SHA-256), pour l'audit par série."""
    contrat, lot = CONTRAT_PLUIE_IMERG, LOT_PLUIE_IMERG
    fichier = (contrat.nom_fichier(lot), empreinte_fichier(contrat, lot))
    return {contrat.code_serie(code): fichier for code in _codes_localites()}


def _recaler_sequence_sources(bind: sa.Connection) -> None:
    """Recale l'identité de ``sources`` sur le plus grand id présent.

    Les sources 16 (0012) et 17 (ici) sont insérées à id figé, sans faire avancer
    l'identité, restée à 15 depuis le seed 0002 : la prochaine source insérée sans
    id serait entrée en collision. Le recalage est idempotent.
    """
    bind.execute(
        sa.text(
            "SELECT setval(pg_get_serial_sequence('sources', 'id'), (SELECT MAX(id) FROM sources))"
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    contrat, lot = CONTRAT_PLUIE_IMERG, LOT_PLUIE_IMERG

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
            f"{UNITE_REFERENTIEL!r} attendue (valeurs servies en mm/day, sans conversion)."
        )
    if nb_jours(contrat) != NB_JOURS:
        raise RuntimeError(f"Migration {REVISION} : contrat de {nb_jours(contrat)} jours.")
    codes_loc = _codes_localites()
    if len(codes_loc) != NB_POINTS or len(set(codes_loc)) != NB_POINTS:
        raise RuntimeError(
            f"Migration {REVISION} : {len(codes_loc)} localités, {NB_POINTS} attendues."
        )
    loc = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM localites WHERE code = ANY(:c)"), {"c": codes_loc}
        ).all()
    }
    manquants = [c for c in codes_loc if c not in loc]
    if manquants:
        raise RuntimeError(f"Migration {REVISION} : localité(s) introuvable(s) : {manquants!r}.")
    codes_series = [contrat.code_serie(code) for code in codes_loc]
    preexistantes = bind.execute(
        sa.text(
            """
            SELECT code FROM series_metadonnees
            WHERE code = ANY(:codes)
               OR (source_id = :src AND granularite = 'journalier' AND grandeur_code = :g)
            """
        ),
        {"codes": codes_series, "src": contrat.source_id, "g": contrat.grandeur_code},
    ).all()
    if preexistantes:
        raise RuntimeError(
            f"Migration {REVISION} : séries déjà présentes : {[r.code for r in preexistantes]!r}."
        )

    # 1. Lecture validée du CSV (tous les jours civils, bornes, doublons, localités).
    series = lire_series_journalieres(contrat, lot)
    if [s["localite_code"] for s in series] != codes_loc:
        raise RuntimeError(
            f"Migration {REVISION} : {contrat.nom_fichier(lot)} ne couvre pas les "
            f"{NB_POINTS} localités."
        )

    # 2. Source à id figé (audit ligne à ligne de ``sources`` conservé).
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

    # 3. Séries journalières (audit ligne à ligne de ``series_metadonnees`` conservé).
    series_table = sa.table(
        "series_metadonnees",
        sa.column("code", sa.String),
        sa.column("libelle", sa.Text),
        sa.column("localite_id", sa.BigInteger),
        sa.column("grandeur_code", sa.String),
        sa.column("source_id", sa.BigInteger),
        sa.column("periode_debut", sa.Date),
        sa.column("periode_fin", sa.Date),
        sa.column("methode_collecte", sa.String),
        sa.column("granularite", sa.String),
        sa.column("note_publique", sa.Text),
    )
    op.bulk_insert(
        series_table,
        [
            {
                "code": s["code"],
                "libelle": s["libelle"],
                "localite_id": loc[s["localite_code"]],
                "grandeur_code": contrat.grandeur_code,
                "source_id": contrat.source_id,
                "periode_debut": contrat.periode_debut,
                "periode_fin": contrat.periode_fin,
                "methode_collecte": contrat.methode_collecte,
                "granularite": contrat.granularite,
                "note_publique": NOTE,
            }
            for s in series
        ],
    )
    serie_id = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": codes_series},
        ).all()
    }
    if len(serie_id) != NB_POINTS:
        raise RuntimeError(f"Migration {REVISION} : {len(serie_id)} séries, {NB_POINTS} attendues.")

    # 4. Mesures journalières par COPY, audit ligne à ligne de ``mesures_ressource``
    #    suspendu le temps de l'insertion.
    connexion = bind.connection.driver_connection  # psycopg 3 : COPY pour le volume
    with audit_ligne_suspendu(bind):
        with (
            connexion.cursor() as curseur,
            curseur.copy(
                "COPY mesures_ressource "
                "(serie_id, instant_mesure, valeur, statut, niveau_confiance_derive) "
                "FROM STDIN"
            ) as copie,
        ):
            for s in series:
                sid = serie_id[s["code"]]
                for jour, valeur in s["mesures"]:
                    copie.write_row((sid, jour, valeur, "brut", contrat.niveau_confiance))
        del series
        nb = bind.execute(
            sa.text("SELECT COUNT(*) FROM mesures_ressource WHERE serie_id = ANY(:ids)"),
            {"ids": list(serie_id.values())},
        ).scalar_one()
    if nb != NB_MESURES_ATTENDU:
        raise RuntimeError(f"Migration {REVISION} : {nb} mesures, {NB_MESURES_ATTENDU} attendues.")

    # 5. Une entrée d'audit par série (142), après l'insertion.
    auditer_series(bind, "I", REVISION, _fichiers())
    _recaler_sequence_sources(bind)
    bind.execute(sa.text("ANALYZE sources"))
    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE mesures_ressource"))


def downgrade() -> None:
    bind = op.get_bind()
    contrat = CONTRAT_PLUIE_IMERG
    presentes = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": [contrat.code_serie(code) for code in _codes_localites()]},
        ).all()
    }
    if presentes:
        fichiers = _fichiers()
        # Audit par série de la suppression, avant elle (comptes et bornes lus en base).
        auditer_series(bind, "D", REVISION, {c: fichiers[c] for c in presentes})
        ids = list(presentes.values())
        with audit_ligne_suspendu(bind):
            bind.execute(
                sa.text("DELETE FROM mesures_ressource WHERE serie_id = ANY(:ids)"), {"ids": ids}
            )
        bind.execute(sa.text("DELETE FROM series_metadonnees WHERE id = ANY(:ids)"), {"ids": ids})
    # La source n'est supprimée que si plus aucune série ne la référence (FK RESTRICT).
    bind.execute(
        sa.text("DELETE FROM sources WHERE id = :i AND code = :c"),
        {"i": contrat.source_id, "c": contrat.source_code},
    )
    _recaler_sequence_sources(bind)
    bind.execute(sa.text("ANALYZE sources"))
    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE mesures_ressource"))
