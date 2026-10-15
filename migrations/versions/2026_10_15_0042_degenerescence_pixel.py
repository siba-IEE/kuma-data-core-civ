"""degenerescence_pixel

Revision ID: 0042
Revises: 0041
Create Date: 2026-10-15

**Dégénérescence de pixel** (grandeur ``degenerescence_pixel``, id 34) — la
couche d'honnêteté spatiale (ADR-0027). Pour chaque série mensuelle **brute**
(une localité, une source, une grandeur), compte les **autres localités** dont
la série de même source et même grandeur est **strictement identique**, mois
par mois, sur sa période : des « jumeaux de pixel ». Règle du service hérité
(``services/grandeurs/degenerescence_pixel.py``), égalité exacte, **aucune
définition de grille** : sur une grille fixe (NASA POWER, CERES 1°), les points
d'une même cellule lisent la même valeur ; sur un service au point (SARAH-3,
CAMS, ERA5 via PVGIS), seuls des points confondus partagent une série.

**Familles détectées en base** : toutes les familles (source, grandeur) de
séries ``granularite = 'mensuel'`` hors calculs Kuma présentes quand la
migration s'exécute. Les 10 familles de rayonnement (NASA GHI/DNI/DHI, SARAH-3
GHI/DNI, ERA5 GHI/DNI, CAMS GHI/DNI/DHI) sont **exigées** aux 142 localités ;
toute autre famille (météo NASA, CAMS EAC4…) est traitée si elle est présente,
à condition que sa maille figure au catalogue ``MAILLES`` (sinon arrêt).

Une ligne ``grandeurs_metier`` par série : ``periode_type = 'statique'``,
années = période de la série, ``valeur`` = nombre de jumeaux (0 = aucun),
confiance B, FK ``series_metadonnees_id`` vers la **série brute** elle-même
(c'est ce que lit l'API ``incertitude_inter_source``). Le groupe de jumeaux,
la distinction « coordonnées distinctes / identiques » et le caveat de
résolution vont dans ``commentaire_editorial``. Rayonnement : **1420 lignes**.

La grandeur passe de ``calculee_volee`` à ``stockee`` (ADR-0009 : ce qui vit
dans ``grandeurs_metier`` est ``stockee``) ; sa description est réécrite pour
le dire. Le compte dépend du périmètre : toute migration qui ajoute ou retire
des localités à une famille, ou modifie ses mesures, doit le recalculer.

Garde-fous : aucune ligne préexistante, grandeur dans l'état hérité, familles
exigées complètes (142 localités, période et nombre de mois du contrat), une
seule série par (localité, famille), maille connue, comptes exacts, valeurs
dans ``[0, n − 1]``. ``ANALYZE grandeurs_metier`` en fin de migration.
``downgrade`` supprime les lignes et restaure la grandeur.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any, NamedTuple

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.lots_civ import CONTRATS_MENSUELS, FIN_EXTENSION, points_nationaux

# revision identifiers, used by Alembic.
revision: str = "0042"
down_revision: str | Sequence[str] | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANDEUR_CODE: str = "degenerescence_pixel"
GRANDEUR_ID: int = 34
NB_POINTS: int = 142
NB_LIGNES_RAYONNEMENT: int = 1_420  # 10 familles × 142 localités


class Maille(NamedTuple):
    """Maille annoncée d'une famille (source, grandeur), pour le commentaire."""

    source: str  # libellé de la source
    description: str  # maille ou mode de service, tel qu'annoncé par la source


_NASA_CERES = Maille("NASA POWER", "grille CERES SYN1deg de 1° × 1°, environ 110 km")
_NASA_MERRA2 = Maille("NASA POWER", "grille MERRA-2 de 0,5° × 0,625°, environ 55 × 70 km")

# Catalogue des mailles annoncées (métadonnées des sources, ADR-0010, ADR-0011).
# Clé (source, grandeur) quand la grille dépend du paramètre (NASA POWER : CERES
# pour le rayonnement et l'albédo, MERRA-2 pour la météo), sinon (source, None)
# pour toutes les grandeurs de la source. Une famille absente arrête la migration.
# Pour couvrir une nouvelle famille mensuelle : ajouter son entrée ici si sa
# migration précède celle-ci ; sinon, graver ses lignes dans une migration
# ultérieure selon la même règle (ADR-0027).
MAILLES: dict[tuple[str, str | None], Maille] = {
    **{("nasa_power", g): _NASA_CERES for g in ("ghi", "dni", "dhi", "kt", "albedo_surface")},
    **{
        ("nasa_power", g): _NASA_MERRA2
        for g in ("t2m", "rh2m", "vent_2m", "vent_10m", "precipitation")
    },
    ("sarah3_monthly", None): Maille(
        "SARAH-3 (PVGIS)", "service au point PVGIS-SARAH3, résolution native d'environ 5 km"
    ),
    ("era5_pvgis", None): Maille(
        "ERA5 (PVGIS)", "réanalyse ERA5 de 0,25° (environ 28 km), servie au point par PVGIS"
    ),
    ("cams_radiation", None): Maille(
        "CAMS Radiation",
        "service au point CAMS Radiation (Heliosat-4, pixel Meteosat de 3 à 5 km)",
    ),
    ("cams_eac4", None): Maille("CAMS EAC4", "réanalyse CAMS EAC4 de 0,75°, environ 80 km"),
    ("ecmwf_era5", None): Maille("ERA5 (CDS)", "réanalyse ERA5 de 0,25°, environ 28 km"),
    ("ecmwf_era5_land", None): Maille(
        "ERA5-Land (CDS)", "réanalyse ERA5-Land servie sur grille de 0,1°, environ 11 km"
    ),
}


def maille(source: str, grandeur: str) -> Maille | None:
    """Maille d'une famille : entrée (source, grandeur), à défaut celle de la source."""
    return MAILLES.get((source, grandeur)) or MAILLES.get((source, None))


# Description héritée (0002), restaurée par le downgrade.
STRATEGIE_HERITEE: str = "calculee_volee"
DESCRIPTION_HERITEE: str = (
    "Indicateur d'honnetete structurelle de l'atlas : pour une (localite, source, parametre), "
    "nombre d'autres points partageant la meme cellule source (0 = point reellement resolu). "
    "Detection empirique par identite de series climato mensuelles sur grille fixe (NASA "
    "radiation CERES 1deg, meteo MERRA 0.5deg). Services interpoles (SARAH-3 / CAMS 5 km) : "
    "compte 0 + caveat de resolution. F1 calculee_volee, materialisee statique, confiance B "
    "(A reservee aux mesures terrain ; exactitude dite par caveat, pas par une remontee en A)."
)
DESCRIPTION: str = (
    "Dégénérescence de pixel : pour une série mensuelle brute (localité, source, grandeur), "
    "nombre d'autres localités dont la série de même source et même grandeur est strictement "
    "identique, mois par mois, sur sa période (0 = aucune). Détection empirique, sans "
    "définition de grille : sur une grille fixe (NASA POWER, CERES 1°), les points d'une même "
    "cellule lisent la même valeur ; sur un service au point (SARAH-3, CAMS, ERA5 via PVGIS), "
    "seuls des points confondus partagent une série. Dépend du périmètre (les localités "
    "portant la famille) : matérialisée statique dans grandeurs_metier, une ligne par série "
    "brute, recalculée par toute migration qui change ce périmètre. strategie_calcul=stockee "
    "(ADR-0027, ADR-0009). Confiance B (A réservée aux mesures terrain). Famille F1."
)

CAVEAT: str = (
    "Indicateur exact (identité observée, non modélisée), confiance B : A est réservée aux "
    "mesures terrain. Compte établi sur les localités portant cette famille ; il change avec "
    "le périmètre (ADR-0027)."
)

# Une ligne par série mensuelle brute : vecteur (année·100 + mois, valeur) des
# mesures courantes, dans l'ordre chronologique.
_SQL_VECTEURS: str = """
    SELECT x.code AS source, s.grandeur_code, s.id AS serie_id, s.code AS serie_code,
           l.id AS localite_id, l.code AS localite, l.latitude, l.longitude,
           s.periode_debut, s.periode_fin,
           COUNT(m.serie_id) AS nb_mois,
           array_agg(m.annee * 100 + m.mois ORDER BY m.annee, m.mois)
               FILTER (WHERE m.serie_id IS NOT NULL) AS cles,
           array_agg(m.valeur ORDER BY m.annee, m.mois)
               FILTER (WHERE m.serie_id IS NOT NULL) AS valeurs
    FROM series_metadonnees s
    JOIN sources x ON x.id = s.source_id
    JOIN localites l ON l.id = s.localite_id
    LEFT JOIN mesures_ressource_mensuelles m
        ON m.serie_id = s.id AND m.valide_au IS NULL AND m.statut <> 'deprecie'
    WHERE s.granularite = 'mensuel' AND x.code <> 'kuma_calculs'
      AND s.methode_collecte IS DISTINCT FROM 'calcul_derive'
    GROUP BY x.code, s.id, l.id
    ORDER BY x.code, s.grandeur_code, l.code
"""


def _liste(codes: list[str]) -> str:
    return ", ".join(codes)


def _commentaire(
    maille: Maille, serie: Any, nb_famille: int, distincts: list[str], confondus: list[str]
) -> str:
    """Groupe de jumeaux (coordonnées distinctes / identiques) ou caveat de résolution."""
    periode = (
        f"série mensuelle {serie.grandeur_code} {maille.source} "
        f"({serie.periode_debut.year}-{serie.periode_fin.year}, {serie.nb_mois} mois)"
    )
    autres = nb_famille - 1
    nb = len(distincts) + len(confondus)
    if nb == 0:
        phrases = [
            f"{periode[0].upper()}{periode[1:]} : aucune des {autres} autres localités du "
            "périmètre n'a une série identique.",
            f"Un compte nul ne vaut pas résolution au point : {maille.description}.",
        ]
    else:
        phrases = [
            f"{periode[0].upper()}{periode[1:]} strictement identique, mois par mois, à celle "
            f"de {nb} des {autres} autres localités du périmètre."
        ]
        if distincts:
            phrases.append(
                f"À des coordonnées distinctes ({len(distincts)}) : {_liste(distincts)} ; la "
                f"source ne distingue pas ces points ({maille.description}) : ne pas présenter "
                "leurs valeurs comme des mesures indépendantes."
            )
        if confondus:
            phrases.append(
                f"Aux mêmes coordonnées ({len(confondus)}) : {_liste(confondus)} ; même point, "
                "série identique par construction."
            )
    phrases.append(CAVEAT)
    return " ".join(phrases)


def _verifier_grandeur(bind: sa.engine.Connection, strategie: str, description: str) -> None:
    row = bind.execute(
        sa.text(
            "SELECT id, strategie_calcul, description, version_formule_actuelle "
            "FROM grandeurs_referentiel WHERE code = :c"
        ),
        {"c": GRANDEUR_CODE},
    ).one()
    if (row.id, row.strategie_calcul, row.description, row.version_formule_actuelle) != (
        GRANDEUR_ID,
        strategie,
        description,
        1,
    ):
        raise RuntimeError(f"Migration 0042 : grandeur {GRANDEUR_CODE!r} hors état attendu.")


def _verifier_familles_exigees(familles: dict[tuple[str, str], list[Any]]) -> None:
    """Les 10 familles de rayonnement, complètes aux 142 localités et à leur période."""
    localites = sorted(code for code, _, _, _ in points_nationaux())
    if len(localites) != NB_POINTS:
        raise RuntimeError(f"Migration 0042 : {len(localites)} localités, {NB_POINTS} attendues.")
    for contrat in CONTRATS_MENSUELS:
        cle = (contrat.source_code, contrat.grandeur_code)
        fin = FIN_EXTENSION[contrat.source_code]
        series = familles.get(cle, [])
        if sorted(s.localite for s in series) != localites:
            raise RuntimeError(f"Migration 0042 : famille {cle!r} incomplète ({len(series)}).")
        nb_mois = (fin - contrat.annee_debut + 1) * 12
        for s in series:
            if (s.periode_debut.year, s.periode_fin.year, s.nb_mois) != (
                contrat.annee_debut,
                fin,
                nb_mois,
            ):
                raise RuntimeError(f"Migration 0042 : série {s.serie_code!r} hors contrat.")


def upgrade() -> None:
    bind = op.get_bind()
    deja = bind.execute(
        sa.text("SELECT COUNT(*) FROM grandeurs_metier WHERE grandeur_code = :c"),
        {"c": GRANDEUR_CODE},
    ).scalar_one()
    if deja:
        raise RuntimeError(f"Migration 0042 : {deja} ligne(s) {GRANDEUR_CODE!r} préexistante(s).")
    _verifier_grandeur(bind, STRATEGIE_HERITEE, DESCRIPTION_HERITEE)

    familles: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for row in bind.execute(sa.text(_SQL_VECTEURS)).all():
        familles[(row.source, row.grandeur_code)].append(row)
    mailles = {cle: m for cle in familles if (m := maille(*cle)) is not None}
    inconnues = sorted(set(familles) - set(mailles))
    if inconnues:
        raise RuntimeError(
            f"Migration 0042 : famille(s) mensuelle(s) sans maille au catalogue : {inconnues!r} "
            "(compléter MAILLES, ADR-0027)."
        )
    for cle, series in familles.items():
        if len({s.localite for s in series}) != len(series):
            raise RuntimeError(f"Migration 0042 : famille {cle!r} : plusieurs séries par localité.")
        for s in series:
            if not s.nb_mois or s.periode_fin is None:
                raise RuntimeError(f"Migration 0042 : série {s.serie_code!r} vide ou ouverte.")
    _verifier_familles_exigees(familles)

    lignes: list[dict[str, Any]] = []
    for cle, series in sorted(familles.items()):
        maille_famille = mailles[cle]
        # Égalité exacte du vecteur (mois, valeur) : les jumeaux d'une famille.
        groupes: dict[tuple[tuple[int, ...], tuple[float, ...]], list[Any]] = defaultdict(list)
        for s in series:
            groupes[(tuple(s.cles), tuple(s.valeurs))].append(s)
        for membres in groupes.values():
            for s in membres:
                jumeaux = [j for j in membres if j.serie_id != s.serie_id]
                point = (s.latitude, s.longitude)
                distincts = sorted(
                    j.localite for j in jumeaux if (j.latitude, j.longitude) != point
                )
                confondus = sorted(
                    j.localite for j in jumeaux if (j.latitude, j.longitude) == point
                )
                lignes.append(
                    {
                        "grandeur_code": GRANDEUR_CODE,
                        "localite_id": s.localite_id,
                        "series_metadonnees_id": s.serie_id,
                        "periode_type": "statique",
                        "annee_debut": s.periode_debut.year,
                        "annee_fin": s.periode_fin.year,
                        "mois": None,
                        "version_formule": 1,
                        "valeur": float(len(jumeaux)),
                        "niveau_confiance_derive": "B",
                        "commentaire_editorial": _commentaire(
                            maille_famille, s, len(series), distincts, confondus
                        ),
                    }
                )

    nb_series = sum(len(series) for series in familles.values())
    if len(lignes) != nb_series:
        raise RuntimeError(f"Migration 0042 : {len(lignes)} lignes, {nb_series} séries.")
    op.bulk_insert(
        sa.table(
            "grandeurs_metier",
            sa.column("grandeur_code", sa.String),
            sa.column("localite_id", sa.BigInteger),
            sa.column("series_metadonnees_id", sa.BigInteger),
            sa.column("periode_type", sa.String),
            sa.column("annee_debut", sa.Integer),
            sa.column("annee_fin", sa.Integer),
            sa.column("mois", sa.Integer),
            sa.column("version_formule", sa.Integer),
            sa.column("valeur", sa.Float),
            sa.column("niveau_confiance_derive", sa.String),
            sa.column("commentaire_editorial", sa.Text),
        ),
        lignes,
    )

    comptes = {
        (row.source, row.grandeur_code): (row.nb, row.vmin, row.vmax, row.n_famille)
        for row in bind.execute(
            sa.text(
                """
                SELECT x.code AS source, s.grandeur_code, COUNT(*) AS nb,
                       MIN(gm.valeur) AS vmin, MAX(gm.valeur) AS vmax,
                       COUNT(DISTINCT s.localite_id) AS n_famille
                FROM grandeurs_metier gm
                JOIN series_metadonnees s ON s.id = gm.series_metadonnees_id
                JOIN sources x ON x.id = s.source_id
                WHERE gm.grandeur_code = :c
                GROUP BY x.code, s.grandeur_code
                """
            ),
            {"c": GRANDEUR_CODE},
        ).all()
    }
    if set(comptes) != set(familles):
        raise RuntimeError(f"Migration 0042 : familles gravées {sorted(comptes)!r}.")
    for cle, (nb, vmin, vmax, n_famille) in comptes.items():
        if nb != len(familles[cle]) or nb != n_famille or vmin < 0 or vmax > nb - 1:
            raise RuntimeError(f"Migration 0042 : famille {cle!r} : {nb} lignes, [{vmin}, {vmax}].")
    rayonnement = sum(comptes[(c.source_code, c.grandeur_code)][0] for c in CONTRATS_MENSUELS)
    if rayonnement != NB_LIGNES_RAYONNEMENT:
        raise RuntimeError(
            f"Migration 0042 : {rayonnement} lignes de rayonnement, {NB_LIGNES_RAYONNEMENT} "
            "attendues."
        )

    bind.execute(
        sa.text(
            "UPDATE grandeurs_referentiel SET strategie_calcul = 'stockee', description = :d "
            "WHERE code = :c"
        ),
        {"d": DESCRIPTION, "c": GRANDEUR_CODE},
    )
    bind.execute(sa.text("ANALYZE grandeurs_metier"))


def downgrade() -> None:
    bind = op.get_bind()
    _verifier_grandeur(bind, "stockee", DESCRIPTION)
    bind.execute(
        sa.text("DELETE FROM grandeurs_metier WHERE grandeur_code = :c"), {"c": GRANDEUR_CODE}
    )
    bind.execute(
        sa.text(
            "UPDATE grandeurs_referentiel SET strategie_calcul = :s, description = :d "
            "WHERE code = :c"
        ),
        {"s": STRATEGIE_HERITEE, "d": DESCRIPTION_HERITEE, "c": GRANDEUR_CODE},
    )
