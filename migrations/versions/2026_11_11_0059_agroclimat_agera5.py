"""agroclimat_agera5

Revision ID: 0059
Revises: 0058
Create Date: 2026-11-11

**Agroclimat AgERA5 (Copernicus C3S), journalier et mensuel, aux 142 localités,
1991-2025** (ADR-0040). AgERA5 tire des valeurs horaires d'ERA5 des indicateurs
journaliers pour l'agriculture, ramenés sur une grille de 0,1° avec une
correction d'altitude. Quatre grandeurs nouvelles au référentiel :

| Grandeur (id) | Variable AgERA5 | Unité |
|---|---|---|
| ``et0`` (47) | ``reference_evapotranspiration`` (Penman-Monteith FAO-56) | mm/jour |
| ``t2m_min`` (48) | ``2m_temperature``, minimum sur 24 h | °C |
| ``t2m_max`` (49) | ``2m_temperature``, maximum sur 24 h | °C |
| ``vpd_tmax`` (50) | ``vapour_pressure_deficit_at_maximum_temperature`` | kPa |

Grave, dans cet ordre :

1. la source ``agera5`` (**id 19**, id figé comme ``chirps`` en 0055) ;
2. les 4 grandeurs (ids 47 à 50) ;
3. **568 séries journalières** ``agera5_<grandeur>_journalier_<localité>``
   (12 784 jours, 7 261 312 mesures, ``COPY`` et audit par série, ADR-0031) ;
4. **568 séries mensuelles** ``agera5_<grandeur>_mensuel_<localité>`` (420
   mois, 238 560 mesures, audit ligne à ligne), moyenne des jours du mois ;
5. la **dégénérescence de pixel** des 4 familles mensuelles (568 lignes,
   règle de 0042, ADR-0027).

Méthode ``reanalyse``, confiance **B**. Jour local 00 h-00 h d'AgERA5, soit le
jour civil en Côte d'Ivoire (UTC+0). Valeur de la maille de 0,1° qui contient
la localité (``maille_agera5`` ; une localité sur une limite de maille est
rattachée à la maille au sud et à l'est, comme pour CHIRPS) : 119 mailles pour
142 localités, sans interpolation. Contrats : ``agroclimat_agera5_civ``.

Valeurs lues hors-ligne dans les CSV gzip committés
(``seeds/donnees/agera5_<grandeur>_<journalier|mensuel>_civ142.csv.gz``,
générés par ``scripts/ingest_agera5.py``) et validées par ``series_csv``.

Recoupements (``scripts/ingest_agera5.py``) : Tmin ≤ Tmax chaque jour, déficit
au plus 97,9 % de la pression de vapeur saturante à Tmax. Face aux extrêmes des
24 heures UTC d'ERA5 (cache horaire de 0057, 110 nœuds), Tmin et Tmax sont
corrélées à 0,955 et 0,964 le même jour, à 0,78-0,82 avec un jour de décalage :
le jour d'AgERA5 est le jour civil. La moyenne journalière ERA5 (0053) tombe
entre Tmin et Tmax 99,82 % des jours ; Hargreaves donne 4,19 mm/jour pour une
ET0 de 4,02. Chiffres publiés dans ``NOTES``.

Garde-fous : id 19 et code ``agera5`` libres, grandeurs absentes, unités, 142
localités, aucune série préexistante, couverture exacte des CSV, comptes de
séries, de mesures et de lignes de dégénérescence. ``downgrade`` supprime la
dégénérescence, le journalier (audit par série), le mensuel, les grandeurs puis
la source.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from kuma_data_core.db.seeds.agroclimat_agera5_civ import (
    CONTRATS_AGERA5_JOURNALIERS,
    CONTRATS_AGERA5_MENSUELS,
    DOI,
    GRANDEURS_AGERA5,
    JEU_CDS,
    LOT_AGERA5,
    SOURCE_CODE,
    SOURCE_ID,
    SOURCE_LIBELLE,
)
from kuma_data_core.db.seeds.gravure_journaliere import graver_lot, supprimer_lot
from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.series_csv import ContratSerie, lire_series

# revision identifiers, used by Alembic.
revision: str = "0059"
down_revision: str | Sequence[str] | None = "0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVISION: str = "0059"
NB_POINTS: int = 142
NB_MESURES_JOURNALIERES: int = 7_261_312  # 4 × 142 × 12 784
NB_MESURES_MENSUELLES: int = 238_560  # 4 × 142 × 420
IDS_GRANDEURS: dict[str, int] = {"et0": 47, "t2m_min": 48, "t2m_max": 49, "vpd_tmax": 50}

URL_JEU: str = f"https://cds.climate.copernicus.eu/datasets/{JEU_CDS}"
SOURCE: dict[str, object] = {
    "id": SOURCE_ID,
    "code": SOURCE_CODE,
    "titre": (
        "AgERA5 v2.0 — indicateurs agrométéorologiques journaliers tirés de la réanalyse "
        "ERA5, grille de 0,1° (Copernicus C3S)"
    ),
    "auteurs": [
        "Boogaard, H.",
        "Schubert, J.",
        "De Wit, A.",
        "Lazebnik, J.",
        "Hutjes, R.",
        "Van der Grijn, G.",
    ],
    "organisation": (
        "Copernicus Climate Change Service (C3S), ECMWF ; Wageningen Environmental Research"
    ),
    "type_source": "base_donnees",
    "annee_publication": 2020,
    "date_consultation": "2026-11-11",
    "url": URL_JEU,
    "doi": DOI,
    "fiabilite": "haute",
    "langue": "en",
    "metadonnees": {
        "acces": (
            f"API du Climate Data Store, jeu {JEU_CDS}, version 2_0, zone de la Côte d'Ivoire, "
            "une requête par grandeur et par année ; clé Copernicus et licence acceptée sur le "
            "compte"
        ),
        "version": "2.0 (fichiers final-v2.0.0)",
        "granularite_spatiale": "0,1° (maille contenant la localité), mer masquée",
        "granularite_temporelle": "journalier, jour local 00 h-00 h (00-00LT)",
        "variables": {
            g.code: g.variable_cds + (f" ({g.statistique})" if g.statistique else "")
            for g in GRANDEURS_AGERA5.values()
        },
        "licence": "Creative Commons Attribution 4.0 International (CC BY 4.0)",
        "attribution": (
            "Contient des informations modifiées du Copernicus Climate Change Service (2026)."
        ),
    },
    "notes": (
        "AgERA5 (Copernicus Climate Change Service ; Wageningen Environmental Research), "
        "version 2.0 : indicateurs agrométéorologiques journaliers calculés à partir des "
        "valeurs horaires de la réanalyse ERA5 (ECMWF), ramenés sur une grille de 0,1° avec "
        "une correction d'altitude, de 1979 à nos jours. Agrégation sur le jour local "
        "00 h-00 h. Évapotranspiration de référence Penman-Monteith selon FAO-56, "
        "températures minimale et maximale sur 24 h, déficit de pression de vapeur à la "
        "température maximale (pression de vapeur saturante à Tmax moins pression de vapeur "
        "moyenne du jour). Licence CC BY 4.0. Citation : Boogaard, H., Schubert, J., De Wit, "
        "A., Lazebnik, J., Hutjes, R., Van der Grijn, G. (2020) : Agrometeorological "
        "indicators from 1979 to present derived from reanalysis, Copernicus Climate Change "
        f"Service (C3S) Climate Data Store (CDS), doi:{DOI}. Consulté le 2026-11-11."
    ),
}

DESCRIPTIONS: dict[str, str] = {
    "et0": (
        "Évapotranspiration d'un gazon de référence bien alimenté en eau, selon la formule de "
        "Penman-Monteith de la FAO (bulletin FAO-56), en mm/jour : la demande en eau de "
        "l'atmosphère, base du calcul des besoins en eau des cultures. Brute, servie par la "
        "source (ADR-0040). Famille F1."
    ),
    "t2m_min": (
        "Température minimale de l'air à 2 m sur le jour, en °C. Brute, servie par la source "
        "(ADR-0040). Famille F1."
    ),
    "t2m_max": (
        "Température maximale de l'air à 2 m sur le jour, en °C. Brute, servie par la source "
        "(ADR-0040). Famille F1."
    ),
    "vpd_tmax": (
        "Déficit de pression de vapeur à la température maximale du jour : pression de vapeur "
        "saturante à Tmax moins pression de vapeur moyenne du jour, en kPa. Mesure le pouvoir "
        "desséchant de l'air aux heures chaudes. Brute, servie par la source (ADR-0040). "
        "Famille F1."
    ),
}

_ADJECTIF: dict[str, str] = {"journalier": "journalière", "mensuel": "mensuelle"}
_PAS: dict[str, str] = {
    "journalier": "valeur du jour local 00 h-00 h (jour civil, UTC+0)",
    "mensuel": "moyenne des jours du mois",
}
_MAILLE: str = (
    "valeur de la maille de 0,1° (environ 11 km) qui contient la localité, sans "
    "interpolation (une localité sur une limite de maille est rattachée à la maille au sud et "
    "à l'est)"
)
_FIN: str = (
    "Réanalyse, jamais une mesure au sol. Confiance B (ADR-0040). Attribution : contient des "
    "informations modifiées du Copernicus Climate Change Service (2026)."
)
_ERA5: str = (
    "La température moyenne journalière ERA5 tombe entre Tmin et Tmax AgERA5 99,82 % des "
    "jours-localités ; la demi-somme de Tmin et Tmax la dépasse de 0,13 °C en moyenne (0,41 en "
    "valeur absolue)."
)
CONSTATS: dict[str, str] = {
    "et0": (
        "Sur les jours de 1991-2025 : 4,02 mm/jour en moyenne aux 142 localités, de 3,38 à "
        "San-Pédro à 5,29 à Doropo ; 4,85 en février, 3,26 en août. La formule de Hargreaves "
        "(FAO-56), qui ne tient compte ni de l'humidité ni du vent, donne 4,19 mm/jour sur les "
        "mêmes jours, corrélée à 0,75."
    ),
    "t2m_min": (
        "Sur les jours de 1991-2025 : 22,36 °C en moyenne aux 142 localités, de 19,93 à "
        f"Biankouma à 25,39 à Jacqueville ; 23,63 en avril, 21,28 en décembre. {_ERA5}"
    ),
    "t2m_max": (
        "Sur les jours de 1991-2025 : 30,67 °C en moyenne aux 142 localités, de 26,71 à "
        f"Sassandra à 33,17 à M’Bengué ; 33,53 en février, 27,67 en août. {_ERA5}"
    ),
    "vpd_tmax": (
        "Sur les jours de 1991-2025 : 1,99 kPa en moyenne aux 142 localités, de 0,64 à "
        "Jacqueville, sur la côte, à 3,15 à Tengréla, au nord ; 3,01 en février, 1,25 en août."
    ),
}
NOTES: dict[tuple[str, str], str] = {}
for _g, _grandeur in GRANDEURS_AGERA5.items():
    for _granularite, _pas in _PAS.items():
        NOTES[(_g, _granularite)] = (
            f"{_grandeur.libelle} {_ADJECTIF[_granularite]} AgERA5 v2.0 (Copernicus C3S, "
            f"indicateurs agrométéorologiques tirés d'ERA5) : {_MAILLE}, {_pas}, 1991-2025. "
            f"{CONSTATS[_g]} {_FIN}"
        )
del _g, _grandeur, _granularite, _pas

# Dégénérescence de pixel : règle, caveat et commentaire de 0042 (ADR-0027), figés ici.
DEGENERESCENCE: str = "degenerescence_pixel"
DESCRIPTION_MAILLE: str = "grille AgERA5 de 0,1°, environ 11 km"
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


def _exiger(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(f"Migration {REVISION} : {message}")


def _codes_localites() -> list[str]:
    return sorted(code for code, _, _, _ in points_nationaux())


def _contrats() -> list[ContratSerie]:
    return [*CONTRATS_AGERA5_JOURNALIERS.values(), *CONTRATS_AGERA5_MENSUELS.values()]


def _note(contrat: ContratSerie, _serie: dict[str, Any] | None = None) -> str:
    return NOTES[(contrat.grandeur_code, contrat.granularite)]


def _recaler_sequence(bind: sa.Connection, table: str) -> None:
    """Recale l'identité de ``table`` sur le plus grand id présent (idempotent)."""
    bind.execute(
        sa.text(
            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT MAX(id) FROM {table}))"
        )
    )


def _commentaire_degenerescence(
    serie: Any, nb_famille: int, distincts: list[str], confondus: list[str]
) -> str:
    """Texte de 0042 : groupe de jumeaux (coordonnées distinctes / identiques) ou caveat."""
    periode = (
        f"série mensuelle {serie.grandeur_code} {SOURCE_LIBELLE} "
        f"({serie.periode_debut.year}-{serie.periode_fin.year}, {serie.nb_mois} mois)"
    )
    autres = nb_famille - 1
    nb = len(distincts) + len(confondus)
    if nb == 0:
        phrases = [
            f"{periode[0].upper()}{periode[1:]} : aucune des {autres} autres localités du "
            "périmètre n'a une série identique.",
            f"Un compte nul ne vaut pas résolution au point : {DESCRIPTION_MAILLE}.",
        ]
    else:
        phrases = [
            f"{periode[0].upper()}{periode[1:]} strictement identique, mois par mois, à celle "
            f"de {nb} des {autres} autres localités du périmètre."
        ]
        if distincts:
            phrases.append(
                f"À des coordonnées distinctes ({len(distincts)}) : {', '.join(distincts)} ; la "
                f"source ne distingue pas ces points ({DESCRIPTION_MAILLE}) : ne pas présenter "
                "leurs valeurs comme des mesures indépendantes."
            )
        if confondus:
            phrases.append(
                f"Aux mêmes coordonnées ({len(confondus)}) : {', '.join(confondus)} ; même point, "
                "série identique par construction."
            )
    phrases.append(CAVEAT_DEGENERESCENCE)
    return " ".join(phrases)


def _graver_mensuel(bind: sa.Connection, contrat: ContratSerie, loc: dict[str, int]) -> int:
    """Séries et mesures mensuelles d'une grandeur (audit ligne à ligne)."""
    series = lire_series(contrat, LOT_AGERA5)
    _exiger(
        [s["localite_code"] for s in series] == sorted(loc),
        f"{contrat.nom_fichier(LOT_AGERA5)} ne couvre pas les {NB_POINTS} localités.",
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


def _graver_degenerescence(bind: sa.Connection, contrat: ContratSerie) -> int:
    """Une ligne ``degenerescence_pixel`` par série mensuelle, règle de 0042 (ADR-0027)."""
    codes = [contrat.code_serie(c) for c in _codes_localites()]
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
                    "g": DEGENERESCENCE,
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
        lignes,
    )
    return len(lignes)


def upgrade() -> None:
    bind = op.get_bind()

    # 0. Garde-fous : source et grandeurs libres, unités, localités, séries préexistantes.
    occupe = bind.execute(
        sa.text("SELECT id, code FROM sources WHERE id = :i OR code = :c"),
        {"i": SOURCE_ID, "c": SOURCE_CODE},
    ).all()
    _exiger(not occupe, f"source déjà présente : {[(r.id, r.code) for r in occupe]!r}.")
    deja = bind.execute(
        sa.text("SELECT code FROM grandeurs_referentiel WHERE code = ANY(:c) OR id = ANY(:i)"),
        {"c": list(IDS_GRANDEURS), "i": list(IDS_GRANDEURS.values())},
    ).all()
    _exiger(not deja, f"grandeurs déjà présentes : {[r.code for r in deja]!r}.")
    unites = dict(
        bind.execute(
            sa.text("SELECT code, id FROM unites WHERE code = ANY(:c)"),
            {"c": sorted({g.unite_referentiel for g in GRANDEURS_AGERA5.values()})},
        ).all()
    )
    _exiger(len(unites) == 3, f"unités {sorted(unites)!r}.")
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
        sa.text("SELECT code FROM series_metadonnees WHERE code = ANY(:c)"),
        {"c": [c.code_serie(code) for c in _contrats() for code in codes_loc]},
    ).all()
    _exiger(not preexistantes, f"séries déjà présentes : {[r.code for r in preexistantes]!r}.")

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
    _recaler_sequence(bind, "sources")

    # 2. Grandeurs du référentiel.
    bind.execute(
        sa.text(
            """
            INSERT INTO grandeurs_referentiel (
                id, code, libelle, unite_id, famille, strategie_calcul,
                version_formule_actuelle, description
            ) VALUES (:id, :code, :libelle, :unite, 'F1', 'stockee', 1, :description)
            """
        ),
        [
            {
                "id": IDS_GRANDEURS[code],
                "code": code,
                "libelle": g.libelle,
                "unite": unites[g.unite_referentiel],
                "description": DESCRIPTIONS[code],
            }
            for code, g in GRANDEURS_AGERA5.items()
        ],
    )
    _recaler_sequence(bind, "grandeurs_referentiel")

    # 3. Journalier : séries, mesures par COPY et audit par série.
    total = graver_lot(
        bind, REVISION, list(CONTRATS_AGERA5_JOURNALIERS.values()), LOT_AGERA5, loc, _note
    )
    _exiger(total == NB_MESURES_JOURNALIERES, f"{total} mesures journalières.")

    # 4. Mensuel : séries et mesures, audit ligne à ligne ; dégénérescence de pixel.
    total = sum(_graver_mensuel(bind, c, loc) for c in CONTRATS_AGERA5_MENSUELS.values())
    _exiger(total == NB_MESURES_MENSUELLES, f"{total} mesures mensuelles.")
    total = sum(_graver_degenerescence(bind, c) for c in CONTRATS_AGERA5_MENSUELS.values())
    _exiger(total == len(GRANDEURS_AGERA5) * NB_POINTS, f"{total} lignes de dégénérescence.")

    bind.execute(sa.text("ANALYZE sources"))
    bind.execute(sa.text("ANALYZE grandeurs_referentiel"))
    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE mesures_ressource"))
    bind.execute(sa.text("ANALYZE mesures_ressource_mensuelles"))
    bind.execute(sa.text("ANALYZE grandeurs_metier"))


def downgrade() -> None:
    bind = op.get_bind()
    codes_loc = _codes_localites()
    codes_mensuels = [
        c.code_serie(code) for c in CONTRATS_AGERA5_MENSUELS.values() for code in codes_loc
    ]
    bind.execute(
        sa.text(
            "DELETE FROM grandeurs_metier WHERE grandeur_code = :g AND series_metadonnees_id IN "
            "(SELECT id FROM series_metadonnees WHERE code = ANY(:c))"
        ),
        {"g": DEGENERESCENCE, "c": codes_mensuels},
    )
    supprimer_lot(bind, REVISION, list(CONTRATS_AGERA5_JOURNALIERS.values()), LOT_AGERA5, codes_loc)
    ids = [
        r.id
        for r in bind.execute(
            sa.text("SELECT id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": codes_mensuels},
        ).all()
    ]
    bind.execute(
        sa.text("DELETE FROM mesures_ressource_mensuelles WHERE serie_id = ANY(:i)"), {"i": ids}
    )
    bind.execute(sa.text("DELETE FROM series_metadonnees WHERE id = ANY(:i)"), {"i": ids})
    bind.execute(
        sa.text("DELETE FROM grandeurs_referentiel WHERE code = ANY(:c)"),
        {"c": list(IDS_GRANDEURS)},
    )
    _recaler_sequence(bind, "grandeurs_referentiel")
    bind.execute(
        sa.text("DELETE FROM sources WHERE id = :i AND code = :c"),
        {"i": SOURCE_ID, "c": SOURCE_CODE},
    )
    _recaler_sequence(bind, "sources")
    bind.execute(sa.text("ANALYZE sources"))
    bind.execute(sa.text("ANALYZE grandeurs_referentiel"))
    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE mesures_ressource"))
    bind.execute(sa.text("ANALYZE mesures_ressource_mensuelles"))
    bind.execute(sa.text("ANALYZE grandeurs_metier"))
