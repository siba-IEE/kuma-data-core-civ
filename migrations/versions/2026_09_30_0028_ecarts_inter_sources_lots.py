"""ecarts_inter_sources_lots

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-30

Étend les **7 écarts inter-sources** (ADR-0009 à ADR-0013), gravés jusqu'ici aux
3 points pilotes, aux **139 localités des lots nationaux** (31 régions + 108
départements, migrations 0025 et 0027) — ADR-0017.

Contrat **inchangé** : mêmes grandeurs (aucune nouvelle ligne dans
``grandeurs_referentiel``), formule ``(comparée − nasa) / nasa × 100``, NASA
POWER au dénominateur, ``stockee``, fenêtre commune 2005-2020 par jointure SQL,
confiance B. Seules des séries (``kuma_calculs``, ``calcul_derive``) et des
lignes ``grandeurs_metier`` sont ajoutées :

- 7 × 139 = **973 séries** ;
- 7 × 139 × 192 = **186 816 lignes**, soit 26 688 par écart.

Les jointures ne portent que sur les séries **mensuelles** (``granularite =
'mensuel'``) : les séries journalières NASA (0026) partagent localité, source et
grandeur et sont exclues explicitement.

``ANALYZE`` avant le calcul (les lots viennent d'insérer ~1,2 M lignes : sans
statistiques, le planificateur choisit des boucles imbriquées très lentes) et
après, sur ``grandeurs_metier``. Garde-fous : nombre de lignes par écart et
total. ``downgrade`` supprime les lignes puis les séries des lots ; les écarts
pilotes restent intacts.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.lots_civ import ECARTS_INTER_SOURCES, points_lots_mensuels

# revision identifiers, used by Alembic.
revision: str = "0028"
down_revision: str | Sequence[str] | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_CALCUL: str = "kuma_calculs"
PERIODE_DEBUT: str = "2005-01-01"
PERIODE_FIN: str = "2020-12-31"
NB_POINTS: int = 139
NB_LIGNES_PAR_ECART: int = NB_POINTS * 192  # 2005-2020
NB_LIGNES_ATTENDU: int = 186_816  # 7 écarts × 139 localités × 192 mois


def _codes_series() -> list[str]:
    codes = [code for code, _, _, _ in points_lots_mensuels()]
    return [e.code_serie(code) for e in ECARTS_INTER_SOURCES for code in codes]


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("ANALYZE mesures_ressource_mensuelles"))
    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE mesures_ressource"))

    points = points_lots_mensuels()
    if len(points) != NB_POINTS:
        raise RuntimeError(f"Migration 0028 : {len(points)} localités, {NB_POINTS} attendues.")
    source_calcul_id = bind.execute(
        sa.text("SELECT id FROM sources WHERE code = :c"), {"c": SOURCE_CALCUL}
    ).scalar_one()
    loc = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM localites WHERE code = ANY(:c)"),
            {"c": [code for code, _, _, _ in points]},
        ).all()
    }
    manquants = [code for code, _, _, _ in points if code not in loc]
    if manquants:
        raise RuntimeError(f"Migration 0028 : localité(s) introuvable(s) : {manquants!r}.")

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

    total = 0
    for ecart in ECARTS_INTER_SOURCES:
        existe = bind.execute(
            sa.text("SELECT COUNT(*) FROM grandeurs_referentiel WHERE code = :c"),
            {"c": ecart.grandeur_code},
        ).scalar_one()
        if existe != 1:
            raise RuntimeError(f"Migration 0028 : grandeur {ecart.grandeur_code!r} absente.")
        brute = ecart.grandeur_brute.upper()
        op.bulk_insert(
            series_table,
            [
                {
                    "code": ecart.code_serie(code),
                    "libelle": (
                        f"Écart relatif {brute} {ecart.libelle_source} vs NASA POWER — "
                        f"{nom} (2005-2020)"
                    ),
                    "localite_id": loc[code],
                    "grandeur_code": ecart.grandeur_code,
                    "source_id": source_calcul_id,
                    "periode_debut": PERIODE_DEBUT,
                    "periode_fin": PERIODE_FIN,
                    "methode_collecte": "calcul_derive",
                    "granularite": None,
                    "note_publique": (
                        f"Écart relatif mensuel du {brute} entre {ecart.libelle_source} et NASA "
                        "POWER (référence), (comparée − nasa) / nasa × 100 en %, sur les mois "
                        "communs 2005-2020. Positif = source comparée plus haute. Confiance B. "
                        "Lot national (ADR-0017), même contrat que les écarts pilotes."
                    ),
                }
                for code, nom, _, _ in points
            ],
        )
        codes = [ecart.code_serie(code) for code, _, _, _ in points]
        bind.execute(
            sa.text(
                """
                INSERT INTO grandeurs_metier (
                    grandeur_code, localite_id, series_metadonnees_id, periode_type,
                    annee_debut, annee_fin, mois, version_formule, valeur,
                    niveau_confiance_derive
                )
                SELECT :grandeur_code, se.localite_id, se.id, 'mensuel',
                       mc.annee, mc.annee, mc.mois, 1,
                       (mc.valeur - mn.valeur) / mn.valeur * 100.0, 'B'
                FROM series_metadonnees se
                JOIN series_metadonnees sc
                    ON sc.localite_id = se.localite_id AND sc.grandeur_code = :brute
                   AND sc.granularite = 'mensuel'
                JOIN sources xc ON xc.id = sc.source_id AND xc.code = :src_comparee
                JOIN mesures_ressource_mensuelles mc ON mc.serie_id = sc.id
                JOIN series_metadonnees sn
                    ON sn.localite_id = se.localite_id AND sn.grandeur_code = :brute
                   AND sn.granularite = 'mensuel'
                JOIN sources xn ON xn.id = sn.source_id AND xn.code = 'nasa_power'
                JOIN mesures_ressource_mensuelles mn
                    ON mn.serie_id = sn.id AND mn.annee = mc.annee AND mn.mois = mc.mois
                WHERE se.code = ANY(:codes)
                """
            ),
            {
                "grandeur_code": ecart.grandeur_code,
                "brute": ecart.grandeur_brute,
                "src_comparee": ecart.source_comparee,
                "codes": codes,
            },
        )
        nb = bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM grandeurs_metier gm "
                "JOIN series_metadonnees s ON s.id = gm.series_metadonnees_id "
                "WHERE s.code = ANY(:codes)"
            ),
            {"codes": codes},
        ).scalar_one()
        if nb != NB_LIGNES_PAR_ECART:
            raise RuntimeError(
                f"Migration 0028 : {ecart.grandeur_code} : {nb} lignes, "
                f"{NB_LIGNES_PAR_ECART} attendues."
            )
        total += nb

    if total != NB_LIGNES_ATTENDU:
        raise RuntimeError(f"Migration 0028 : {total} lignes, {NB_LIGNES_ATTENDU} attendues.")
    bind.execute(sa.text("ANALYZE grandeurs_metier"))


def downgrade() -> None:
    bind = op.get_bind()
    codes = _codes_series()
    bind.execute(
        sa.text(
            "DELETE FROM grandeurs_metier WHERE series_metadonnees_id IN "
            "(SELECT id FROM series_metadonnees WHERE code = ANY(:c))"
        ),
        {"c": codes},
    )
    bind.execute(sa.text("DELETE FROM series_metadonnees WHERE code = ANY(:c)"), {"c": codes})
