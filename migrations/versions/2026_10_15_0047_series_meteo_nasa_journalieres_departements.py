"""series_meteo_nasa_journalieres_departements

Revision ID: 0047
Revises: 0046
Create Date: 2026-10-15

**Météo journalière NASA POWER aux 108 départements** (ADR-0031) : les 6
grandeurs météorologiques journalières de la migration 0035 (ADR-0020), aux
mêmes contrats, étendues aux **108 départements** hors pilotes du lot
``departements`` (``journalier_departements_civ.points_journalier_departements``),
dans la table ``mesures_ressource`` (grain journalier, ``instant_mesure`` =
date). Contrats : ``journalier_departements_civ.CONTRATS_METEO_DEPARTEMENTS``
(= ``meteo_civ.CONTRATS_METEO_NASA_JOURNALIERS``).

| Grandeur | Paramètre NASA | Produit | Méthode | Période | Jours par série | Mesures |
|---|---|---|---|---|---:|---:|
| ``t2m`` | ``T2M`` | MERRA-2 | ``reanalyse`` | 1991-2025 | 12 784 | 1 380 672 |
| ``rh2m`` | ``RH2M`` | MERRA-2 | ``reanalyse`` | 1991-2025 | 12 784 | 1 380 672 |
| ``vent_2m`` | ``WS2M`` | MERRA-2 | ``reanalyse`` | 1991-2025 | 12 784 | 1 380 672 |
| ``vent_10m`` | ``WS10M`` | MERRA-2 | ``reanalyse`` | 1991-2025 | 12 784 | 1 380 672 |
| ``precipitation`` | ``PRECTOTCORR`` | MERRA-2 | ``reanalyse`` | 1991-2025 | 12 784 | 1 380 672 |
| ``albedo_surface`` | ``ALLSKY_SRF_ALB`` | CERES SYN1deg | ``modele_satellitaire`` | 2001-2025 | 9 131 | 986 148 |

Soit **648 séries** (``granularite='journalier'``) et **7 889 508 mesures**,
confiance **B**, source ``nasa_power`` (id 1). Valeurs dans l'unité servie,
qui est celle de la grandeur au référentiel (°C, %, m/s, mm/jour, sans
dimension ; vérifié ici) : aucune conversion. Aucune valeur de remplissage dans
les périodes gravées, albédo compris, aux 108 départements. Libellés et notes
publiques de 0035, lot « départements ».

**Pluie** : les 20 jours au-delà de 200 mm servis aux 108 départements
(``PLUIES_AU_DELA_DE_200_MM``, dont 15 en septembre 2022 ; 726,74 mm le
2022-09-16 à San-Pédro, 321,59 mm le 2025-12-02 à Ouangolodougou) sont gravés
tels quels, sous la borne journalière de 1000 mm/jour du contrat. La note
publique des 108 séries de pluie les cite tous, avec la rupture des fortes
pluies vers 2017 constatée sur ces départements : métadonnée seulement, aucune
valeur corrigée. La migration vérifie que les jours au-delà de 200 mm du CSV
sont exactement ceux que la note cite.

Valeurs lues hors-ligne dans les CSV gzip committés
(``seeds/donnees/nasa_power_<grandeur>_journalier_departements.csv.gz``,
générés par ``scripts/ingest_nasa_power_meteo_journalier.py --departements``)
et validées par ``series_csv.lire_series_journalieres`` (tous les jours civils,
bornes, doublons, localités). Insertion par ``COPY`` avec l'**audit par série**
(``audit_par_serie``) : l'audit ligne à ligne de ``mesures_ressource`` est
suspendu le temps de l'insertion, puis une entrée d'audit par série (code,
nombre de mesures, bornes, fichier et empreinte SHA-256, révision) est écrite ;
les séries elles-mêmes (``series_metadonnees``) gardent l'audit ligne à ligne.
Garde-fous : identité de la source, unités du référentiel, 108 localités, aucune
série préexistante (code ou série journalière NASA de même grandeur et localité,
qui rendrait ambiguë la résolution des compagnes), 108 séries et nombre de
mesures par grandeur, total. ``ANALYZE`` en fin de migration. ``downgrade``
écrit l'audit par série de la suppression, puis supprime les mesures (audit
ligne à ligne suspendu) et les séries.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.audit_par_serie import (
    audit_ligne_suspendu,
    auditer_series,
    empreinte_fichier,
)
from kuma_data_core.db.seeds.journalier_departements_civ import (
    CONTRATS_METEO_DEPARTEMENTS,
    LOT_JOURNALIER_DEPARTEMENTS,
    points_journalier_departements,
)
from kuma_data_core.db.seeds.localites_civ_seed_data import LOCALITES_SEED
from kuma_data_core.db.seeds.meteo_civ import PARAMETRES_METEO_NASA
from kuma_data_core.db.seeds.series_csv import ContratSerie, lire_series_journalieres, nb_jours

# revision identifiers, used by Alembic.
revision: str = "0047"
down_revision: str | Sequence[str] | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVISION: str = "0047"
SOURCE_ID: int = 1
SOURCE_CODE: str = "nasa_power"
NB_POINTS: int = 108
NB_MESURES_ATTENDU: int = 7_889_508  # 108 × (5 × 12 784 + 9 131)
SEUIL_PLUIE_EXTREME: float = 200.0  # mm/jour

# Unité de chaque grandeur au référentiel = unité servie par NASA POWER.
UNITES: dict[str, tuple[str, str]] = {
    "t2m": ("degree_celsius", "°C"),
    "rh2m": ("pourcent", "%"),
    "vent_2m": ("metre_par_seconde", "m/s"),
    "vent_10m": ("metre_par_seconde", "m/s"),
    "precipitation": ("mm_par_jour", "mm/jour"),
    "albedo_surface": ("sans_unite", "sans dimension"),
}
# Produit NASA POWER et nature de la confiance B, par méthode de collecte.
PRODUITS: dict[str, tuple[str, str]] = {
    "reanalyse": ("réanalyse MERRA-2", "réanalyse"),
    "modele_satellitaire": ("CERES SYN1deg", "satellite"),
}

# Jours au-delà de 200 mm servis par NASA POWER aux 108 départements, 1991-2025
# (constat de l'ingestion du 2026-10-15, vérifié sur le CSV par la migration) :
# (localité, jour, mm), par groupe de la mise en garde.
PLUIES_SEPTEMBRE_2022: tuple[tuple[str, str, float], ...] = (
    ("civ_dep_san_pedro", "2022-09-16", 726.74),
    ("civ_dep_sassandra", "2022-09-16", 710.75),
    ("civ_dep_meagui", "2022-09-16", 380.24),
    ("civ_dep_gueyo", "2022-09-16", 345.5),
    ("civ_dep_fresco", "2022-09-16", 281.72),
    ("civ_dep_tai", "2022-09-23", 403.43),
    ("civ_dep_duekoue", "2022-09-23", 329.59),
    ("civ_dep_guiglo", "2022-09-23", 329.59),
    ("civ_dep_blolequin", "2022-09-23", 286.94),
    ("civ_dep_toulepleu", "2022-09-23", 286.94),
    ("civ_dep_buyo", "2022-09-23", 248.92),
    ("civ_dep_soubre", "2022-09-23", 248.92),
    ("civ_dep_meagui", "2022-09-23", 226.83),
    ("civ_dep_madinani", "2022-09-26", 202.19),
    ("civ_dep_seguelon", "2022-09-26", 202.19),
)
PLUIES_NORD_HORS_SAISON: tuple[tuple[str, str, float], ...] = (
    ("civ_dep_tehini", "2023-03-17", 288.76),
    ("civ_dep_ouangolodougou", "2025-12-02", 321.59),
)
PLUIES_TABOU_2024: tuple[tuple[str, str, float], ...] = (
    ("civ_dep_tabou", "2024-09-27", 263.99),
    ("civ_dep_tabou", "2024-10-13", 240.19),
    ("civ_dep_tabou", "2024-10-22", 213.46),
)
PLUIES_AU_DELA_DE_200_MM: tuple[tuple[str, str, float], ...] = (
    PLUIES_SEPTEMBRE_2022 + PLUIES_NORD_HORS_SAISON + PLUIES_TABOU_2024
)

_NOMS: dict[str, str] = {e["code"]: e["nom"] for e in LOCALITES_SEED}


def _jours(pluies: tuple[tuple[str, str, float], ...]) -> str:
    """« 726,74 mm à San-Pédro le 2022-09-16, … » : forme relue par les tests."""
    return ", ".join(
        f"{f'{mm:.2f}'.replace('.', ',')} mm à {_NOMS[code]} le {jour}" for code, jour, mm in pluies
    )


MISE_EN_GARDE_PLUIE: str = (
    " Mise en garde : valeurs aberrantes probables servies par NASA POWER, gravées "
    f"sans correction. Les {len(PLUIES_AU_DELA_DE_200_MM)} seuls jours au-delà de 200 mm "
    "(1991-2025, 108 départements) : en septembre 2022, dans l'ouest, le sud-ouest et "
    f"le nord-ouest, {_jours(PLUIES_SEPTEMBRE_2022)} ; au nord, hors saison des pluies, "
    f"{_jours(PLUIES_NORD_HORS_SAISON)} ; dans le sud-ouest en 2024, "
    f"{_jours(PLUIES_TABOU_2024)}. Septembre 2022 est le septembre le plus pluvieux de "
    "1991-2025 dans 68 des 108 départements. Sur les 108 départements, les jours > 50 mm "
    "passent de 16,1 par an en 1991-2015 à 192,0 en 2017-2025, en hausse dans chacun "
    "d'eux. Fortes pluies à recouper avec ERA5 (ADR-0020, ADR-0031)."
)


def _note(grandeur: str, contrat: ContratSerie) -> str:
    parametre, methode, _, libelle, _, _ = PARAMETRES_METEO_NASA[grandeur]
    produit, nature = PRODUITS[methode]
    note = (
        f"{libelle} journalier NASA POWER ({parametre}, {produit}), {UNITES[grandeur][1]}, "
        f"{contrat.annee_debut}-{contrat.annee_fin}, sans conversion. Lot national "
        "« départements » (108 départements hors pilotes, ADR-0031) ; la moyenne des jours "
        "du mois redonne la série mensuelle NASA (à l'arrondi près). "
        f"Confiance B ({nature})."
    )
    return note + MISE_EN_GARDE_PLUIE if grandeur == "precipitation" else note


def _codes_series() -> list[str]:
    codes = [code for code, _, _, _ in points_journalier_departements()]
    return [c.code_serie(code) for c in CONTRATS_METEO_DEPARTEMENTS.values() for code in codes]


def _fichiers() -> dict[str, tuple[str, str]]:
    """Code de série → (CSV, empreinte SHA-256), pour l'audit par série."""
    codes = [code for code, _, _, _ in points_journalier_departements()]
    fichiers: dict[str, tuple[str, str]] = {}
    for contrat in CONTRATS_METEO_DEPARTEMENTS.values():
        nom = contrat.nom_fichier(LOT_JOURNALIER_DEPARTEMENTS)
        empreinte = empreinte_fichier(contrat, LOT_JOURNALIER_DEPARTEMENTS)
        fichiers.update({contrat.code_serie(code): (nom, empreinte) for code in codes})
    return fichiers


def upgrade() -> None:
    bind = op.get_bind()
    contrats = CONTRATS_METEO_DEPARTEMENTS
    lot = LOT_JOURNALIER_DEPARTEMENTS

    # 0. Garde-fous : source, unités du référentiel, localités, séries préexistantes.
    code_source = bind.execute(
        sa.text("SELECT code FROM sources WHERE id = :i"), {"i": SOURCE_ID}
    ).scalar_one_or_none()
    if code_source != SOURCE_CODE:
        raise RuntimeError(
            f"Migration {REVISION} : source id {SOURCE_ID} = {code_source!r}, "
            f"{SOURCE_CODE!r} attendue."
        )
    unites = {
        row.grandeur: row.unite
        for row in bind.execute(
            sa.text(
                "SELECT g.code AS grandeur, u.code AS unite FROM grandeurs_referentiel g "
                "JOIN unites u ON u.id = g.unite_id WHERE g.code = ANY(:g) AND g.actif"
            ),
            {"g": list(contrats)},
        ).all()
    }
    attendues = {g: u for g, (u, _) in UNITES.items()}
    if unites != attendues:
        raise RuntimeError(f"Migration {REVISION} : unités {unites!r}, {attendues!r} attendues.")
    codes_loc = sorted(code for code, _, _, _ in points_journalier_departements())
    if len(codes_loc) != NB_POINTS:
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
    preexistantes = bind.execute(
        sa.text(
            """
            SELECT code FROM series_metadonnees
            WHERE code = ANY(:codes)
               OR (source_id = :src AND granularite = 'journalier'
                   AND grandeur_code = ANY(:g) AND localite_id = ANY(:loc))
            """
        ),
        {
            "codes": _codes_series(),
            "src": SOURCE_ID,
            "g": list(contrats),
            "loc": list(loc.values()),
        },
    ).all()
    if preexistantes:
        raise RuntimeError(
            f"Migration {REVISION} : séries déjà présentes : {[r.code for r in preexistantes]!r}."
        )

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
    connexion = bind.connection.driver_connection  # psycopg 3 : COPY pour le volume
    total = 0
    # Audit ligne à ligne de ``mesures_ressource`` suspendu le temps de l'insertion
    # (les séries, dans ``series_metadonnees``, restent auditées ligne à ligne).
    with audit_ligne_suspendu(bind):
        for grandeur, contrat in contrats.items():
            series = lire_series_journalieres(contrat, lot)
            if sorted(s["localite_code"] for s in series) != codes_loc:
                raise RuntimeError(
                    f"Migration {REVISION} : {contrat.nom_fichier(lot)} ne couvre pas le lot."
                )
            if grandeur == "precipitation":
                extremes = {
                    (s["localite_code"], jour.isoformat(), valeur)
                    for s in series
                    for jour, valeur in s["mesures"]
                    if valeur > SEUIL_PLUIE_EXTREME
                }
                cites = set(PLUIES_AU_DELA_DE_200_MM)
                if extremes != cites or len(cites) != len(PLUIES_AU_DELA_DE_200_MM):
                    raise RuntimeError(
                        f"Migration {REVISION} : jours > 200 mm du CSV "
                        f"{sorted(extremes ^ cites)!r} absents de la note ou en trop."
                    )

            # 1. Séries journalières.
            op.bulk_insert(
                series_table,
                [
                    {
                        "code": s["code"],
                        "libelle": s["libelle"],
                        "localite_id": loc[s["localite_code"]],
                        "grandeur_code": contrat.grandeur_code,
                        "source_id": SOURCE_ID,
                        "periode_debut": contrat.periode_debut,
                        "periode_fin": contrat.periode_fin,
                        "methode_collecte": contrat.methode_collecte,
                        "granularite": contrat.granularite,
                        "note_publique": _note(grandeur, contrat),
                    }
                    for s in series
                ],
            )
            serie_id = {
                row.code: row.id
                for row in bind.execute(
                    sa.text("SELECT code, id FROM series_metadonnees WHERE code = ANY(:c)"),
                    {"c": [s["code"] for s in series]},
                ).all()
            }

            # 2. Mesures journalières, par COPY.
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

            nb = bind.execute(
                sa.text("SELECT COUNT(*) FROM mesures_ressource WHERE serie_id = ANY(:ids)"),
                {"ids": list(serie_id.values())},
            ).scalar_one()
            attendu = NB_POINTS * nb_jours(contrat)
            if len(serie_id) != NB_POINTS or nb != attendu:
                raise RuntimeError(
                    f"Migration {REVISION} : {grandeur} : {len(serie_id)} séries et {nb} "
                    f"mesures, {NB_POINTS} et {attendu} attendues."
                )
            total += nb
            del series

    if total != NB_MESURES_ATTENDU:
        raise RuntimeError(
            f"Migration {REVISION} : {total} mesures, {NB_MESURES_ATTENDU} attendues."
        )
    # 3. Une entrée d'audit par série (648), après l'insertion.
    auditer_series(bind, "I", REVISION, _fichiers())
    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE mesures_ressource"))


def downgrade() -> None:
    bind = op.get_bind()
    presentes = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": _codes_series()},
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
    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE mesures_ressource"))
