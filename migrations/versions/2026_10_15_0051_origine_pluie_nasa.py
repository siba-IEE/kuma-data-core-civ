"""origine_pluie_nasa

Revision ID: 0051
Revises: 0050
Create Date: 2026-10-15

**Mises en garde de la pluie établies par le recoupement** (ADR-0032).
Métadonnées seulement : aucune valeur n'est corrigée ni retirée.

1. **284 séries de pluie NASA POWER** (142 mensuelles, 142 journalières) : une
   phrase donne l'origine désormais établie des jours extrêmes et de la rupture
   de 2016-2017. Sur l'Afrique, la pluie est recalée par pentade et maille de
   2,5° sur CMAP « temps réel » ; ni ERA5 (0050), ni CHIRPS, ni IMERG ne
   confirment les jours au-delà de 200 mm, et la hausse des fortes pluies est
   propre à NASA.
2. **142 séries mensuelles de pluie NASA** : le chiffre ERA5 cité par 0034
   (« 4,89 mm/jour », relevé hors CDS, archive Open-Meteo) est remplacé par les
   valeurs ERA5 du CDS en base (0036) aux deux points de San-Pédro.
3. **142 séries mensuelles de pluie ERA5** (0036) : dans 13 mois de raccord
   entre expériences de production ERA5, la moyenne mensuelle servie par le CDS
   diffère de la somme des cumuls horaires (0050).

Garde-fous : ensembles de séries exacts, phrases absentes avant, présentes
après. ``downgrade`` rétablit les notes à l'identique.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.seeds.meteo_civ import (
    CONTRATS_METEO_NASA_JOURNALIERS,
    CONTRATS_METEO_NASA_MENSUELS,
)
from kuma_data_core.db.seeds.meteo_era5_civ import CONTRATS_METEO_ERA5_MENSUELS

# revision identifiers, used by Alembic.
revision: str = "0051"
down_revision: str | Sequence[str] | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ORIGINE_PLUIE_NASA: str = (
    " Origine établie (ADR-0032) : sur l'Afrique, cette pluie est celle du modèle "
    "MERRA-2 recalée par pentade (5 jours) et maille de 2,5° sur CMAP « temps réel », "
    "produit que la NOAA qualifie d'expérimental ; elle n'est fiable qu'à cette échelle. "
    "Aucun des 25 jours-localités au-delà de 200 mm (1991-2025) n'est confirmé par ERA5 "
    "(au plus 19 mm à un jour près), ni par CHIRPS (0 mm à San-Pédro, Sassandra, Téhini "
    "et Tabou) ou IMERG. La hausse des jours > 50 mm vers 2016-2017 (×12) est propre à "
    "NASA : ERA5 n'augmente que de ×1,7, progressivement, et CHIRPS comme IMERG sont "
    "sans rupture ; elle coïncide avec un changement documenté du modèle qui répartit "
    "la pluie dans la pentade. À ne pas utiliser pour les extrêmes, les tendances ni "
    "les épisodes de pluie."
)

ERA5_CITE_AVANT: str = "contre 4,89 mm/jour dans ERA5 à San-Pédro"
ERA5_CITE_APRES: str = "contre 3,73 à 5,64 mm/jour dans ERA5 du CDS aux deux points de San-Pédro"

RACCORDS_ERA5: str = (
    " Mise en garde (ADR-0032) : dans 13 mois de raccord entre expériences de "
    "production ERA5 (1993-08, 1995-09, 2000-01, 2000-10, octobres 2001 à 2006, 2008-01, "
    "2010-01, 2019-03), la moyenne mensuelle servie par le CDS diffère de la somme des "
    "cumuls horaires (série journalière ERA5), jusqu'à 0,386 mm/jour (Tengréla, "
    "1995-09) ; valeurs de ces mois à lire avec prudence."
)


def _localites() -> list[str]:
    return [code for code, _, _, _ in points_nationaux()]


def codes_pluie_nasa_mensuelle() -> list[str]:
    contrat = CONTRATS_METEO_NASA_MENSUELS["precipitation"]
    return [contrat.code_serie(loc) for loc in _localites()]


def codes_pluie_nasa() -> list[str]:
    """Les 284 séries de pluie NASA POWER (mensuelles puis journalières)."""
    contrat = CONTRATS_METEO_NASA_JOURNALIERS["precipitation"]
    return codes_pluie_nasa_mensuelle() + [contrat.code_serie(loc) for loc in _localites()]


def codes_pluie_era5_mensuelle() -> list[str]:
    contrat = CONTRATS_METEO_ERA5_MENSUELS["precipitation"]
    return [contrat.code_serie(loc) for loc in _localites()]


def _portant(bind: sa.Connection, fragment: str) -> set[str]:
    return {
        row.code
        for row in bind.execute(
            sa.text("SELECT code FROM series_metadonnees WHERE strpos(note_publique, :f) > 0"),
            {"f": fragment},
        )
    }


def _exiger(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(f"Migration 0051 : {message}")


def upgrade() -> None:
    bind = op.get_bind()
    nasa, nasa_mensuel, era5 = (
        set(codes_pluie_nasa()),
        set(codes_pluie_nasa_mensuelle()),
        set(codes_pluie_era5_mensuelle()),
    )
    _exiger(len(nasa) == 284 and len(era5) == 142, "périmètres inattendus.")
    _exiger(not _portant(bind, ORIGINE_PLUIE_NASA), "origine déjà ajoutée.")
    _exiger(not _portant(bind, RACCORDS_ERA5), "mise en garde ERA5 déjà ajoutée.")
    _exiger(_portant(bind, ERA5_CITE_AVANT) == nasa_mensuel, "citation ERA5 de 0034 introuvable.")

    bind.execute(
        sa.text(
            "UPDATE series_metadonnees SET note_publique = replace(note_publique, :a, :b) "
            "WHERE code = ANY(:c)"
        ),
        {"a": ERA5_CITE_AVANT, "b": ERA5_CITE_APRES, "c": sorted(nasa_mensuel)},
    )
    for phrase, codes in ((ORIGINE_PLUIE_NASA, nasa), (RACCORDS_ERA5, era5)):
        bind.execute(
            sa.text(
                "UPDATE series_metadonnees SET note_publique = note_publique || :p "
                "WHERE code = ANY(:c)"
            ),
            {"p": phrase, "c": sorted(codes)},
        )

    _exiger(_portant(bind, ORIGINE_PLUIE_NASA) == nasa, "origine mal répartie.")
    _exiger(_portant(bind, RACCORDS_ERA5) == era5, "mise en garde ERA5 mal répartie.")
    _exiger(_portant(bind, ERA5_CITE_APRES) == nasa_mensuel, "citation ERA5 mal remplacée.")
    _exiger(not _portant(bind, ERA5_CITE_AVANT), "citation ERA5 de 0034 restante.")


def downgrade() -> None:
    bind = op.get_bind()
    for phrase, codes in (
        (ORIGINE_PLUIE_NASA, codes_pluie_nasa()),
        (RACCORDS_ERA5, codes_pluie_era5_mensuelle()),
    ):
        bind.execute(
            sa.text(
                """
                UPDATE series_metadonnees
                SET note_publique = left(note_publique, length(note_publique) - length(:p))
                WHERE code = ANY(:c) AND right(note_publique, length(:p)) = :p
                """
            ),
            {"p": phrase, "c": codes},
        )
    bind.execute(
        sa.text(
            "UPDATE series_metadonnees SET note_publique = replace(note_publique, :a, :b) "
            "WHERE code = ANY(:c)"
        ),
        {"a": ERA5_CITE_APRES, "b": ERA5_CITE_AVANT, "c": codes_pluie_nasa_mensuelle()},
    )
