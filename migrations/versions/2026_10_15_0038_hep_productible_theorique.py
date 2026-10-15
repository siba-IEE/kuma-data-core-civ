"""hep_productible_theorique

Revision ID: 0038
Revises: 0034
Create Date: 2026-10-15

Matérialise les **heures équivalentes pleines** (``hep``, id 1, unité
``heure_equivalente_pleine``) et le **productible spécifique théorique**
(``productible_specifique_theorique``, id 4, unité ``kwh_par_kwc_periode``),
grandeurs F1 ``stockee`` seedées en 0002, aux **142 localités**, depuis le GHI
**mensuel** des **4 sources** (ADR-0023) :

    HEP_mensuel(a, m) := GHI(a, m) × n_jours(a, m)
    HEP_annuel(a)     := Σ_{m=1..12} HEP_mensuel(a, m)   (années complètes seulement)
    PST(période)      := HEP(période) × 0,8              (mensuel et annuel)

``GHI(a, m)`` est la moyenne journalière du mois (kWh/m²/jour). C'est la
formule de la fiche ``docs/methodologie/grandeurs/hep.md`` (somme des GHI
journaliers du mois, convention STC 1 kWh/m² ↔ 1 h_eq), **version 1
inchangée** : sur les jours d'un mois, Σ GHI(t) = n_jours × moyenne ; seule
l'entrée change de grain, comme pour la fraction diffuse (ADR-0014). Le
productible suit la fiche ``productible_specifique_theorique.md`` (PR théorique
fixe 0,8) et se calcule **depuis les lignes ``hep`` gravées** : sa complétude
est héritée par construction. Ses lignes mensuelles relèvent de
``productible_specifique_theorique`` (``periode_type='mensuel'``), pas de
``productible_mensuel`` (id 6, désactivée au référentiel) — ADR-0023.

Une série par (grandeur, source, localité), source ``kuma_calculs``,
``calcul_derive``, ``granularite`` NULL, codes ``hep_<source>_<localité>`` et
``productible_specifique_theorique_<source>_<localité>`` :

======================  ===========  =====================================
Source (jeton)          Période      Lignes par localité et par grandeur
======================  ===========  =====================================
NASA POWER (nasa_power) 1991-2025    420 mensuelles + 35 annuelles
CAMS (cams)             2005-2025    252 mensuelles + 21 annuelles
SARAH-3 (sarah3)        2005-2023    228 mensuelles + 19 annuelles
ERA5 (era5)             2005-2023    228 mensuelles + 19 annuelles
======================  ===========  =====================================

Soit **1 136 séries** et 2 × 173 524 = **347 048 lignes** (confiance B, statut
brut). Les séries dérivées d'ERA5 portent la mise en garde du saut 2021, même
phrase que la migration 0033.

Calcul **hors-ligne, en SQL**, par jointure sur les séries GHI mensuelles
désignées **par leur code** (les séries journalières NASA ne peuvent pas s'y
glisser). Produits et sommes en ``numeric`` : les GHI gravés (4 décimales) sont
relus exactement, le résultat est arrondi une seule fois en ``float8`` —
reproductible au bit près, indépendamment de l'ordre d'agrégation.

Garde-fous : grandeurs actives en version 1 avec leur unité ; aucune série ni
ligne ``hep`` ou productible préexistante ; chaque série amont complète (12 mois
× années de la source, mesures courantes) ; comptes exacts par (grandeur,
source, période) ; domaine ``0 < HEP ≤ 12 h_eq par jour de la période`` ;
Σ HEP mensuel = HEP annuel. ``ANALYZE`` avant le calcul et en fin de migration.
``downgrade`` supprime les lignes puis les séries ; les grandeurs (seed 0002)
sont conservées.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import NamedTuple

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.lots_civ import (
    CONTRATS_CAMS,
    CONTRATS_ERA5,
    CONTRATS_NASA,
    CONTRATS_SARAH3,
    FIN_EXTENSION,
    points_nationaux,
)
from kuma_data_core.db.seeds.series_csv import ContratSerie

# revision identifiers, used by Alembic.
revision: str = "0038"
down_revision: str | Sequence[str] | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANDEUR_HEP: str = "hep"
GRANDEUR_PST: str = "productible_specifique_theorique"
UNITES_ATTENDUES: dict[str, str] = {
    GRANDEUR_HEP: "heure_equivalente_pleine",
    GRANDEUR_PST: "kwh_par_kwc_periode",
}
SOURCE_CALCUL: str = "kuma_calculs"
VERSION_FORMULE: int = 1
PR_THEORIQUE: Decimal = Decimal("0.8")  # fiche productible_specifique_theorique, § 3
HEP_MAX_PAR_JOUR: int = 12  # h_eq/jour : au-delà du rayonnement extraterrestre (~10,5)
NB_POINTS: int = 142
NB_SERIES_ATTENDU: int = 1_136  # 2 grandeurs × 4 sources × 142 localités
NB_LIGNES_ATTENDU: int = 347_048  # 2 × 142 × (455 + 273 + 247 + 247)

# Même phrase que la migration 0033 (ADR-0018), ajoutée aux séries dérivées d'ERA5.
CAVEAT_ERA5: str = (
    " Mise en garde : saut probable du produit PVGIS-ERA5 en 2021 (moyenne nationale "
    "GHI +3,6 %, DNI +7,7 % par rapport à 2016-2020, environ trois fois la variabilité "
    "interannuelle), absent des autres sources ; valeurs 2021-2023 à interpréter avec "
    "prudence (ADR-0018)."
)


class SourceGhi(NamedTuple):
    """Une source de GHI mensuel : jeton des codes de série, libellé, contrat amont."""

    jeton: str  # dans les codes de série, ex. "nasa_power"
    libelle: str  # dans les libellés, ex. "NASA POWER"
    contrat: ContratSerie  # GHI mensuel des lots (période de base)

    @property
    def annee_debut(self) -> int:
        return self.contrat.annee_debut

    @property
    def annee_fin(self) -> int:
        return FIN_EXTENSION[self.contrat.source_code]  # prolongée par 0030 (ADR-0018)

    @property
    def nb_annees(self) -> int:
        return self.annee_fin - self.annee_debut + 1

    def code_amont(self, localite_code: str) -> str:
        return self.contrat.code_serie(localite_code)


SOURCES_GHI: tuple[SourceGhi, ...] = (
    SourceGhi("nasa_power", "NASA POWER", CONTRATS_NASA["ghi"]),
    SourceGhi("cams", "CAMS", CONTRATS_CAMS["ghi"]),
    SourceGhi("sarah3", "SARAH-3", CONTRATS_SARAH3["ghi"]),
    SourceGhi("era5", "ERA5", CONTRATS_ERA5["ghi"]),
)


def code_serie(grandeur: str, source: SourceGhi, localite_code: str) -> str:
    """Code de série dérivée, ex. ``hep_nasa_power_civ_dep_abidjan``."""
    return f"{grandeur}_{source.jeton}_{localite_code}"


def _codes(grandeur: str, source: SourceGhi, localites: list[str]) -> list[str]:
    return [code_serie(grandeur, source, loc) for loc in localites]


def _tous_les_codes() -> list[str]:
    localites = [code for code, _, _, _ in points_nationaux()]
    return [
        code
        for source in SOURCES_GHI
        for grandeur in (GRANDEUR_HEP, GRANDEUR_PST)
        for code in _codes(grandeur, source, localites)
    ]


def _note_hep(source: SourceGhi) -> str:
    note = (
        f"Heures équivalentes pleines (h_eq) depuis le GHI mensuel {source.libelle}, "
        f"mensuelles et annuelles {source.annee_debut}-{source.annee_fin} : HEP mensuel = "
        "GHI (moyenne journalière du mois, kWh/m²/jour) × nombre de jours du mois ; HEP "
        "annuel = somme des 12 mois (années complètes seulement). Convention STC "
        "1 kWh/m² ↔ 1 h_eq à 1 kW/m², plan horizontal : ressource solaire, pas un "
        "productible réel. Formule de la fiche hep, version 1. Confiance B (ADR-0023)."
    )
    return note + (CAVEAT_ERA5 if source.jeton == "era5" else "")


def _note_pst(source: SourceGhi) -> str:
    note = (
        f"Productible spécifique théorique (kWh/kWc sur la période) depuis le GHI mensuel "
        f"{source.libelle}, mensuel et annuel {source.annee_debut}-{source.annee_fin} : HEP "
        f"de la série hep_{source.jeton} × PR théorique fixe 0,8. Plan horizontal, sans "
        "correction thermique : valeur de référence, pas un productible garanti. Formule "
        "de la fiche productible_specifique_theorique, version 1. Confiance B (ADR-0023)."
    )
    return note + (CAVEAT_ERA5 if source.jeton == "era5" else "")


def _verifier_grandeurs(bind: sa.Connection) -> None:
    rows = bind.execute(
        sa.text(
            """
            SELECT g.code, g.actif, g.version_formule_actuelle, g.strategie_calcul,
                   u.code AS unite
            FROM grandeurs_referentiel g JOIN unites u ON u.id = g.unite_id
            WHERE g.code = ANY(:c)
            """
        ),
        {"c": list(UNITES_ATTENDUES)},
    ).all()
    etat = {
        r.code: (r.actif, r.version_formule_actuelle, r.strategie_calcul, r.unite) for r in rows
    }
    attendu = {g: (True, VERSION_FORMULE, "stockee", u) for g, u in UNITES_ATTENDUES.items()}
    if etat != attendu:
        raise RuntimeError(f"Migration 0038 : grandeurs {etat!r}, {attendu!r} attendues.")
    for table in ("series_metadonnees", "grandeurs_metier"):
        n = bind.execute(
            sa.text(f"SELECT COUNT(*) FROM {table} WHERE grandeur_code = ANY(:c)"),
            {"c": list(UNITES_ATTENDUES)},
        ).scalar_one()
        if n:
            raise RuntimeError(f"Migration 0038 : {n} ligne(s) hep/productible déjà dans {table}.")


def _verifier_amont(bind: sa.Connection, source: SourceGhi, localites: list[str]) -> None:
    """Chaque série GHI amont existe, est mensuelle et complète sur la période de la source."""
    rows = bind.execute(
        sa.text(
            """
            SELECT s.code, src.code AS source, s.grandeur_code, s.granularite,
                   COUNT(m.id) AS nb, MIN(m.annee) AS debut, MAX(m.annee) AS fin
            FROM series_metadonnees s
            JOIN sources src ON src.id = s.source_id
            LEFT JOIN mesures_ressource_mensuelles m
                ON m.serie_id = s.id AND m.valide_au IS NULL AND m.statut <> 'deprecie'
            WHERE s.code = ANY(:c)
            GROUP BY s.code, src.code, s.grandeur_code, s.granularite
            """
        ),
        {"c": [source.code_amont(loc) for loc in localites]},
    ).all()
    attendu = (
        source.contrat.source_code,
        "ghi",
        "mensuel",
        12 * source.nb_annees,
        source.annee_debut,
        source.annee_fin,
    )
    fautives = [
        r.code
        for r in rows
        if (r.source, r.grandeur_code, r.granularite, r.nb, r.debut, r.fin) != attendu
    ]
    if len(rows) != len(localites) or fautives:
        raise RuntimeError(
            f"Migration 0038 : GHI {source.libelle} : {len(rows)} séries amont sur "
            f"{len(localites)}, non conformes à {attendu!r} : {fautives[:5]!r}."
        )


def _compter(bind: sa.Connection, codes: list[str]) -> dict[str, int]:
    return {
        str(periode): int(n)
        for periode, n in bind.execute(
            sa.text(
                "SELECT gm.periode_type, COUNT(*) FROM grandeurs_metier gm "
                "JOIN series_metadonnees s ON s.id = gm.series_metadonnees_id "
                "WHERE s.code = ANY(:c) GROUP BY gm.periode_type"
            ),
            {"c": codes},
        ).all()
    }


_INSERT: str = """
    INSERT INTO grandeurs_metier (
        grandeur_code, localite_id, series_metadonnees_id, periode_type,
        annee_debut, annee_fin, mois, version_formule, valeur, niveau_confiance_derive
    )
"""

# GHI mensuel amont de chaque série HEP cible, apparié par code (même localité).
_CTE_GHI: str = """
    WITH ghi AS (
        SELECT sc.id AS serie_cible, sc.localite_id, m.annee, m.mois,
               m.valeur::numeric AS ghi,
               EXTRACT(
                   DAY FROM (make_date(m.annee, m.mois, 1) + INTERVAL '1 month - 1 day')
               )::int AS n_jours
        FROM unnest(CAST(:cibles AS text[]), CAST(:amonts AS text[])) AS p(cible, amont)
        JOIN series_metadonnees sc ON sc.code = p.cible
        JOIN series_metadonnees sa
            ON sa.code = p.amont AND sa.localite_id = sc.localite_id
        JOIN mesures_ressource_mensuelles m
            ON m.serie_id = sa.id AND m.valide_au IS NULL AND m.statut <> 'deprecie'
    )
"""


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE mesures_ressource_mensuelles"))

    points = points_nationaux()
    if len(points) != NB_POINTS:
        raise RuntimeError(f"Migration 0038 : {len(points)} localités, {NB_POINTS} attendues.")
    localites = [code for code, _, _, _ in points]
    _verifier_grandeurs(bind)
    for source in SOURCES_GHI:
        _verifier_amont(bind, source, localites)

    source_calcul_id = bind.execute(
        sa.text("SELECT id FROM sources WHERE code = :c"), {"c": SOURCE_CALCUL}
    ).scalar_one()
    loc = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM localites WHERE code = ANY(:c)"), {"c": localites}
        ).all()
    }
    manquants = [code for code in localites if code not in loc]
    if manquants:
        raise RuntimeError(f"Migration 0038 : localité(s) introuvable(s) : {manquants!r}.")

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
    libelles = {
        GRANDEUR_HEP: "Heures équivalentes pleines",
        GRANDEUR_PST: "Productible spécifique théorique",
    }
    op.bulk_insert(
        series_table,
        [
            {
                "code": code_serie(grandeur, source, code),
                "libelle": (
                    f"{libelles[grandeur]} {source.libelle} — {nom} "
                    f"({source.annee_debut}-{source.annee_fin})"
                ),
                "localite_id": loc[code],
                "grandeur_code": grandeur,
                "source_id": source_calcul_id,
                "periode_debut": f"{source.annee_debut}-01-01",
                "periode_fin": f"{source.annee_fin}-12-31",
                "methode_collecte": "calcul_derive",
                "granularite": None,
                "note_publique": _note_hep(source)
                if grandeur == GRANDEUR_HEP
                else _note_pst(source),
            }
            for source in SOURCES_GHI
            for grandeur in (GRANDEUR_HEP, GRANDEUR_PST)
            for code, nom, _, _ in points
        ],
    )
    nb_series = bind.execute(
        sa.text("SELECT COUNT(*) FROM series_metadonnees WHERE code = ANY(:c)"),
        {"c": _tous_les_codes()},
    ).scalar_one()
    if nb_series != NB_SERIES_ATTENDU:
        raise RuntimeError(f"Migration 0038 : {nb_series} séries, {NB_SERIES_ATTENDU} attendues.")

    total = 0
    for source in SOURCES_GHI:
        codes_hep = _codes(GRANDEUR_HEP, source, localites)
        codes_pst = _codes(GRANDEUR_PST, source, localites)
        params_hep = {
            "g": GRANDEUR_HEP,
            "v": VERSION_FORMULE,
            "cibles": codes_hep,
            "amonts": [source.code_amont(c) for c in localites],
        }
        # 1. HEP mensuel : GHI × jours du mois (produit exact en numeric).
        bind.execute(
            sa.text(
                _CTE_GHI
                + _INSERT
                + """
                SELECT :g, localite_id, serie_cible, 'mensuel', annee, annee, mois, :v,
                       (ghi * n_jours)::float8, 'B'
                FROM ghi
                """
            ),
            params_hep,
        )
        # 2. HEP annuel : somme des 12 mois, années complètes seulement. Somme en
        #    numeric : exacte, donc indépendante de l'ordre d'agrégation.
        bind.execute(
            sa.text(
                _CTE_GHI
                + _INSERT
                + """
                SELECT :g, localite_id, serie_cible, 'annuel', annee, annee, NULL, :v,
                       SUM(ghi * n_jours)::float8, 'B'
                FROM ghi
                GROUP BY localite_id, serie_cible, annee
                HAVING COUNT(*) = 12
                """
            ),
            params_hep,
        )
        # 3. Productible spécifique théorique = HEP gravé × PR théorique, par période.
        bind.execute(
            sa.text(
                _INSERT
                + """
                SELECT :g, sp.localite_id, sp.id, gm.periode_type, gm.annee_debut,
                       gm.annee_fin, gm.mois, :v, (gm.valeur::numeric * :pr)::float8, 'B'
                FROM unnest(CAST(:cibles AS text[]), CAST(:amonts AS text[])) AS p(cible, amont)
                JOIN series_metadonnees sp ON sp.code = p.cible
                JOIN series_metadonnees sh
                    ON sh.code = p.amont AND sh.localite_id = sp.localite_id
                JOIN grandeurs_metier gm
                    ON gm.series_metadonnees_id = sh.id AND gm.grandeur_code = :hep
                   AND gm.version_formule = :v AND gm.valide_au IS NULL
                   AND gm.statut <> 'deprecie'
                """
            ),
            {
                "g": GRANDEUR_PST,
                "hep": GRANDEUR_HEP,
                "v": VERSION_FORMULE,
                "pr": PR_THEORIQUE,
                "cibles": codes_pst,
                "amonts": codes_hep,
            },
        )
        attendu = {
            "mensuel": NB_POINTS * 12 * source.nb_annees,
            "annuel": NB_POINTS * source.nb_annees,
        }
        for grandeur, codes in ((GRANDEUR_HEP, codes_hep), (GRANDEUR_PST, codes_pst)):
            comptes = _compter(bind, codes)
            if comptes != attendu:
                raise RuntimeError(
                    f"Migration 0038 : {grandeur} {source.libelle} : lignes {comptes!r}, "
                    f"{attendu!r} attendues."
                )
            total += sum(comptes.values())
    if total != NB_LIGNES_ATTENDU:
        raise RuntimeError(f"Migration 0038 : {total} lignes, {NB_LIGNES_ATTENDU} attendues.")

    # Domaine physique : 0 < HEP ≤ 12 h_eq par jour de la période (PST = 0,8 × HEP).
    tous = _tous_les_codes()
    hors_domaine = bind.execute(
        sa.text(
            """
            SELECT COUNT(*) FROM (
                SELECT gm.valeur, gm.grandeur_code,
                       CASE WHEN gm.periode_type = 'mensuel'
                            THEN (make_date(gm.annee_debut, gm.mois, 1) + INTERVAL '1 month')::date
                                 - make_date(gm.annee_debut, gm.mois, 1)
                            ELSE make_date(gm.annee_debut + 1, 1, 1) - make_date(gm.annee_debut, 1, 1)
                       END AS n_jours
                FROM grandeurs_metier gm
                JOIN series_metadonnees s ON s.id = gm.series_metadonnees_id
                WHERE s.code = ANY(:c)
            ) t
            WHERE NOT (valeur > 0 AND valeur <= :max * n_jours
                       * CASE WHEN grandeur_code = :pst THEN :pr ELSE 1 END)
            """
        ),
        {"c": tous, "max": HEP_MAX_PAR_JOUR, "pst": GRANDEUR_PST, "pr": PR_THEORIQUE},
    ).scalar_one()
    if hors_domaine:
        raise RuntimeError(f"Migration 0038 : {hors_domaine} valeur(s) hors domaine physique.")
    # Cohérence : Σ des 12 mois = annuel, par (série, année) — sans auto-jointure.
    incoherentes = bind.execute(
        sa.text(
            """
            SELECT COUNT(*) FROM (
                SELECT SUM(gm.valeur) FILTER (WHERE gm.periode_type = 'mensuel') AS somme,
                       MAX(gm.valeur) FILTER (WHERE gm.periode_type = 'annuel') AS annuel
                FROM grandeurs_metier gm
                JOIN series_metadonnees s ON s.id = gm.series_metadonnees_id
                WHERE s.code = ANY(:c)
                GROUP BY gm.series_metadonnees_id, gm.annee_debut
            ) t
            WHERE annuel IS NULL OR abs(somme - annuel) > 1e-9 * annuel
            """
        ),
        {"c": tous},
    ).scalar_one()
    if incoherentes:
        raise RuntimeError(f"Migration 0038 : {incoherentes} année(s) Σ mensuel ≠ annuel.")
    bind.execute(sa.text("ANALYZE grandeurs_metier"))
    bind.execute(sa.text("ANALYZE series_metadonnees"))


def downgrade() -> None:
    bind = op.get_bind()
    codes = _tous_les_codes()
    bind.execute(
        sa.text(
            "DELETE FROM grandeurs_metier WHERE series_metadonnees_id IN "
            "(SELECT id FROM series_metadonnees WHERE code = ANY(:c))"
        ),
        {"c": codes},
    )
    bind.execute(sa.text("DELETE FROM series_metadonnees WHERE code = ANY(:c)"), {"c": codes})
