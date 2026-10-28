"""rayonnement_cams_journalier

Revision ID: 0054
Revises: 0053
Create Date: 2026-10-28

**GHI, DNI et DHI journaliers CAMS Radiation aux 142 localités** : deuxième
source journalière du rayonnement, à côté de NASA POWER (0026, 0046). CAMS
(Heliosat-4, McClear) calcule l'irradiation au point demandé depuis les images
Meteosat, là où NASA POWER sert une maille de 0,5° × 0,625° : 126 séries
distinctes pour 142 localités, contre 35 pour NASA (ADR-0027). Le mensuel CAMS
est gravé depuis 0018 (ADR-0011, ADR-0013, ADR-0018).

| Grandeur | Colonne CAMS | Conversion | Période | Jours par série | Lacunes | Mesures |
|---|---|---|---|---:|---:|---:|
| ``ghi`` | ``GHI`` | Wh/m² ÷ 1000 → kWh/m²/jour | 2005-2025 | 7 670 | 622 | 1 088 518 |
| ``dni`` | ``BNI`` | Wh/m² ÷ 1000 → kWh/m²/jour | 2005-2025 | 7 670 | 622 | 1 088 518 |
| ``dhi`` | ``DHI`` | Wh/m² ÷ 1000 → kWh/m²/jour | 2005-2025 | 7 670 | 622 | 1 088 518 |

Soit **426 séries** ``cams_<grandeur>_journalier_<localité>``
(``granularite='journalier'``, table ``mesures_ressource``) et **3 265 554
mesures**, source ``cams_radiation`` (id 13), méthode ``modele_satellitaire``,
confiance **B**. Contrats :
``rayonnement_cams_journalier_civ.CONTRATS_CAMS_JOURNALIERS``. Jeu ADS
``cams-solar-radiation-timeseries`` (CAMS Radiation Service v4.6, consulté le
2026-10-28), tous ciels, ``time_step=1day``, temps universel (jour civil local,
UTC+0), coordonnées du référentiel.

**Lacunes** : CAMS ne sert aucune valeur les 2005-01-11, 2005-01-12, 2006-01-10 et
2006-01-11 (images Meteosat manquantes), ni le 2006-09-23 dans 54 localités de
l'est et du sud-est. Ces jours sont des lacunes explicites du CSV
(``lacunes_admises``), non gravées : la migration vérifie que les jours absents de
chaque série sont exactement ceux-là.

**Cohérence avec le mensuel CAMS gravé** (moyenne des jours servis − mensuel) :
2005-2020 hors mois à lacune, à 0,0001 kWh/m²/jour près (26 926 mois-localités
par grandeur). Mais CAMS a **révisé 2021-2025** depuis la gravure de ces années
(sondage du 2026-09-30, ADR-0018) : le mensuel servi le 2026-10-28 redonne la
moyenne des jours (vérifié à Sandégué), plus les valeurs gravées. Écart moyen
des 8 520 mois-localités : GHI +0,018 kWh/m²/jour (jusqu'à 0,118), DNI +0,025
(jusqu'à 0,154), DHI −0,002 (jusqu'à 0,031). Les valeurs mensuelles gravées sont
conservées ; une mise en garde est ajoutée à la note publique des **426 séries
mensuelles CAMS** (métadonnée seulement).

Valeurs lues hors-ligne dans les CSV gzip committés
(``seeds/donnees/cams_<grandeur>_journalier_civ142.csv.gz``, générés par
``scripts/ingest_cams_radiation_journalier.py``) et validées par
``series_csv.lire_series_journalieres``. Insertion par ``COPY`` avec l'audit par
série (``gravure_journaliere``, ADR-0031).

Garde-fous : identité de la source, unités du référentiel, 142 localités, aucune
série journalière CAMS préexistante, couverture exacte des CSV, lacunes
attendues, 426 séries et 3 265 554 mesures, mise en garde absente avant et
présente après sur les 426 séries mensuelles. ``downgrade`` retire la mise en
garde, puis supprime mesures et séries.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.gravure_journaliere import graver_lot, supprimer_lot
from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.rayonnement_cams_journalier_civ import (
    CONTRATS_CAMS_JOURNALIERS,
    LOT_CAMS_JOURNALIER,
)
from kuma_data_core.db.seeds.series_csv import ContratSerie, lire_series_journalieres

# revision identifiers, used by Alembic.
revision: str = "0054"
down_revision: str | Sequence[str] | None = "0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVISION: str = "0054"
SOURCE_ID: int = 13
SOURCE_CODE: str = "cams_radiation"
NB_POINTS: int = 142
NB_MESURES_ATTENDU: int = 3_265_554  # 3 × (142 × 7 670 − 622)
UNITE: str = "kwh_par_m2_jour"

JOURS_SANS_IMAGES: tuple[date, ...] = (
    date(2005, 1, 11),
    date(2005, 1, 12),
    date(2006, 1, 10),
    date(2006, 1, 11),
)
"""Jours que CAMS ne sert à aucune des 142 localités."""
JOUR_PARTIEL: date = date(2006, 9, 23)
LOCALITES_JOUR_PARTIEL: frozenset[str] = frozenset(
    {
        "civ_agneby_tiassa",
        "civ_belier",
        "civ_bounkani",
        "civ_dep_abengourou",
        "civ_dep_abidjan",
        "civ_dep_aboisso",
        "civ_dep_adiake",
        "civ_dep_adzope",
        "civ_dep_agboville",
        "civ_dep_agnibilekrou",
        "civ_dep_akoupe",
        "civ_dep_alepe",
        "civ_dep_arrah",
        "civ_dep_bettie",
        "civ_dep_bocanda",
        "civ_dep_bondoukou",
        "civ_dep_bongouanou",
        "civ_dep_bouake",
        "civ_dep_bouna",
        "civ_dep_dabakala",
        "civ_dep_dabou",
        "civ_dep_daoukro",
        "civ_dep_didievi",
        "civ_dep_dimbokro",
        "civ_dep_doropo",
        "civ_dep_grand_bassam",
        "civ_dep_grand_lahou",
        "civ_dep_jacqueville",
        "civ_dep_kong",
        "civ_dep_kouassi_kouassikro",
        "civ_dep_koun_fao",
        "civ_dep_m_bahiakro",
        "civ_dep_m_batto",
        "civ_dep_nassian",
        "civ_dep_ouelle",
        "civ_dep_prikro",
        "civ_dep_sandegue",
        "civ_dep_sikensi",
        "civ_dep_tanda",
        "civ_dep_tehini",
        "civ_dep_tiapoum",
        "civ_dep_tiassale",
        "civ_dep_toumodi",
        "civ_dep_transua",
        "civ_dep_yakasse_attobrou",
        "civ_gbeke",
        "civ_gontougo",
        "civ_grands_ponts",
        "civ_iffou",
        "civ_indenie_djuablin",
        "civ_la_me",
        "civ_moronou",
        "civ_n_zi",
        "civ_sud_comoe",
    }
)
"""Localités que CAMS ne sert pas le 2006-09-23 (est et sud-est du pays)."""

# Comparaison au rayonnement journalier NASA POWER (0026, 0046), mêmes jours servis,
# 142 localités, 2005-2025 : (moyenne CAMS, moyenne NASA, écart relatif, localité
# d'écart minimal, localité d'écart maximal).
COMPARAISON_NASA: dict[str, str] = {
    "ghi": (
        "Face au GHI journalier NASA POWER aux mêmes localités et jours, CAMS est plus "
        "élevé de 10,9 % en moyenne (5,36 contre 4,84 kWh/m²/jour ; de −0,03 à Abidjan à "
        "+0,87 kWh/m²/jour à Fresco selon la localité)."
    ),
    "dni": (
        "Face au DNI journalier NASA POWER aux mêmes localités et jours, CAMS est plus "
        "élevé de 57 % en moyenne (3,85 contre 2,46 kWh/m²/jour ; de +0,61 à Abidjan à "
        "+2,07 kWh/m²/jour à Fresco) : NASA reste l'aberrant bas du DNI (ADR-0012, ADR-0017)."
    ),
    "dhi": (
        "Face au DHI journalier NASA POWER aux mêmes localités et jours, CAMS est plus "
        "élevé de 3,8 % en moyenne (2,61 contre 2,51 kWh/m²/jour ; de −0,18 à Kaniasso à "
        "+0,27 kWh/m²/jour à Divo)."
    ),
}
LIBELLES: dict[str, str] = {
    "ghi": "Rayonnement global horizontal (GHI)",
    "dni": "Rayonnement direct normal (DNI, colonne BNI)",
    "dhi": "Rayonnement diffus horizontal (DHI)",
}
REVISION_2021_2025: dict[str, str] = {
    "ghi": "+0,018 kWh/m²/jour en moyenne (jusqu'à 0,118)",
    "dni": "+0,025 kWh/m²/jour en moyenne (jusqu'à 0,154)",
    "dhi": "−0,002 kWh/m²/jour en moyenne (jusqu'à 0,031)",
}


def _note_journaliere(contrat: ContratSerie, _serie: dict[str, Any]) -> str:
    g = contrat.grandeur_code
    return (
        f"{LIBELLES[g]} journalier CAMS Radiation (Copernicus ; Heliosat-4 et McClear, "
        "service v4.6), tous ciels : irradiation du jour UTC (jour civil local, UTC+0) au "
        "point de la localité, en kWh/m²/jour (Wh/m² ÷ 1000), 2005-2025, telle que servie. "
        "Jours non servis par CAMS (images Meteosat manquantes), laissés en lacune, jamais "
        "bouchés : 2005-01-11, 2005-01-12, 2006-01-10 et 2006-01-11 partout, et 2006-09-23 "
        "dans 54 localités de l'est et du sud-est. La moyenne des jours du mois redonne la "
        "série mensuelle CAMS à 0,0001 kWh/m²/jour près de 2005 à 2020 ; pour 2021-2025, "
        "CAMS a révisé ses valeurs après la gravure du mensuel (écart moyen "
        f"{REVISION_2021_2025[g]}). {COMPARAISON_NASA[g]} Estimation satellitaire, jamais "
        "une mesure au sol. Confiance B (ADR-0011, ADR-0035). Source : Copernicus "
        "Atmosphere Monitoring Service (CAMS), 2026."
    )


def _mise_en_garde_mensuelle(grandeur: str) -> str:
    return (
        " Révision de la source (ADR-0035) : CAMS a révisé 2021-2025 après la gravure de "
        "ces années (sondage du 2026-09-30) ; le 2026-10-28, la moyenne des jours servis "
        f"s'écarte des valeurs gravées de {REVISION_2021_2025[grandeur]}, quand 2005-2020 "
        "est inchangé. Valeurs gravées conservées ; la série journalière CAMS suit la "
        "révision."
    )


def _codes_localites() -> list[str]:
    return sorted(code for code, _, _, _ in points_nationaux())


def _contrats() -> list[ContratSerie]:
    return list(CONTRATS_CAMS_JOURNALIERS.values())


def _codes_mensuels(grandeur: str) -> list[str]:
    return [f"cams_{grandeur}_mensuel_{code}" for code in _codes_localites()]


def _portant(bind: sa.Connection, fragment: str) -> set[str]:
    return {
        row.code
        for row in bind.execute(
            sa.text("SELECT code FROM series_metadonnees WHERE strpos(note_publique, :f) > 0"),
            {"f": fragment},
        )
    }


def upgrade() -> None:
    bind = op.get_bind()
    contrats = _contrats()

    # 0. Garde-fous : source, unités, localités, séries préexistantes, lacunes.
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
            {"g": list(CONTRATS_CAMS_JOURNALIERS)},
        ).all()
    }
    if unites != dict.fromkeys(CONTRATS_CAMS_JOURNALIERS, UNITE):
        raise RuntimeError(f"Migration {REVISION} : unités {unites!r}, {UNITE!r} attendue.")
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
        sa.text(
            """
            SELECT code FROM series_metadonnees
            WHERE code = ANY(:codes)
               OR (source_id = :src AND granularite = 'journalier' AND grandeur_code = ANY(:g))
            """
        ),
        {
            "codes": [c.code_serie(code) for c in contrats for code in codes_loc],
            "src": SOURCE_ID,
            "g": list(CONTRATS_CAMS_JOURNALIERS),
        },
    ).all()
    if preexistantes:
        raise RuntimeError(
            f"Migration {REVISION} : séries déjà présentes : {[r.code for r in preexistantes]!r}."
        )
    for contrat in contrats:
        for s in lire_series_journalieres(contrat, LOT_CAMS_JOURNALIER):
            attendues = list(JOURS_SANS_IMAGES)
            if s["localite_code"] in LOCALITES_JOUR_PARTIEL:
                attendues.append(JOUR_PARTIEL)
            if s["lacunes"] != attendues:
                raise RuntimeError(
                    f"Migration {REVISION} : {s['code']} : lacunes {s['lacunes']!r}, "
                    f"{attendues!r} attendues."
                )
    for grandeur in CONTRATS_CAMS_JOURNALIERS:
        mensuelles = set(_codes_mensuels(grandeur))
        presentes = {
            r.code
            for r in bind.execute(
                sa.text("SELECT code FROM series_metadonnees WHERE code = ANY(:c)"),
                {"c": sorted(mensuelles)},
            )
        }
        if presentes != mensuelles:
            raise RuntimeError(
                f"Migration {REVISION} : séries mensuelles CAMS {grandeur} incomplètes."
            )
        if _portant(bind, _mise_en_garde_mensuelle(grandeur)):
            raise RuntimeError(f"Migration {REVISION} : mise en garde {grandeur} déjà présente.")

    # 1. Séries journalières, mesures par COPY et audit par série.
    total = graver_lot(bind, REVISION, contrats, LOT_CAMS_JOURNALIER, loc, _note_journaliere)
    if total != NB_MESURES_ATTENDU:
        raise RuntimeError(
            f"Migration {REVISION} : {total} mesures, {NB_MESURES_ATTENDU} attendues."
        )

    # 2. Mise en garde sur la révision 2021-2025, aux 426 séries mensuelles CAMS.
    for grandeur in CONTRATS_CAMS_JOURNALIERS:
        phrase = _mise_en_garde_mensuelle(grandeur)
        bind.execute(
            sa.text(
                "UPDATE series_metadonnees SET note_publique = note_publique || :p "
                "WHERE code = ANY(:c)"
            ),
            {"p": phrase, "c": _codes_mensuels(grandeur)},
        )
        if _portant(bind, phrase) != set(_codes_mensuels(grandeur)):
            raise RuntimeError(f"Migration {REVISION} : mise en garde {grandeur} mal répartie.")
    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE mesures_ressource"))


def downgrade() -> None:
    bind = op.get_bind()
    for grandeur in CONTRATS_CAMS_JOURNALIERS:
        bind.execute(
            sa.text(
                """
                UPDATE series_metadonnees
                SET note_publique = left(note_publique, length(note_publique) - length(:p))
                WHERE code = ANY(:c) AND right(note_publique, length(:p)) = :p
                """
            ),
            {"p": _mise_en_garde_mensuelle(grandeur), "c": _codes_mensuels(grandeur)},
        )
    supprimer_lot(bind, REVISION, _contrats(), LOT_CAMS_JOURNALIER, _codes_localites())
    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE mesures_ressource"))
