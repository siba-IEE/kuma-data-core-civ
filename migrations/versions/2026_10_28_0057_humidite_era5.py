"""humidite_era5

Revision ID: 0057
Revises: 0056
Create Date: 2026-10-28

**Humidité relative à 2 m ERA5 (CDS Copernicus), journalière et mensuelle, aux
142 localités** : deuxième source de ``rh2m``, à côté de NASA POWER (réanalyse
MERRA-2, 0034, 0035 et 0047). ERA5 ne sert pas d'humidité relative au sol ;
l'ADR-0021 s'était abstenu de la recalculer depuis des moyennes de T et de Td,
biaisées (−1,77 point aux pilotes), et avait laissé ouverte la voie horaire,
seule sans biais par construction. C'est elle qui est gravée ici (ADR-0038).

| Granularité | Valeur | Période | Par série | Mesures |
|---|---|---|---:|---:|
| journalier | moyenne des 24 humidités horaires 00 h → 23 h du jour UTC | 1991-2025 | 12 784 jours | 1 815 328 |
| mensuel | moyenne des humidités horaires du mois | 1991-2025 | 420 mois | 59 640 |

Humidité horaire : ``HR = 100 · e_sat(Td) / e_sat(T)`` (formule d'ECMWF, Tetens
sur l'eau : 611,21 Pa, 17,502, 32,19 K), depuis ``2m_temperature`` et
``2m_dewpoint_temperature`` horaires lues nœud par nœud dans le jeu
``reanalysis-era5-single-levels-timeseries``, au point de grille 0,25° le plus
proche (**même maille que 0036, 0050 et 0053**, 110 mailles pour 142
localités). Aucune valeur écrêtée.

Soit **284 séries** ``ecmwf_era5_rh2m_<journalier|mensuel>_<localité>`` et
**1 874 968 mesures**, source ``ecmwf_era5`` (id 2), méthode ``reanalyse``,
confiance **B**, unité ``pourcent``. Contrats : ``humidite_era5_civ``. Aucune
nouvelle source, grandeur, unité ni valeur d'énumération.

Recoupements (``scripts/ingest_era5_cds_humidite.py``) : la température moyenne
de chaque jour, recalculée depuis les mêmes fichiers, redonne le journalier ERA5
gravé (0053) à 0,0001 °C près ; la moyenne des jours de chaque mois redonne le
mensuel à l'arrondi près. Face à NASA POWER (MERRA-2), ERA5 est plus humide de
1,52 point en moyenne au jour le jour (de −2,85 à Duékoué à +5,66 à Touba),
surtout de décembre à février (+5,03) : chiffres publiés dans ``NOTES``.

Valeurs lues hors-ligne dans les CSV gzip committés
(``seeds/donnees/ecmwf_era5_rh2m_<journalier|mensuel>_civ142.csv.gz``) et
validées par ``series_csv``. Journalier inséré par ``COPY`` avec l'**audit par
série** (``gravure_journaliere``, ADR-0031) ; mensuel inséré comme en 0036,
audité ligne à ligne.

**Dégénérescence de pixel** (ADR-0027) : toute série mensuelle brute porte une
ligne ``degenerescence_pixel``. La famille mensuelle étant gravée après 0042,
ses 142 lignes sont gravées ici selon la règle de 0042 (égalité exacte des
séries, même commentaire, maille ERA5 du CDS) ; même maille que la température
ERA5 mensuelle, donc mêmes comptes de jumeaux, ce que la migration exige.

Garde-fous : identité de la source, unité du référentiel, 142 localités,
**aucune série ERA5 ``rh2m`` préexistante**, couverture exacte des CSV, comptes
de séries, de mesures et de jumeaux. ``ANALYZE`` en fin de migration.
``downgrade`` supprime la dégénérescence, le journalier (audit par série) puis
le mensuel.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.gravure_journaliere import graver_lot, supprimer_lot
from kuma_data_core.db.seeds.humidite_era5_civ import (
    CONTRAT_HUMIDITE_ERA5_JOURNALIER,
    CONTRAT_HUMIDITE_ERA5_MENSUEL,
    GRANDEUR,
    LOT_HUMIDITE_ERA5,
)
from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.series_csv import ContratSerie, lire_series

# revision identifiers, used by Alembic.
revision: str = "0057"
down_revision: str | Sequence[str] | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVISION: str = "0057"
SOURCE_ID: int = 2
SOURCE_CODE: str = "ecmwf_era5"
UNITE: str = "pourcent"
NB_POINTS: int = 142
NB_MESURES_JOURNALIERES: int = 1_815_328  # 142 × 12 784
NB_MESURES_MENSUELLES: int = 59_640  # 142 × 420

ATTRIBUTION: str = (
    "Attribution : contient des informations modifiées du Copernicus Climate Change Service (2026)."
)
_METHODE: str = (
    "humidité relative de chaque heure calculée depuis la température et le point de "
    "rosée à 2 m horaires (formule d'ECMWF, pression de vapeur saturante de Tetens sur "
    "l'eau), puis moyennée"
)
NOTES: dict[str, str] = {
    "journalier": (
        "Humidité relative à 2 m journalière ERA5 (réanalyse ECMWF, Copernicus C3S ; "
        f"valeurs horaires du CDS, jeu reanalysis-era5-single-levels) : {_METHODE} sur les "
        "24 heures datées de 00 h à 23 h du jour civil UTC (jour civil local, UTC+0), en %. "
        "Point de grille 0,25° le plus proche, 1991-2025, même maille que la température "
        "journalière ERA5 (0053). Face à l'humidité journalière NASA POWER (MERRA-2) aux "
        "mêmes localités, ERA5 est plus humide de 1,52 point en moyenne sur 1991-2025 "
        "(76,42 contre 74,90 % ; de −2,85 points à Duékoué à +5,66 points à Touba selon la "
        "localité), surtout en saison sèche (+5,03 points de décembre à février, −0,29 de "
        "juin à août), avec 6,04 points d'écart absolu moyen au jour le jour. Confiance B "
        "(réanalyse) ; jamais une mesure au sol (ADR-0021, ADR-0038). "
    ),
    "mensuel": (
        "Humidité relative à 2 m mensuelle ERA5 (réanalyse ECMWF, Copernicus C3S ; valeurs "
        f"horaires du CDS, jeu reanalysis-era5-single-levels) : {_METHODE} sur toutes les "
        "heures du mois, en %, soit la moyenne des jours de la série journalière. ERA5 ne "
        "sert pas d'humidité relative : la recalculer depuis les moyennes mensuelles de T "
        "et de Td la sous-estimerait (de 1,77 point en moyenne à Abidjan, Yamoussoukro et "
        "Korhogo sur 2016-2025). Point de grille 0,25° le plus proche, 1991-2025, même "
        "maille que les séries mensuelles ERA5 (0036). Face à l'humidité mensuelle NASA "
        "POWER (MERRA-2) aux mêmes localités, ERA5 est plus humide de 1,54 point en moyenne "
        "sur 1991-2025 (76,37 contre 74,83 % ; de −2,87 points à Duékoué à +5,71 points à "
        "Touba selon la localité). Confiance B (réanalyse) ; jamais une mesure au sol "
        "(ADR-0021, ADR-0038). "
    ),
}


# Dégénérescence de pixel : maille et caveat de 0042 (ADR-0027), figés ici.
DEGENERESCENCE: str = "degenerescence_pixel"
MAILLE_ERA5: tuple[str, str] = ("ERA5 (CDS)", "réanalyse ERA5 de 0,25°, environ 28 km")
CAVEAT_DEGENERESCENCE: str = (
    "Indicateur exact (identité observée, non modélisée), confiance B : A est réservée aux "
    "mesures terrain. Compte établi sur les localités portant cette famille ; il change avec "
    "le périmètre (ADR-0027)."
)
_SQL_VECTEURS: str = """
    SELECT s.grandeur_code, s.id AS serie_id, s.code AS serie_code,
           l.id AS localite_id, l.code AS localite, l.latitude, l.longitude,
           s.periode_debut, s.periode_fin, COUNT(*) AS nb_mois,
           array_agg(m.annee * 100 + m.mois ORDER BY m.annee, m.mois) AS cles,
           array_agg(m.valeur ORDER BY m.annee, m.mois) AS valeurs
    FROM series_metadonnees s
    JOIN localites l ON l.id = s.localite_id
    JOIN mesures_ressource_mensuelles m
        ON m.serie_id = s.id AND m.valide_au IS NULL AND m.statut <> 'deprecie'
    WHERE s.code = ANY(:c)
    GROUP BY s.id, l.id
"""


def _commentaire_degenerescence(
    serie: Any, nb_famille: int, distincts: list[str], confondus: list[str]
) -> str:
    """Texte de 0042 : groupe de jumeaux (coordonnées distinctes / identiques) ou caveat."""
    source, description = MAILLE_ERA5
    periode = (
        f"série mensuelle {serie.grandeur_code} {source} "
        f"({serie.periode_debut.year}-{serie.periode_fin.year}, {serie.nb_mois} mois)"
    )
    autres = nb_famille - 1
    nb = len(distincts) + len(confondus)
    if nb == 0:
        phrases = [
            f"{periode[0].upper()}{periode[1:]} : aucune des {autres} autres localités du "
            "périmètre n'a une série identique.",
            f"Un compte nul ne vaut pas résolution au point : {description}.",
        ]
    else:
        phrases = [
            f"{periode[0].upper()}{periode[1:]} strictement identique, mois par mois, à celle "
            f"de {nb} des {autres} autres localités du périmètre."
        ]
        if distincts:
            phrases.append(
                f"À des coordonnées distinctes ({len(distincts)}) : {', '.join(distincts)} ; la "
                f"source ne distingue pas ces points ({description}) : ne pas présenter "
                "leurs valeurs comme des mesures indépendantes."
            )
        if confondus:
            phrases.append(
                f"Aux mêmes coordonnées ({len(confondus)}) : {', '.join(confondus)} ; même point, "
                "série identique par construction."
            )
    phrases.append(CAVEAT_DEGENERESCENCE)
    return " ".join(phrases)


def _codes_localites() -> list[str]:
    return sorted(code for code, _, _, _ in points_nationaux())


def _contrats() -> list[ContratSerie]:
    return [CONTRAT_HUMIDITE_ERA5_JOURNALIER, CONTRAT_HUMIDITE_ERA5_MENSUEL]


def _note(contrat: ContratSerie, _serie: dict[str, Any] | None = None) -> str:
    return NOTES[contrat.granularite] + ATTRIBUTION


def _exiger(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(f"Migration {REVISION} : {message}")


def _graver_mensuel(bind: sa.Connection, loc: dict[str, int]) -> int:
    """Séries et mesures mensuelles (comme 0036 : audit ligne à ligne)."""
    contrat = CONTRAT_HUMIDITE_ERA5_MENSUEL
    series = lire_series(contrat, LOT_HUMIDITE_ERA5)
    _exiger(
        [s["localite_code"] for s in series] == sorted(loc),
        f"{contrat.nom_fichier(LOT_HUMIDITE_ERA5)} ne couvre pas les {NB_POINTS} localités.",
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO series_metadonnees (
                code, libelle, localite_id, grandeur_code, source_id, periode_debut,
                periode_fin, methode_collecte, granularite, note_publique
            ) VALUES (:code, :libelle, :localite_id, :grandeur_code, :source_id,
                      CAST(:periode_debut AS date), CAST(:periode_fin AS date),
                      :methode_collecte, :granularite, :note_publique)
            """
        ),
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
                "note_publique": _note(contrat),
            }
            for s in series
        ],
    )
    serie_id = dict(
        bind.execute(
            sa.text("SELECT code, id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": [s["code"] for s in series]},
        ).all()
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO mesures_ressource_mensuelles (
                serie_id, annee, mois, valeur, statut, niveau_confiance_derive
            ) VALUES (:s, :a, :m, :v, 'brut', :c)
            """
        ),
        [
            {"s": serie_id[s["code"]], "a": a, "m": m, "v": v, "c": contrat.niveau_confiance}
            for s in series
            for a, m, v in s["mesures"]
        ],
    )
    return int(
        bind.execute(
            sa.text("SELECT COUNT(*) FROM mesures_ressource_mensuelles WHERE serie_id = ANY(:i)"),
            {"i": list(serie_id.values())},
        ).scalar_one()
    )


def _graver_degenerescence(bind: sa.Connection) -> int:
    """Une ligne ``degenerescence_pixel`` par série mensuelle, règle de 0042 (ADR-0027)."""
    codes = [CONTRAT_HUMIDITE_ERA5_MENSUEL.code_serie(c) for c in _codes_localites()]
    series = bind.execute(sa.text(_SQL_VECTEURS), {"c": codes}).all()
    _exiger(len(series) == NB_POINTS, f"{len(series)} séries mensuelles pour la dégénérescence.")
    groupes: dict[tuple[tuple[int, ...], tuple[float, ...]], list[Any]] = defaultdict(list)
    for serie in series:
        groupes[(tuple(serie.cles), tuple(serie.valeurs))].append(serie)
    lignes: list[dict[str, Any]] = []
    for membres in groupes.values():
        for serie in membres:
            jumeaux = [j for j in membres if j.serie_id != serie.serie_id]
            point = (serie.latitude, serie.longitude)
            distincts = sorted(j.localite for j in jumeaux if (j.latitude, j.longitude) != point)
            confondus = sorted(j.localite for j in jumeaux if (j.latitude, j.longitude) == point)
            lignes.append(
                {
                    "l": serie.localite_id,
                    "s": serie.serie_id,
                    "a": serie.periode_debut.year,
                    "f": serie.periode_fin.year,
                    "v": float(len(jumeaux)),
                    "c": _commentaire_degenerescence(serie, len(series), distincts, confondus),
                }
            )
    bind.execute(
        sa.text(
            """
            INSERT INTO grandeurs_metier (
                grandeur_code, localite_id, series_metadonnees_id, periode_type, annee_debut,
                annee_fin, mois, version_formule, valeur, niveau_confiance_derive,
                commentaire_editorial
            ) VALUES (:g, :l, :s, 'statique', :a, :f, NULL, 1, :v, 'B', :c)
            """
        ),
        [{"g": DEGENERESCENCE, **ligne} for ligne in lignes],
    )
    # Même maille que la température ERA5 mensuelle (0036) : mêmes comptes de jumeaux.
    differents = bind.execute(
        sa.text(
            """
            SELECT h.localite_id
            FROM grandeurs_metier h
            JOIN series_metadonnees sh ON sh.id = h.series_metadonnees_id
            JOIN grandeurs_metier t ON t.grandeur_code = h.grandeur_code
                 AND t.localite_id = h.localite_id AND t.valide_au IS NULL
            JOIN series_metadonnees st ON st.id = t.series_metadonnees_id
                 AND st.code = 'ecmwf_era5_t2m_mensuel_' || substr(sh.code, :n)
            WHERE h.grandeur_code = :g AND sh.code = ANY(:c) AND t.valeur <> h.valeur
            """
        ),
        {"g": DEGENERESCENCE, "c": codes, "n": len("ecmwf_era5_rh2m_mensuel_") + 1},
    ).all()
    _exiger(not differents, f"jumeaux différents de la température ERA5 : {differents!r}.")
    return len(lignes)


def upgrade() -> None:
    bind = op.get_bind()

    # 0. Garde-fous : source, unité du référentiel, localités, séries préexistantes.
    code_source = bind.execute(
        sa.text("SELECT code FROM sources WHERE id = :i"), {"i": SOURCE_ID}
    ).scalar_one_or_none()
    _exiger(code_source == SOURCE_CODE, f"source id {SOURCE_ID} = {code_source!r}.")
    unite = bind.execute(
        sa.text(
            "SELECT u.code FROM grandeurs_referentiel g JOIN unites u ON u.id = g.unite_id "
            "WHERE g.code = :g AND g.actif"
        ),
        {"g": GRANDEUR},
    ).scalar_one_or_none()
    _exiger(unite == UNITE, f"grandeur {GRANDEUR!r} en {unite!r}, {UNITE!r} attendue.")
    codes_loc = _codes_localites()
    loc = dict(
        bind.execute(
            sa.text("SELECT code, id FROM localites WHERE code = ANY(:c)"), {"c": codes_loc}
        ).all()
    )
    _exiger(
        len(codes_loc) == NB_POINTS and sorted(loc) == codes_loc,
        f"{len(loc)} localités trouvées sur {len(codes_loc)}, {NB_POINTS} attendues.",
    )
    preexistantes = bind.execute(
        sa.text(
            "SELECT code FROM series_metadonnees "
            "WHERE code = ANY(:codes) OR (source_id = :src AND grandeur_code = :g)"
        ),
        {
            "codes": [c.code_serie(code) for c in _contrats() for code in codes_loc],
            "src": SOURCE_ID,
            "g": GRANDEUR,
        },
    ).all()
    _exiger(not preexistantes, f"séries déjà présentes : {[r.code for r in preexistantes]!r}.")

    # 1. Journalier : séries, mesures par COPY et audit par série.
    total = graver_lot(
        bind, REVISION, [CONTRAT_HUMIDITE_ERA5_JOURNALIER], LOT_HUMIDITE_ERA5, loc, _note
    )
    _exiger(total == NB_MESURES_JOURNALIERES, f"{total} mesures journalières.")

    # 2. Mensuel : séries et mesures, audit ligne à ligne.
    total = _graver_mensuel(bind, loc)
    _exiger(total == NB_MESURES_MENSUELLES, f"{total} mesures mensuelles.")

    # 3. Dégénérescence de pixel de la famille mensuelle (ADR-0027).
    total = _graver_degenerescence(bind)
    _exiger(total == NB_POINTS, f"{total} lignes de dégénérescence.")
    bind.execute(sa.text("ANALYZE grandeurs_metier"))
    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE mesures_ressource"))
    bind.execute(sa.text("ANALYZE mesures_ressource_mensuelles"))


def downgrade() -> None:
    bind = op.get_bind()
    codes_loc = _codes_localites()
    bind.execute(
        sa.text(
            "DELETE FROM grandeurs_metier WHERE grandeur_code = :g AND series_metadonnees_id IN "
            "(SELECT id FROM series_metadonnees WHERE code = ANY(:c))"
        ),
        {
            "g": DEGENERESCENCE,
            "c": [CONTRAT_HUMIDITE_ERA5_MENSUEL.code_serie(c) for c in codes_loc],
        },
    )
    supprimer_lot(bind, REVISION, [CONTRAT_HUMIDITE_ERA5_JOURNALIER], LOT_HUMIDITE_ERA5, codes_loc)
    ids = [
        r.id
        for r in bind.execute(
            sa.text("SELECT id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": [CONTRAT_HUMIDITE_ERA5_MENSUEL.code_serie(c) for c in codes_loc]},
        ).all()
    ]
    bind.execute(
        sa.text("DELETE FROM mesures_ressource_mensuelles WHERE serie_id = ANY(:i)"), {"i": ids}
    )
    bind.execute(sa.text("DELETE FROM series_metadonnees WHERE id = ANY(:i)"), {"i": ids})
    bind.execute(sa.text("ANALYZE grandeurs_metier"))
    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE mesures_ressource"))
    bind.execute(sa.text("ANALYZE mesures_ressource_mensuelles"))
