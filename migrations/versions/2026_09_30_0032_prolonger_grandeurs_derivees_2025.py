"""prolonger_grandeurs_derivees_2025

Revision ID: 0032
Revises: 0031
Create Date: 2026-09-30

**Extension temporelle des grandeurs dérivées** (ADR-0018), aux 142 localités,
sur les nouvelles années des séries brutes (0030) :

- **7 écarts inter-sources** : formule, référence NASA et contrat inchangés ;
  la fenêtre commune s'étend jusqu'à la dernière année commune avec NASA —
  **2023** pour SARAH-3 et ERA5, **2025** pour CAMS. 4 × 142 × 36 + 3 × 142 × 60
  = **46 008 lignes** ;
- **fraction diffuse NASA** : 2021-2025, **8 520 lignes mensuelles** et **710
  annuelles** (sommes annuelles en ``numeric``, garde-fou ``[0, 1]``).

Mêmes séries (mêmes codes) : ``periode_fin`` prolongée, libellé « (AAAA-2020) »
→ « (AAAA-fin) », phrase ajoutée à la note publique. Calcul en SQL hors-ligne,
restreint aux années > 2020 et aux séries **mensuelles**. Garde-fous : séries
existantes finissant en 2020, aucune ligne après 2020, comptes. ``ANALYZE`` en
fin de migration. ``downgrade`` supprime les lignes postérieures à 2020 et
restaure les métadonnées.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.lots_civ import ECARTS_INTER_SOURCES, FIN_EXTENSION, points_nationaux

# revision identifiers, used by Alembic.
revision: str = "0032"
down_revision: str | Sequence[str] | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NB_POINTS: int = 142
NB_ECARTS_ATTENDU: int = 46_008
NB_FD_MENSUEL: int = 8_520  # 142 × 60
NB_FD_ANNUEL: int = 710  # 142 × 5
FIN_FD: int = 2025
FIN_ACTUELLE: str = "2020-12-31"


def _phrase(fin: int) -> str:
    return f" Prolongée jusqu'en {fin} (ADR-0018)."


def _codes_fd() -> list[str]:
    return [f"fraction_diffuse_nasa_power_{code}" for code, _, _, _ in points_nationaux()]


def _prolonger_metadonnees(bind: sa.Connection, codes: list[str], fin: int) -> None:
    n = bind.execute(
        sa.text(
            """
            UPDATE series_metadonnees
            SET periode_fin = :fin,
                libelle = regexp_replace(libelle, '-2020\\)$', :suffixe),
                note_publique = note_publique || :phrase
            WHERE code = ANY(:c) AND periode_fin = :fin_actuelle
            """
        ),
        {
            "fin": f"{fin}-12-31",
            "suffixe": f"-{fin})",
            "phrase": _phrase(fin),
            "c": codes,
            "fin_actuelle": FIN_ACTUELLE,
        },
    ).rowcount
    if n != len(codes):
        raise RuntimeError(f"Migration 0032 : {n} séries prolongées, {len(codes)} attendues.")


def _compter(bind: sa.Connection, codes: list[str]) -> int:
    return int(
        bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM grandeurs_metier gm "
                "JOIN series_metadonnees s ON s.id = gm.series_metadonnees_id "
                "WHERE s.code = ANY(:c) AND gm.annee_debut > 2020"
            ),
            {"c": codes},
        ).scalar_one()
    )


def upgrade() -> None:
    bind = op.get_bind()
    localites = [code for code, _, _, _ in points_nationaux()]
    if len(localites) != NB_POINTS:
        raise RuntimeError(f"Migration 0032 : {len(localites)} localités, {NB_POINTS} attendues.")

    # 1. Écarts inter-sources.
    total = 0
    for ecart in ECARTS_INTER_SOURCES:
        codes = [ecart.code_serie(code) for code in localites]
        if _compter(bind, codes):
            raise RuntimeError(f"Migration 0032 : {ecart.grandeur_code} déjà prolongé.")
        fin = min(FIN_EXTENSION[ecart.source_comparee], FIN_EXTENSION["nasa_power"])
        _prolonger_metadonnees(bind, codes, fin)
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
                JOIN mesures_ressource_mensuelles mc
                    ON mc.serie_id = sc.id AND mc.annee > 2020
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
        nb = _compter(bind, codes)
        attendu = NB_POINTS * (fin - 2020) * 12
        if nb != attendu:
            raise RuntimeError(
                f"Migration 0032 : {ecart.grandeur_code} : {nb} lignes, {attendu} attendues."
            )
        total += nb
    if total != NB_ECARTS_ATTENDU:
        raise RuntimeError(f"Migration 0032 : {total} lignes d'écart, {NB_ECARTS_ATTENDU}.")

    # 2. Fraction diffuse NASA 2021-2025.
    codes_fd = _codes_fd()
    if _compter(bind, codes_fd):
        raise RuntimeError("Migration 0032 : fraction diffuse déjà prolongée.")
    _prolonger_metadonnees(bind, codes_fd, FIN_FD)
    cte = """
        WITH couples AS (
            SELECT sf.id AS serie_cible, sf.localite_id, md.annee, md.mois,
                   md.valeur AS dhi, mg.valeur AS ghi,
                   EXTRACT(
                       DAY FROM (make_date(md.annee, md.mois, 1) + INTERVAL '1 month - 1 day')
                   )::int AS n_jours
            FROM series_metadonnees sf
            JOIN series_metadonnees sd
                ON sd.localite_id = sf.localite_id AND sd.grandeur_code = 'dhi'
               AND sd.granularite = 'mensuel'
            JOIN sources xd ON xd.id = sd.source_id AND xd.code = 'nasa_power'
            JOIN mesures_ressource_mensuelles md ON md.serie_id = sd.id AND md.annee > 2020
            JOIN series_metadonnees sg
                ON sg.localite_id = sf.localite_id AND sg.grandeur_code = 'ghi'
               AND sg.granularite = 'mensuel'
            JOIN sources xg ON xg.id = sg.source_id AND xg.code = 'nasa_power'
            JOIN mesures_ressource_mensuelles mg
                ON mg.serie_id = sg.id AND mg.annee = md.annee AND mg.mois = md.mois
            WHERE sf.code = ANY(:codes)
        )
    """
    params = {"codes": codes_fd}
    bind.execute(
        sa.text(
            cte
            + """
            INSERT INTO grandeurs_metier (
                grandeur_code, localite_id, series_metadonnees_id, periode_type,
                annee_debut, annee_fin, mois, version_formule, valeur,
                niveau_confiance_derive
            )
            SELECT 'fraction_diffuse', localite_id, serie_cible, 'mensuel',
                   annee, annee, mois, 1, dhi / ghi, 'B'
            FROM couples WHERE ghi > 0
            """
        ),
        params,
    )
    bind.execute(
        sa.text(
            cte
            + """
            INSERT INTO grandeurs_metier (
                grandeur_code, localite_id, series_metadonnees_id, periode_type,
                annee_debut, annee_fin, mois, version_formule, valeur,
                niveau_confiance_derive
            )
            SELECT 'fraction_diffuse', localite_id, serie_cible, 'annuel',
                   annee, annee, NULL, 1,
                   -- Sommes en numeric : exactes, donc indépendantes de l'ordre.
                   (SUM(dhi::numeric * n_jours) / SUM(ghi::numeric * n_jours))::float8, 'B'
            FROM couples
            GROUP BY localite_id, serie_cible, annee
            HAVING COUNT(*) = 12 AND SUM(ghi * n_jours) > 0
            """
        ),
        params,
    )
    comptes = dict(
        bind.execute(
            sa.text(
                "SELECT gm.periode_type, COUNT(*) FROM grandeurs_metier gm "
                "JOIN series_metadonnees s ON s.id = gm.series_metadonnees_id "
                "WHERE s.code = ANY(:codes) AND gm.annee_debut > 2020 GROUP BY 1"
            ),
            params,
        ).all()
    )
    if comptes != {"mensuel": NB_FD_MENSUEL, "annuel": NB_FD_ANNUEL}:
        raise RuntimeError(f"Migration 0032 : fraction diffuse {comptes!r}.")
    hors = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM grandeurs_metier WHERE grandeur_code = 'fraction_diffuse' "
            "AND (valeur < 0 OR valeur > 1)"
        )
    ).scalar_one()
    if hors:
        raise RuntimeError(f"Migration 0032 : {hors} fraction(s) diffuse(s) hors de [0, 1].")
    bind.execute(sa.text("ANALYZE grandeurs_metier"))


def downgrade() -> None:
    bind = op.get_bind()
    localites = [code for code, _, _, _ in points_nationaux()]
    groupes = [
        (
            [e.code_serie(code) for code in localites],
            min(FIN_EXTENSION[e.source_comparee], FIN_EXTENSION["nasa_power"]),
        )
        for e in ECARTS_INTER_SOURCES
    ] + [(_codes_fd(), FIN_FD)]
    for codes, fin in groupes:
        bind.execute(
            sa.text(
                "DELETE FROM grandeurs_metier WHERE annee_debut > 2020 AND series_metadonnees_id "
                "IN (SELECT id FROM series_metadonnees WHERE code = ANY(:c))"
            ),
            {"c": codes},
        )
        bind.execute(
            sa.text(
                """
                UPDATE series_metadonnees
                SET periode_fin = :fin_actuelle,
                    libelle = regexp_replace(libelle, :motif, '-2020)'),
                    note_publique = left(note_publique, length(note_publique) - length(:phrase))
                WHERE code = ANY(:c) AND right(note_publique, length(:phrase)) = :phrase
                """
            ),
            {
                "fin_actuelle": FIN_ACTUELLE,
                "motif": re.escape(f"-{fin})") + "$",
                "phrase": _phrase(fin),
                "c": codes,
            },
        )
