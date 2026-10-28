"""revision_cams_mensuel_2021_2025

Revision ID: 0056
Revises: 0055
Create Date: 2026-10-28

**Révision du mensuel CAMS 2021-2025, par versionnement temporel non
destructif** (ADR-0037). CAMS Radiation a révisé ses années 2021-2025 après
leur gravure (sondage du 2026-09-30, migration 0030) ; 2005-2020 est inchangé
(ADR-0035). Les valeurs servies le 2026-10-28 sont gravées comme nouvelles
versions : pour chaque (série, année, mois) dont la valeur change, la ligne
courante est **close** (``valide_au``) et une nouvelle ligne courante est
insérée (``valide_du`` = même instant), portant le marqueur ``MARQUEUR`` en
commentaire éditorial. Rien n'est supprimé ; les lectures (API, services)
ne voient que les lignes courantes (``valide_au IS NULL``).

1. **Mesures brutes** : 426 séries ``cams_<ghi|dni|dhi>_mensuel_<localité>``,
   valeurs du CSV ``cams_<grandeur>_mensuel_revision_2026_10_28.csv.gz``
   (``LOT_REVISION_CAMS``, généré par ``ingest_cams_radiation_mensuel.py
   --revision``, qui exige 2005-2020 identique aux valeurs gravées).
   8 489 (GHI), 8 502 (DNI) et 8 481 (DHI) lignes versionnées sur 8 520 par
   grandeur (``NB_BRUTES_REVISEES``).
2. **Grandeurs dérivées du mensuel CAMS**, recalculées sur 2021-2025 par les
   formules de leurs migrations d'origine, sur les valeurs courantes, puis
   versionnées de même là où la valeur change (``version_formule`` inchangée :
   même méthode, données révisées) :

   - écarts relatifs CAMS − NASA (GHI, DNI, DHI ; formule de 0032) ;
   - fraction diffuse CAMS, mensuelle et annuelle (0040) ;
   - heures équivalentes pleines CAMS, mensuelles et annuelles, puis
     productible spécifique théorique depuis les HEP courantes (0038) ;
   - indice de clarté ``kt`` CAMS, mensuel et annuel (0041, fonctions pures
     ``services/grandeurs/kt.py``, paramètres figés de 0041).

   La **dégénérescence de pixel** (0042) dépend de l'identité des séries
   brutes : la migration vérifie que les groupes de séries CAMS identiques sont
   les mêmes avant et après la révision (aucune ligne à recalculer).
3. **Notes publiques** : la mise en garde de 0054 sur les 426 séries mensuelles
   CAMS est remplacée par celle de la révision gravée ; la phrase des 426 séries
   journalières CAMS sur la révision est mise à jour ; une phrase est ajoutée
   aux 994 séries dérivées CAMS.

**Instant de la révision** : ``clock_timestamp()``, lu une fois. Toutes les
migrations tournent dans une seule transaction (``migrations/env.py``) : les
lignes 2021-2025 insérées par 0030 lors d'un rejeu intégral ont pour
``valide_du`` le début de cette transaction (``now()``) ; les clore à ``now()``
violerait ``valide_au > valide_du``. La migration vérifie que l'instant est
postérieur au ``valide_du`` de toute ligne close.

Garde-fous : CSV couvrant exactement les 426 séries et 60 mois, une seule ligne
courante par clé, comptes exacts de lignes versionnées par famille, aucune
valeur dérivée nouvelle hors de son domaine, dégénérescence inchangée, phrases
présentes avant et après. ``downgrade`` supprime les nouvelles versions
(marqueur), rouvre les lignes qu'elles avaient closes et restaure les notes.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.lots_civ import (
    CONTRATS_CAMS,
    LOT_REVISION_CAMS,
    contrat_extension,
    points_nationaux,
)
from kuma_data_core.db.seeds.series_csv import lire_series
from kuma_data_core.services.grandeurs.kt import calculer_kt

# revision identifiers, used by Alembic.
revision: str = "0056"
down_revision: str | Sequence[str] | None = "0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVISION: str = "0056"
GRANDEURS: tuple[str, ...] = ("ghi", "dni", "dhi")
NB_POINTS: int = 142
NB_MOIS: int = 60  # 2021-2025
MARQUEUR: str = "Révision CAMS du 2026-10-28 (migration 0056, ADR-0037)."

# Lignes versionnées attendues (constat du 2026-10-28, voir ADR-0037).
NB_BRUTES_REVISEES: dict[str, int] = {"ghi": 8_489, "dni": 8_502, "dhi": 8_481}
NB_DERIVEES_REVISEES: dict[str, int] = {
    "ecart_relatif_ghi_cams_nasa": 8_489,
    "ecart_relatif_dni_cams_nasa": 8_502,
    "ecart_relatif_dhi_cams_nasa": 8_481,
    "fraction_diffuse": 9_230,
    "hep": 9_199,
    "productible_specifique_theorique": 9_199,
    "kt": 9_199,
}

# Paramètres de 0038 et 0041, figés ici à l'identique.
PR_THEORIQUE: str = "0.8"
CONSTANTE_SOLAIRE: float = 1361.0
MODELE_SOLAIRE = "spencer"

# Phrases de 0054 (mise en garde mensuelle, phrase journalière) et de remplacement.
_REVISION_0054: dict[str, str] = {
    "ghi": "+0,018 kWh/m²/jour en moyenne (jusqu'à 0,118)",
    "dni": "+0,025 kWh/m²/jour en moyenne (jusqu'à 0,154)",
    "dhi": "−0,002 kWh/m²/jour en moyenne (jusqu'à 0,031)",
}
_REVISION_GRAVEE: dict[str, str] = {
    "ghi": "+0,018 kWh/m²/jour en moyenne sur les 142 localités (jusqu'à 0,118)",
    "dni": "+0,025 kWh/m²/jour en moyenne sur les 142 localités (jusqu'à 0,154)",
    "dhi": "−0,002 kWh/m²/jour en moyenne sur les 142 localités (jusqu'à 0,031)",
}


def _ancienne_garde_mensuelle(g: str) -> str:
    return (
        " Révision de la source (ADR-0035) : CAMS a révisé 2021-2025 après la gravure de "
        "ces années (sondage du 2026-09-30) ; le 2026-10-28, la moyenne des jours servis "
        f"s'écarte des valeurs gravées de {_REVISION_0054[g]}, quand 2005-2020 "
        "est inchangé. Valeurs gravées conservées ; la série journalière CAMS suit la "
        "révision."
    )


def _nouvelle_garde_mensuelle(g: str) -> str:
    return (
        " Révision de la source (ADR-0037) : CAMS a révisé 2021-2025 après la gravure de "
        "ces années (sondage du 2026-09-30). Les valeurs servies le 2026-10-28 sont gravées "
        "par versionnement (migration 0056) : elles s'écartent des valeurs remplacées de "
        f"{_REVISION_GRAVEE[g]}. 2005-2020 est inchangé ; les valeurs remplacées restent "
        "en base, closes."
    )


def _ancienne_phrase_journaliere(g: str) -> str:
    return (
        "La moyenne des jours du mois redonne la série mensuelle CAMS à 0,0001 kWh/m²/jour "
        "près de 2005 à 2020 ; pour 2021-2025, CAMS a révisé ses valeurs après la gravure "
        f"du mensuel (écart moyen {_REVISION_0054[g]})."
    )


NOUVELLE_PHRASE_JOURNALIERE: str = (
    "La moyenne des jours du mois redonne la série mensuelle CAMS à 0,0001 kWh/m²/jour "
    "près, 2021-2025 compris depuis la révision du mensuel CAMS (migration 0056, ADR-0037)."
)
PHRASE_DERIVEES: str = (
    " Recalculée sur 2021-2025 après la révision du mensuel CAMS : valeurs remplacées "
    "versionnées, anciennes conservées closes (migration 0056, ADR-0037)."
)

# Colonnes d'identité d'une ligne de grandeurs_metier (hors période de validité).
_IDENTITE_GM: str = """
    gm.grandeur_code = n.grandeur_code AND gm.localite_id = n.localite_id
    AND gm.series_metadonnees_id = n.series_metadonnees_id
    AND gm.periode_type = n.periode_type AND gm.annee_debut = n.annee_debut
    AND gm.annee_fin = n.annee_fin AND gm.mois IS NOT DISTINCT FROM n.mois
    AND gm.version_formule = n.version_formule
"""


def _exiger(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(f"Migration {REVISION} : {message}")


def _localites() -> list[str]:
    return sorted(code for code, _, _, _ in points_nationaux())


def _codes(prefixe: str) -> list[str]:
    return [f"{prefixe}_{code}" for code in _localites()]


def _codes_derives() -> list[str]:
    prefixes = [f"ecart_{g}_cams_nasa" for g in GRANDEURS] + [
        "fraction_diffuse_cams",
        "hep_cams",
        "productible_specifique_theorique_cams",
        "kt_cams",
    ]
    return [c for p in prefixes for c in _codes(p)]


def _portant(bind: sa.Connection, fragment: str, codes: list[str]) -> set[str]:
    return {
        r.code
        for r in bind.execute(
            sa.text(
                "SELECT code FROM series_metadonnees "
                "WHERE code = ANY(:c) AND strpos(note_publique, :f) > 0"
            ),
            {"c": codes, "f": fragment},
        )
    }


# --- Versionnement générique --------------------------------------------------------


def _versionner_mensuel(bind: sa.Connection, instant: datetime) -> int:
    """Clôt et remplace les mesures mensuelles courantes qui diffèrent de ``rev_mensuel``."""
    bind.execute(
        sa.text(
            """
            CREATE TEMP TABLE a_versionner_mensuel ON COMMIT DROP AS
            SELECT m.id, r.valeur AS nouvelle
            FROM rev_mensuel r
            JOIN mesures_ressource_mensuelles m
                ON m.serie_id = r.serie_id AND m.annee = r.annee AND m.mois = r.mois
               AND m.valide_au IS NULL
            WHERE m.valeur IS DISTINCT FROM r.valeur
            """
        )
    )
    return _clore_et_inserer(bind, "mesures_ressource_mensuelles", "a_versionner_mensuel", instant)


def _clore_et_inserer(bind: sa.Connection, table: str, a_versionner: str, instant: datetime) -> int:
    """Clôt les lignes ``id`` de ``a_versionner`` et insère leurs remplaçantes (``nouvelle``)."""
    plus_recent = bind.execute(
        sa.text(f"SELECT MAX(t.valide_du) FROM {table} t JOIN {a_versionner} a ON a.id = t.id")
    ).scalar_one()
    _exiger(
        plus_recent is None or plus_recent < instant,
        f"instant {instant} non postérieur au valide_du {plus_recent} d'une ligne à clore.",
    )
    identite = (
        "serie_id, annee, mois"
        if table == "mesures_ressource_mensuelles"
        else "grandeur_code, localite_id, series_metadonnees_id, periode_type, annee_debut, "
        "annee_fin, mois, version_formule"
    )
    bind.execute(
        sa.text(
            f"UPDATE {table} t SET valide_au = :t, modifie_le = :t "
            f"FROM {a_versionner} a WHERE t.id = a.id"
        ),
        {"t": instant},
    )
    colonnes = ", ".join(f"t.{c.strip()}" for c in identite.split(","))
    n = bind.execute(
        sa.text(
            f"""
            INSERT INTO {table} (
                {identite}, valeur, valide_du, statut, niveau_confiance_derive,
                commentaire_editorial, cree_le, modifie_le
            )
            SELECT {colonnes}, a.nouvelle, :t, 'brut', t.niveau_confiance_derive, :m, :t, :t
            FROM {a_versionner} a JOIN {table} t ON t.id = a.id
            """
        ),
        {"t": instant, "m": MARQUEUR},
    ).rowcount
    bind.execute(sa.text(f"DROP TABLE {a_versionner}"))
    return int(n)


def _creer_nouvelles(bind: sa.Connection) -> None:
    bind.execute(
        sa.text(
            """
            CREATE TEMP TABLE gm_nouvelles (
                grandeur_code varchar, localite_id bigint, series_metadonnees_id bigint,
                periode_type varchar, annee_debut integer, annee_fin integer, mois integer,
                version_formule integer, valeur double precision
            ) ON COMMIT DROP
            """
        )
    )


def _versionner_grandeurs(bind: sa.Connection, instant: datetime, famille: str) -> int:
    """Versionne les lignes courantes de ``grandeurs_metier`` dont ``gm_nouvelles`` diffère."""
    nouvelles = bind.execute(sa.text("SELECT COUNT(*) FROM gm_nouvelles")).scalar_one()
    appariees = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM gm_nouvelles n JOIN grandeurs_metier gm ON "
            + _IDENTITE_GM
            + " AND gm.valide_au IS NULL"
        )
    ).scalar_one()
    _exiger(
        nouvelles > 0 and appariees == nouvelles,
        f"{famille} : {nouvelles} valeurs recalculées, {appariees} lignes courantes appariées.",
    )
    bind.execute(
        sa.text(
            "CREATE TEMP TABLE a_versionner_gm ON COMMIT DROP AS "
            "SELECT gm.id, n.valeur AS nouvelle FROM gm_nouvelles n JOIN grandeurs_metier gm ON "
            + _IDENTITE_GM
            + " AND gm.valide_au IS NULL WHERE gm.valeur IS DISTINCT FROM n.valeur"
        )
    )
    n = _clore_et_inserer(bind, "grandeurs_metier", "a_versionner_gm", instant)
    bind.execute(sa.text("DROP TABLE gm_nouvelles"))
    return n


# --- Recalcul des grandeurs dérivées (formules des migrations d'origine) -----------------

_SQL_ECARTS: str = """
    INSERT INTO gm_nouvelles
    SELECT :grandeur, se.localite_id, se.id, 'mensuel', mc.annee, mc.annee, mc.mois, 1,
           (mc.valeur - mn.valeur) / mn.valeur * 100.0
    FROM series_metadonnees se
    JOIN localites l ON l.id = se.localite_id
    JOIN series_metadonnees sc ON sc.code = 'cams_' || :brute || '_mensuel_' || l.code
    JOIN mesures_ressource_mensuelles mc
        ON mc.serie_id = sc.id AND mc.annee > 2020 AND mc.valide_au IS NULL
    JOIN series_metadonnees sn ON sn.code = 'nasa_power_' || :brute || '_mensuel_' || l.code
    JOIN mesures_ressource_mensuelles mn
        ON mn.serie_id = sn.id AND mn.annee = mc.annee AND mn.mois = mc.mois
       AND mn.valide_au IS NULL
    WHERE se.code = ANY(:codes)
"""

_CTE_FD: str = """
    WITH couples AS (
        SELECT sf.id AS serie_cible, sf.localite_id, md.annee, md.mois,
               md.valeur AS dhi, mg.valeur AS ghi,
               EXTRACT(
                   DAY FROM (make_date(md.annee, md.mois, 1) + INTERVAL '1 month - 1 day')
               )::int AS n_jours
        FROM unnest(CAST(:cibles AS text[]), CAST(:dhi AS text[]), CAST(:ghi AS text[]))
            AS p(cible, dhi, ghi)
        JOIN series_metadonnees sf ON sf.code = p.cible
        JOIN series_metadonnees sd ON sd.code = p.dhi
        JOIN mesures_ressource_mensuelles md
            ON md.serie_id = sd.id AND md.annee > 2020 AND md.valide_au IS NULL
        JOIN series_metadonnees sg ON sg.code = p.ghi
        JOIN mesures_ressource_mensuelles mg
            ON mg.serie_id = sg.id AND mg.annee = md.annee AND mg.mois = md.mois
           AND mg.valide_au IS NULL
    )
"""

_CTE_GHI: str = """
    WITH ghi AS (
        SELECT sc.id AS serie_cible, sc.localite_id, m.annee, m.mois,
               m.valeur::numeric AS ghi,
               EXTRACT(
                   DAY FROM (make_date(m.annee, m.mois, 1) + INTERVAL '1 month - 1 day')
               )::int AS n_jours
        FROM unnest(CAST(:cibles AS text[]), CAST(:amonts AS text[])) AS p(cible, amont)
        JOIN series_metadonnees sc ON sc.code = p.cible
        JOIN series_metadonnees sa ON sa.code = p.amont AND sa.localite_id = sc.localite_id
        JOIN mesures_ressource_mensuelles m
            ON m.serie_id = sa.id AND m.annee > 2020 AND m.valide_au IS NULL
           AND m.statut <> 'deprecie'
    )
"""


def _derivees(bind: sa.Connection, instant: datetime) -> dict[str, int]:
    """Recalcule et versionne les grandeurs dérivées du mensuel CAMS, 2021-2025."""
    loc = _localites()
    comptes: dict[str, int] = {}

    for g in GRANDEURS:  # écarts relatifs CAMS − NASA (0032)
        _creer_nouvelles(bind)
        bind.execute(
            sa.text(_SQL_ECARTS),
            {
                "grandeur": f"ecart_relatif_{g}_cams_nasa",
                "brute": g,
                "codes": _codes(f"ecart_{g}_cams_nasa"),
            },
        )
        comptes[f"ecart_relatif_{g}_cams_nasa"] = _versionner_grandeurs(bind, instant, f"écart {g}")

    params_fd = {
        "cibles": _codes("fraction_diffuse_cams"),
        "dhi": _codes("cams_dhi_mensuel"),
        "ghi": _codes("cams_ghi_mensuel"),
    }
    _creer_nouvelles(bind)  # fraction diffuse CAMS (0040)
    bind.execute(
        sa.text(
            _CTE_FD
            + """
            INSERT INTO gm_nouvelles
            SELECT 'fraction_diffuse', localite_id, serie_cible, 'mensuel', annee, annee, mois,
                   1, dhi / ghi
            FROM couples WHERE ghi > 0
            """
        ),
        params_fd,
    )
    bind.execute(
        sa.text(
            _CTE_FD
            + """
            INSERT INTO gm_nouvelles
            SELECT 'fraction_diffuse', localite_id, serie_cible, 'annuel', annee, annee, NULL,
                   1, (SUM(dhi::numeric * n_jours) / SUM(ghi::numeric * n_jours))::float8
            FROM couples
            GROUP BY localite_id, serie_cible, annee
            HAVING COUNT(*) = 12 AND SUM(ghi * n_jours) > 0
            """
        ),
        params_fd,
    )
    comptes["fraction_diffuse"] = _versionner_grandeurs(bind, instant, "fraction diffuse")

    params_hep = {"cibles": _codes("hep_cams"), "amonts": _codes("cams_ghi_mensuel")}
    _creer_nouvelles(bind)  # heures équivalentes pleines CAMS (0038)
    bind.execute(
        sa.text(
            _CTE_GHI
            + """
            INSERT INTO gm_nouvelles
            SELECT 'hep', localite_id, serie_cible, 'mensuel', annee, annee, mois, 1,
                   (ghi * n_jours)::float8
            FROM ghi
            """
        ),
        params_hep,
    )
    bind.execute(
        sa.text(
            _CTE_GHI
            + """
            INSERT INTO gm_nouvelles
            SELECT 'hep', localite_id, serie_cible, 'annuel', annee, annee, NULL, 1,
                   SUM(ghi * n_jours)::float8
            FROM ghi
            GROUP BY localite_id, serie_cible, annee
            HAVING COUNT(*) = 12
            """
        ),
        params_hep,
    )
    comptes["hep"] = _versionner_grandeurs(bind, instant, "HEP")

    _creer_nouvelles(bind)  # productible spécifique théorique, depuis les HEP courantes (0038)
    bind.execute(
        sa.text(
            """
            INSERT INTO gm_nouvelles
            SELECT 'productible_specifique_theorique', sp.localite_id, sp.id, gm.periode_type,
                   gm.annee_debut, gm.annee_fin, gm.mois, 1,
                   (gm.valeur::numeric * CAST(:pr AS numeric))::float8
            FROM unnest(CAST(:cibles AS text[]), CAST(:amonts AS text[])) AS p(cible, amont)
            JOIN series_metadonnees sp ON sp.code = p.cible
            JOIN series_metadonnees sh ON sh.code = p.amont AND sh.localite_id = sp.localite_id
            JOIN grandeurs_metier gm
                ON gm.series_metadonnees_id = sh.id AND gm.grandeur_code = 'hep'
               AND gm.version_formule = 1 AND gm.valide_au IS NULL
               AND gm.statut <> 'deprecie' AND gm.annee_debut > 2020
            """
        ),
        {
            "pr": PR_THEORIQUE,
            "cibles": _codes("productible_specifique_theorique_cams"),
            "amonts": _codes("hep_cams"),
        },
    )
    comptes["productible_specifique_theorique"] = _versionner_grandeurs(bind, instant, "PST")

    # Indice de clarté kt CAMS (0041) : fonctions pures sur toute la série 2005-2025.
    latitudes = {
        r.code: (r.id, float(r.latitude))
        for r in bind.execute(
            sa.text("SELECT code, id, latitude FROM localites WHERE code = ANY(:c)"), {"c": loc}
        )
    }
    series_kt = dict(
        bind.execute(
            sa.text("SELECT code, id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": _codes("kt_cams")},
        ).all()
    )
    ghi: dict[str, dict[tuple[int, int], float]] = defaultdict(dict)
    for r in bind.execute(
        sa.text(
            """
            SELECT s.code, m.annee, m.mois, m.valeur
            FROM series_metadonnees s JOIN mesures_ressource_mensuelles m
                ON m.serie_id = s.id AND m.valide_au IS NULL
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": _codes("cams_ghi_mensuel")},
    ):
        ghi[r.code.removeprefix("cams_ghi_mensuel_")][(r.annee, r.mois)] = r.valeur
    lignes: list[dict[str, Any]] = []
    for code in loc:
        _exiger(len(ghi[code]) == 21 * 12, f"GHI CAMS {code} incomplet.")
        localite_id, latitude = latitudes[code]
        for c in calculer_kt(
            ghi[code], latitude, constante_solaire=CONSTANTE_SOLAIRE, modele=MODELE_SOLAIRE
        ):
            if c["annee"] > 2020:
                _exiger(0.0 < c["valeur"] < 1.0, f"kt {code} {c!r} hors de ]0, 1[.")
                lignes.append(
                    {
                        "l": localite_id,
                        "s": series_kt[f"kt_cams_{code}"],
                        "p": c["periode_type"],
                        "a": c["annee"],
                        "m": c["mois"],
                        "v": c["valeur"],
                    }
                )
    _creer_nouvelles(bind)
    bind.execute(
        sa.text("INSERT INTO gm_nouvelles VALUES ('kt', :l, :s, :p, :a, :a, :m, 1, :v)"), lignes
    )
    comptes["kt"] = _versionner_grandeurs(bind, instant, "kt")
    return comptes


def _groupes_identiques(bind: sa.Connection) -> set[frozenset[int]]:
    """Groupes de séries mensuelles CAMS identiques mois par mois (valeurs courantes)."""
    groupes: dict[tuple[str, str], set[int]] = defaultdict(set)
    for r in bind.execute(
        sa.text(
            """
            SELECT s.grandeur_code, s.id,
                   md5(array_agg(m.annee * 100 + m.mois ORDER BY m.annee, m.mois)::text
                       || array_agg(m.valeur ORDER BY m.annee, m.mois)::text) AS empreinte
            FROM series_metadonnees s JOIN mesures_ressource_mensuelles m
                ON m.serie_id = s.id AND m.valide_au IS NULL AND m.statut <> 'deprecie'
            WHERE s.code = ANY(:c)
            GROUP BY s.grandeur_code, s.id
            """
        ),
        {"c": [c for g in GRANDEURS for c in _codes(f"cams_{g}_mensuel")]},
    ):
        groupes[(r.grandeur_code, r.empreinte)].add(r.id)
    return {frozenset(ids) for ids in groupes.values()}


def upgrade() -> None:
    bind = op.get_bind()
    instant = bind.execute(sa.text("SELECT clock_timestamp()")).scalar_one()
    loc = _localites()
    _exiger(len(loc) == NB_POINTS, f"{len(loc)} localités, {NB_POINTS} attendues.")
    codes_mensuels = {g: _codes(f"cams_{g}_mensuel") for g in GRANDEURS}
    codes_journaliers = {g: _codes(f"cams_{g}_journalier") for g in GRANDEURS}
    for g in GRANDEURS:
        _exiger(
            _portant(bind, _ancienne_garde_mensuelle(g), codes_mensuels[g])
            == set(codes_mensuels[g]),
            f"mise en garde mensuelle {g} de 0054 introuvable.",
        )
        _exiger(
            _portant(bind, _ancienne_phrase_journaliere(g), codes_journaliers[g])
            == set(codes_journaliers[g]),
            f"phrase journalière {g} de 0054 introuvable.",
        )
    deja = bind.execute(
        sa.text(
            "SELECT (SELECT COUNT(*) FROM mesures_ressource_mensuelles "
            "WHERE commentaire_editorial = :m) + (SELECT COUNT(*) FROM grandeurs_metier "
            "WHERE commentaire_editorial = :m)"
        ),
        {"m": MARQUEUR},
    ).scalar_one()
    _exiger(deja == 0, f"{deja} ligne(s) déjà marquée(s) par la révision.")
    groupes_avant = _groupes_identiques(bind)

    # 1. Mesures brutes révisées, depuis le CSV de révision.
    serie_id = dict(
        bind.execute(
            sa.text("SELECT code, id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": [c for cs in codes_mensuels.values() for c in cs]},
        ).all()
    )
    _exiger(len(serie_id) == 3 * NB_POINTS, f"{len(serie_id)} séries mensuelles CAMS.")
    bind.execute(
        sa.text(
            "CREATE TEMP TABLE rev_mensuel (serie_id bigint, annee smallint, mois smallint, "
            "valeur double precision) ON COMMIT DROP"
        )
    )
    brutes: dict[str, int] = {}
    for g in GRANDEURS:
        series = lire_series(contrat_extension(CONTRATS_CAMS[g]), LOT_REVISION_CAMS)
        _exiger(
            [s["localite_code"] for s in series] == loc
            and all(len(s["mesures"]) == NB_MOIS for s in series),
            f"CSV de révision {g} : couverture inattendue.",
        )
        bind.execute(sa.text("TRUNCATE rev_mensuel"))
        bind.execute(
            sa.text("INSERT INTO rev_mensuel VALUES (:s, :a, :m, :v)"),
            [
                {"s": serie_id[s["code"]], "a": a, "m": mo, "v": v}
                for s in series
                for a, mo, v in s["mesures"]
            ],
        )
        couvertes = bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM rev_mensuel r JOIN mesures_ressource_mensuelles m "
                "ON m.serie_id = r.serie_id AND m.annee = r.annee AND m.mois = r.mois "
                "AND m.valide_au IS NULL"
            )
        ).scalar_one()
        _exiger(couvertes == NB_POINTS * NB_MOIS, f"{g} : {couvertes} lignes courantes appariées.")
        brutes[g] = _versionner_mensuel(bind, instant)
    _exiger(brutes == NB_BRUTES_REVISEES, f"mesures versionnées {brutes!r}.")

    # 2. Grandeurs dérivées, puis dégénérescence inchangée.
    derivees = _derivees(bind, instant)
    _exiger(derivees == NB_DERIVEES_REVISEES, f"grandeurs versionnées {derivees!r}.")
    _exiger(_groupes_identiques(bind) == groupes_avant, "groupes de séries identiques changés.")

    # 3. Notes publiques.
    for g in GRANDEURS:
        bind.execute(
            sa.text(
                "UPDATE series_metadonnees SET note_publique = replace(note_publique, :a, :b) "
                "WHERE code = ANY(:c)"
            ),
            {
                "a": _ancienne_garde_mensuelle(g),
                "b": _nouvelle_garde_mensuelle(g),
                "c": codes_mensuels[g],
            },
        )
        bind.execute(
            sa.text(
                "UPDATE series_metadonnees SET note_publique = replace(note_publique, :a, :b) "
                "WHERE code = ANY(:c)"
            ),
            {
                "a": _ancienne_phrase_journaliere(g),
                "b": NOUVELLE_PHRASE_JOURNALIERE,
                "c": codes_journaliers[g],
            },
        )
        _exiger(
            _portant(bind, _nouvelle_garde_mensuelle(g), codes_mensuels[g])
            == set(codes_mensuels[g]),
            f"nouvelle mise en garde {g} mal répartie.",
        )
    bind.execute(
        sa.text(
            "UPDATE series_metadonnees SET note_publique = note_publique || :p WHERE code = ANY(:c)"
        ),
        {"p": PHRASE_DERIVEES, "c": _codes_derives()},
    )
    _exiger(
        _portant(bind, PHRASE_DERIVEES, _codes_derives()) == set(_codes_derives()),
        "phrase des séries dérivées mal répartie.",
    )
    bind.execute(sa.text("ANALYZE mesures_ressource_mensuelles"))
    bind.execute(sa.text("ANALYZE grandeurs_metier"))


def _rouvrir(bind: sa.Connection, table: str, identite: list[str]) -> int:
    """Supprime les versions marquées et rouvre les lignes qu'elles avaient closes."""
    cles = ", ".join(identite)
    bind.execute(
        sa.text(
            f"CREATE TEMP TABLE a_retirer ON COMMIT DROP AS SELECT id, {cles}, valide_du "
            f"FROM {table} WHERE commentaire_editorial = :m AND valide_au IS NULL"
        ),
        {"m": MARQUEUR},
    )
    bind.execute(sa.text(f"DELETE FROM {table} t USING a_retirer a WHERE t.id = a.id"))
    egalites = " AND ".join(
        f"t.{c} IS NOT DISTINCT FROM a.{c}" if c == "mois" else f"t.{c} = a.{c}" for c in identite
    )
    n = bind.execute(
        sa.text(
            f"UPDATE {table} t SET valide_au = NULL, modifie_le = clock_timestamp() "
            f"FROM a_retirer a WHERE {egalites} AND t.valide_au = a.valide_du"
        )
    ).rowcount
    retires = bind.execute(sa.text("SELECT COUNT(*) FROM a_retirer")).scalar_one()
    bind.execute(sa.text("DROP TABLE a_retirer"))
    _exiger(n == retires, f"{table} : {retires} versions retirées, {n} lignes rouvertes.")
    return int(n)


def downgrade() -> None:
    bind = op.get_bind()
    _rouvrir(
        bind,
        "grandeurs_metier",
        [
            "grandeur_code",
            "localite_id",
            "series_metadonnees_id",
            "periode_type",
            "annee_debut",
            "annee_fin",
            "mois",
            "version_formule",
        ],
    )
    _rouvrir(bind, "mesures_ressource_mensuelles", ["serie_id", "annee", "mois"])
    bind.execute(
        sa.text(
            """
            UPDATE series_metadonnees
            SET note_publique = left(note_publique, length(note_publique) - length(:p))
            WHERE code = ANY(:c) AND right(note_publique, length(:p)) = :p
            """
        ),
        {"p": PHRASE_DERIVEES, "c": _codes_derives()},
    )
    for g in GRANDEURS:
        for a, b, prefixe in (
            (_nouvelle_garde_mensuelle(g), _ancienne_garde_mensuelle(g), f"cams_{g}_mensuel"),
            (NOUVELLE_PHRASE_JOURNALIERE, _ancienne_phrase_journaliere(g), f"cams_{g}_journalier"),
        ):
            bind.execute(
                sa.text(
                    "UPDATE series_metadonnees SET note_publique = replace(note_publique, :a, :b) "
                    "WHERE code = ANY(:c)"
                ),
                {"a": a, "b": b, "c": _codes(prefixe)},
            )
    bind.execute(sa.text("ANALYZE mesures_ressource_mensuelles"))
    bind.execute(sa.text("ANALYZE grandeurs_metier"))
