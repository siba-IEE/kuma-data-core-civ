"""ciel_clair_cams

Revision ID: 0058
Revises: 0057
Create Date: 2026-11-07

**Ciel clair, irradiation extraterrestre et fiabilité CAMS Radiation, journaliers
et mensuels, aux 142 localités, 2005-2025** (ADR-0039). Colonnes que CAMS sert
dans les mêmes réponses que le tous ciels déjà gravé (mensuel 0014 à 0030,
révisé en 0056 ; journalier 0054) : aucune nouvelle requête.

| Grandeur (nouvelle, id) | Colonne CAMS | Unité |
|---|---|---|
| ``ghi_ciel_clair`` (42) | ``Clear sky GHI`` (McClear) | kWh/m²/jour |
| ``dni_ciel_clair`` (43) | ``Clear sky BNI`` (McClear) | kWh/m²/jour |
| ``dhi_ciel_clair`` (44) | ``Clear sky DHI`` (McClear) | kWh/m²/jour |
| ``irradiation_extraterrestre`` (45) | ``TOA`` | kWh/m²/jour |
| ``fiabilite_satellite`` (46) | ``Reliability`` | sans unité (0 à 1) |

Soit **1 420 séries** ``cams_<grandeur>_<journalier|mensuel>_<localité>`` et
**5 624 620 mesures** : 710 séries journalières (7 670 jours, 5 445 700
mesures, ``COPY`` et audit par série, ADR-0031) et 710 séries mensuelles
(252 mois, 178 920 mesures, audit ligne à ligne), source ``cams_radiation``
(id 13), méthode ``modele_satellitaire``, confiance B. Le ciel clair (modèle
McClear) ne dépend pas des images Meteosat : CAMS le sert aussi les jours où le
tous ciels manque, sans lacune. Contrats : ``ciel_clair_cams_civ``.

Recoupements (``ingest_cams_radiation_mensuel.py`` et
``ingest_cams_radiation_journalier.py``, mode ``--ciel-clair``) : la moyenne
des jours de chaque mois redonne le mensuel à 0,00007 kWh/m²/jour près ; la
fiabilité mensuelle, que CAMS ne calcule pas comme la moyenne des jours, s'en
écarte d'au plus 0,016. Constats publiés dans ``NOTES``.

**Dégénérescence de pixel** (ADR-0027) : 710 lignes pour les 5 familles
mensuelles, selon la règle de 0042 (égalité exacte des séries, même
commentaire).

Garde-fous : identité de la source, grandeurs absentes du référentiel,
unités, 142 localités, aucune série préexistante, couverture exacte des CSV,
comptes de séries, de mesures et de lignes de dégénérescence. ``downgrade``
supprime la dégénérescence, le journalier (audit par série), le mensuel puis
les grandeurs.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.ciel_clair_cams_civ import (
    CONTRATS_CIEL_CLAIR_JOURNALIERS,
    CONTRATS_CIEL_CLAIR_MENSUELS,
    GRANDEURS_CIEL_CLAIR,
    LIBELLES,
    LOT_CIEL_CLAIR_CAMS,
)
from kuma_data_core.db.seeds.gravure_journaliere import graver_lot, supprimer_lot
from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.series_csv import ContratSerie, lire_series

# revision identifiers, used by Alembic.
revision: str = "0058"
down_revision: str | Sequence[str] | None = "0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVISION: str = "0058"
SOURCE_ID: int = 13
SOURCE_CODE: str = "cams_radiation"
NB_POINTS: int = 142
NB_MESURES_JOURNALIERES: int = 5_445_700  # 5 × 142 × 7 670
NB_MESURES_MENSUELLES: int = 178_920  # 5 × 142 × 252
GRANDEURS: dict[str, tuple[int, str]] = {
    "ghi_ciel_clair": (42, "kwh_par_m2_jour"),
    "dni_ciel_clair": (43, "kwh_par_m2_jour"),
    "dhi_ciel_clair": (44, "kwh_par_m2_jour"),
    "irradiation_extraterrestre": (45, "kwh_par_m2_jour"),
    "fiabilite_satellite": (46, "sans_unite"),
}
DESCRIPTIONS: dict[str, str] = {
    "ghi_ciel_clair": (
        "Irradiation globale sur plan horizontal qu'on recevrait sans nuage, compte tenu des "
        "aérosols, de la vapeur d'eau et de l'ozone (modèle McClear de CAMS Radiation). Le "
        "rapport du GHI tous ciels à cette valeur est l'indice de ciel clair. Brute, servie "
        "par la source (ADR-0039). Famille F1."
    ),
    "dni_ciel_clair": (
        "Irradiation directe normale qu'on recevrait sans nuage, compte tenu des aérosols, de "
        "la vapeur d'eau et de l'ozone (modèle McClear de CAMS Radiation). Brute, servie par "
        "la source (ADR-0039). Famille F1."
    ),
    "dhi_ciel_clair": (
        "Irradiation diffuse sur plan horizontal qu'on recevrait sans nuage, compte tenu des "
        "aérosols, de la vapeur d'eau et de l'ozone (modèle McClear de CAMS Radiation). Brute, "
        "servie par la source (ADR-0039). Famille F1."
    ),
    "irradiation_extraterrestre": (
        "Irradiation solaire sur plan horizontal au sommet de l'atmosphère (H0), telle que "
        "servie par la source avec ses autres colonnes de rayonnement : dénominateur de "
        "l'indice de clarté kt. Brute (ADR-0039). Famille F1."
    ),
    "fiabilite_satellite": (
        "Part, de 0 à 1, des pas de temps pour lesquels la source dispose d'observations "
        "satellitaires fiables sur la période (colonne Reliability de CAMS Radiation). "
        "Qualifie le rayonnement tous ciels, pas le ciel clair. Brute (ADR-0039). Famille F1."
    ),
}

_FIN: str = (
    "Estimation par modèle, jamais une mesure au sol. Confiance B (ADR-0011, ADR-0039). "
    "Source : Copernicus Atmosphere Monitoring Service (CAMS), 2026."
)
_CC: str = (
    "par ciel clair CAMS Radiation (Copernicus ; modèle McClear, service v4.6) : "
    "rayonnement qu'on recevrait sans nuage, compte tenu des aérosols, de la vapeur d'eau et "
    "de l'ozone des analyses CAMS, au point de la localité, en kWh/m²/jour"
)
_ADJECTIF: dict[str, str] = {"journalier": "journalière", "mensuel": "mensuelle"}
_PAS: dict[str, str] = {
    "journalier": "intégré sur le jour UTC (jour civil local, UTC+0)",
    "mensuel": "moyenne journalière du mois",
}
_CONSTATS: dict[str, str] = {
    "ghi_ciel_clair": (
        "Le GHI tous ciels CAMS en vaut 80,9 % en moyenne sur 2005-2025 (95 % en janvier, "
        "64 % en août ; de 70,6 % à Abidjan à 87,9 % à Tengréla selon la localité) : le reste "
        "est arrêté par les nuages."
    ),
    "dni_ciel_clair": (
        "Le DNI tous ciels CAMS en vaut 61,6 % en moyenne sur 2005-2025 (88 % en janvier, "
        "36 % en août). Le ciel clair lui-même baisse en saison sèche : 5,4 kWh/m²/jour de "
        "décembre à février contre 7,3 en septembre. Rapporté à l'irradiation extraterrestre, "
        "il est au plus bas en février et mars (0,53 à 0,55, contre 0,71 en septembre), quand "
        "le soleil est haut : effet des aérosols de la saison sèche (Harmattan), pas seulement "
        "de la hauteur du soleil."
    ),
    "dhi_ciel_clair": (
        "Le DHI tous ciels CAMS le dépasse de 26 % en moyenne sur 2005-2025 : les nuages "
        "diffusent le rayonnement direct qu'ils arrêtent."
    ),
}
NOTES: dict[tuple[str, str], str] = {}
for _g in ("ghi_ciel_clair", "dni_ciel_clair", "dhi_ciel_clair"):
    _nom = LIBELLES[_g].removesuffix(" par ciel clair")
    for _granularite, _pas in _PAS.items():
        NOTES[(_g, _granularite)] = (
            f"{_nom} {_ADJECTIF[_granularite]} {_CC}, {_pas}, 2005-2025. Servie aussi les jours "
            "sans images "
            f"Meteosat, où le tous ciels manque. {_CONSTATS[_g]} {_FIN}"
        )
for _granularite, _pas in _PAS.items():
    NOTES[("irradiation_extraterrestre", _granularite)] = (
        f"Irradiation extraterrestre horizontale {_ADJECTIF[_granularite]} CAMS Radiation "
        "(Copernicus, "
        f"service v4.6) : rayonnement solaire sur plan horizontal au sommet de l'atmosphère, au "
        f"point de la localité, {_pas}, en kWh/m²/jour, 2005-2025. Elle redonne à 0,44 % près "
        "(+0,08 % en moyenne) l'irradiation extraterrestre calculée pour l'indice de clarté kt "
        f"(0041 : Spencer 1971, constante solaire 1361 W/m²). Calcul astronomique. {_FIN}"
    )
NOTES[("fiabilite_satellite", "journalier")] = (
    "Fiabilité journalière des observations satellitaires CAMS Radiation (Copernicus, service "
    "v4.6) : part, de 0 à 1, des pas de 15 minutes du jour UTC pour lesquels CAMS dispose "
    "d'images Meteosat fiables au point de la localité, telle que servie, 2005-2025. Médiane "
    "0,985 ; 1 733 jours-localités sous 0,9 sur 1 089 140 ; environ 0,52 les jours où des "
    "images manquent et où le tous ciels n'est pas servi. Elle qualifie le rayonnement tous "
    f"ciels, pas le ciel clair, calculé sans images. {_FIN}"
)
NOTES[("fiabilite_satellite", "mensuel")] = (
    "Fiabilité mensuelle des observations satellitaires CAMS Radiation (Copernicus, service "
    "v4.6) : part, de 0 à 1, des pas de 15 minutes du mois pour lesquels CAMS dispose d'images "
    "Meteosat fiables au point de la localité, telle que servie, 2005-2025. De 0,959 "
    "(Bangolo, janvier 2006) à 0,989 ; CAMS ne la calcule pas comme la moyenne des jours "
    "(écart d'au plus 0,016). Elle qualifie le rayonnement tous ciels, pas le ciel clair, "
    f"calculé sans images. {_FIN}"
)
del _g, _nom, _granularite, _pas

# Dégénérescence de pixel : règle, caveat et commentaire de 0042 (ADR-0027), figés ici.
DEGENERESCENCE: str = "degenerescence_pixel"
SOURCE_LIBELLE: str = "CAMS Radiation"
MAILLES: dict[str, str] = {
    "ghi_ciel_clair": "modèle McClear au point, sur les analyses CAMS des aérosols et de l'eau",
    "dni_ciel_clair": "modèle McClear au point, sur les analyses CAMS des aérosols et de l'eau",
    "dhi_ciel_clair": "modèle McClear au point, sur les analyses CAMS des aérosols et de l'eau",
    "irradiation_extraterrestre": "calcul astronomique au point (latitude, longitude, date)",
    "fiabilite_satellite": (
        "service au point CAMS Radiation (Heliosat-4, pixel Meteosat de 3 à 5 km)"
    ),
}
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
    return [
        *CONTRATS_CIEL_CLAIR_JOURNALIERS.values(),
        *CONTRATS_CIEL_CLAIR_MENSUELS.values(),
    ]


def _note(contrat: ContratSerie, _serie: dict[str, Any] | None = None) -> str:
    return NOTES[(contrat.grandeur_code, contrat.granularite)]


def _commentaire_degenerescence(
    serie: Any, nb_famille: int, distincts: list[str], confondus: list[str]
) -> str:
    """Texte de 0042 : groupe de jumeaux (coordonnées distinctes / identiques) ou caveat."""
    description = MAILLES[serie.grandeur_code]
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


def _graver_mensuel(bind: sa.Connection, contrat: ContratSerie, loc: dict[str, int]) -> int:
    """Séries et mesures mensuelles d'une grandeur (audit ligne à ligne)."""
    series = lire_series(contrat, LOT_CIEL_CLAIR_CAMS)
    _exiger(
        [s["localite_code"] for s in series] == sorted(loc),
        f"{contrat.nom_fichier(LOT_CIEL_CLAIR_CAMS)} ne couvre pas les {NB_POINTS} localités.",
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
    _exiger(len(series) == NB_POINTS, f"{contrat.prefixe_code} : {len(series)} séries.")
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
    _exiger(
        all(0 <= ligne["v"] <= NB_POINTS - 1 for ligne in lignes),
        f"{contrat.prefixe_code} : compte de jumeaux hors bornes.",
    )
    return len(lignes)


def upgrade() -> None:
    bind = op.get_bind()

    # 0. Garde-fous : source, grandeurs absentes, unités, localités, séries préexistantes.
    code_source = bind.execute(
        sa.text("SELECT code FROM sources WHERE id = :i"), {"i": SOURCE_ID}
    ).scalar_one_or_none()
    _exiger(code_source == SOURCE_CODE, f"source id {SOURCE_ID} = {code_source!r}.")
    deja = bind.execute(
        sa.text("SELECT code FROM grandeurs_referentiel WHERE code = ANY(:c) OR id = ANY(:i)"),
        {"c": list(GRANDEURS), "i": [i for i, _ in GRANDEURS.values()]},
    ).all()
    _exiger(not deja, f"grandeurs déjà présentes : {[r.code for r in deja]!r}.")
    unites = dict(
        bind.execute(
            sa.text("SELECT code, id FROM unites WHERE code = ANY(:c)"),
            {"c": sorted({u for _, u in GRANDEURS.values()})},
        ).all()
    )
    _exiger(len(unites) == 2, f"unités {sorted(unites)!r}.")
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

    # 1. Grandeurs du référentiel.
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
                "id": gid,
                "code": g,
                "libelle": LIBELLES[g],
                "unite": unites[unite],
                "description": DESCRIPTIONS[g],
            }
            for g, (gid, unite) in GRANDEURS.items()
        ],
    )

    # 2. Journalier : séries, mesures par COPY et audit par série.
    total = graver_lot(
        bind,
        REVISION,
        list(CONTRATS_CIEL_CLAIR_JOURNALIERS.values()),
        LOT_CIEL_CLAIR_CAMS,
        loc,
        _note,
    )
    _exiger(total == NB_MESURES_JOURNALIERES, f"{total} mesures journalières.")

    # 3. Mensuel : séries et mesures, audit ligne à ligne ; dégénérescence de pixel.
    total = sum(_graver_mensuel(bind, c, loc) for c in CONTRATS_CIEL_CLAIR_MENSUELS.values())
    _exiger(total == NB_MESURES_MENSUELLES, f"{total} mesures mensuelles.")
    total = sum(_graver_degenerescence(bind, c) for c in CONTRATS_CIEL_CLAIR_MENSUELS.values())
    _exiger(total == len(GRANDEURS_CIEL_CLAIR) * NB_POINTS, f"{total} lignes de dégénérescence.")

    bind.execute(sa.text("ANALYZE grandeurs_referentiel"))
    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE mesures_ressource"))
    bind.execute(sa.text("ANALYZE mesures_ressource_mensuelles"))
    bind.execute(sa.text("ANALYZE grandeurs_metier"))


def downgrade() -> None:
    bind = op.get_bind()
    codes_loc = _codes_localites()
    codes_mensuels = [
        c.code_serie(code) for c in CONTRATS_CIEL_CLAIR_MENSUELS.values() for code in codes_loc
    ]
    bind.execute(
        sa.text(
            "DELETE FROM grandeurs_metier WHERE grandeur_code = :g AND series_metadonnees_id IN "
            "(SELECT id FROM series_metadonnees WHERE code = ANY(:c))"
        ),
        {"g": DEGENERESCENCE, "c": codes_mensuels},
    )
    supprimer_lot(
        bind,
        REVISION,
        list(CONTRATS_CIEL_CLAIR_JOURNALIERS.values()),
        LOT_CIEL_CLAIR_CAMS,
        codes_loc,
    )
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
        sa.text("DELETE FROM grandeurs_referentiel WHERE code = ANY(:c)"), {"c": list(GRANDEURS)}
    )
    bind.execute(sa.text("ANALYZE grandeurs_referentiel"))
    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE mesures_ressource"))
    bind.execute(sa.text("ANALYZE mesures_ressource_mensuelles"))
    bind.execute(sa.text("ANALYZE grandeurs_metier"))
