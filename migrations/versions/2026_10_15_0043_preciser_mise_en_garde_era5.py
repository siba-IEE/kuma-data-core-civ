"""preciser_mise_en_garde_era5

Revision ID: 0043
Revises: 0042
Create Date: 2026-10-15

**Précision de la mise en garde ERA5** (ADR-0018, ADR-0021). La phrase gravée par
0033, puis reprise par 0038 et 0041 pour les séries dérivées, attribuait le saut
de 2021 au « produit PVGIS-ERA5 ». Le diagnostic de l'ADR-0021 l'attribue à la
réanalyse ERA5 elle-même : le rayonnement global ERA5 servi directement par
Copernicus (CDS, ``surface_solar_radiation_downwards``) saute de +3,6 % entre
2016-2020 et 2021-2023 aux mêmes 142 localités, et le rapport PVGIS / CDS reste
entre 0,996 et 0,999 chaque année de 2005 à 2023.

Remplace la phrase dans la note publique des **994 séries** qui la portent :

- 284 séries ERA5 brutes (GHI et DNI, PVGIS) et 284 écarts ERA5 − NASA (0033) ;
- 284 séries HEP et productible spécifique théorique ERA5 (0038) ;
- 142 séries d'indice de clarté ERA5 (0041).

Les séries météo ERA5 du CDS (0036) ne la portent pas : aucun saut analogue sur
la température, le vent ou la pluie (ADR-0021).

**Métadonnées seulement**, aucune valeur modifiée. Garde-fous : l'ensemble des
séries portant l'ancienne phrase est exactement l'ensemble attendu, aucune ne
porte déjà la nouvelle. ``downgrade`` rétablit l'ancienne phrase.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.lots_civ import CONTRATS_ERA5, ECARTS_INTER_SOURCES, points_nationaux

# revision identifiers, used by Alembic.
revision: str = "0043"
down_revision: str | Sequence[str] | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NB_SERIES_ATTENDU: int = 994  # (2 brutes + 2 écarts + HEP + productible + kt) × 142

ANCIENNE: str = (
    " Mise en garde : saut probable du produit PVGIS-ERA5 en 2021 (moyenne nationale "
    "GHI +3,6 %, DNI +7,7 % par rapport à 2016-2020, environ trois fois la variabilité "
    "interannuelle), absent des autres sources ; valeurs 2021-2023 à interpréter avec "
    "prudence (ADR-0018)."
)

NOUVELLE: str = (
    " Mise en garde : saut probable de la réanalyse ERA5 en 2021 (moyenne nationale "
    "servie par PVGIS : GHI +3,6 %, DNI +7,7 % par rapport à 2016-2020, environ trois "
    "fois la variabilité interannuelle), absent des autres sources ; le rayonnement "
    "global ERA5 servi directement par Copernicus (CDS) montre le même saut (+3,6 %), "
    "qui vient donc d'ERA5 et non du traitement PVGIS ; valeurs 2021-2023 à interpréter "
    "avec prudence (ADR-0018, ADR-0021)."
)


def codes_attendus() -> set[str]:
    """Séries ERA5 brutes, écarts ERA5 − NASA et séries dérivées du GHI ERA5."""
    localites = [code for code, _, _, _ in points_nationaux()]
    brutes = {c.code_serie(loc) for c in CONTRATS_ERA5.values() for loc in localites}
    ecarts = {
        e.code_serie(loc)
        for e in ECARTS_INTER_SOURCES
        if e.source_comparee == "era5_pvgis"
        for loc in localites
    }
    derivees = {
        f"{prefixe}_era5_{loc}"
        for prefixe in ("hep", "productible_specifique_theorique", "kt")
        for loc in localites
    }
    return brutes | ecarts | derivees


def _codes_portant(bind: sa.Connection, phrase: str) -> set[str]:
    return {
        row.code
        for row in bind.execute(
            sa.text("SELECT code FROM series_metadonnees WHERE strpos(note_publique, :p) > 0"),
            {"p": phrase},
        )
    }


def _remplacer(bind: sa.Connection, avant: str, apres: str) -> None:
    attendus = codes_attendus()
    if len(attendus) != NB_SERIES_ATTENDU:
        raise RuntimeError(f"Migration 0043 : {len(attendus)} codes, {NB_SERIES_ATTENDU} attendus.")
    portant = _codes_portant(bind, avant)
    if portant != attendus:
        raise RuntimeError(
            f"Migration 0043 : {len(portant)} séries portent la phrase à remplacer, "
            f"{len(portant - attendus)} inattendues, {len(attendus - portant)} manquantes."
        )
    if _codes_portant(bind, apres):
        raise RuntimeError("Migration 0043 : la phrase cible est déjà présente.")
    n = bind.execute(
        sa.text(
            """
            UPDATE series_metadonnees SET note_publique = replace(note_publique, :avant, :apres)
            WHERE code = ANY(:c) AND strpos(note_publique, :avant) > 0
            """
        ),
        {"avant": avant, "apres": apres, "c": sorted(attendus)},
    ).rowcount
    if n != NB_SERIES_ATTENDU or _codes_portant(bind, apres) != attendus:
        raise RuntimeError(f"Migration 0043 : {n} séries mises à jour, {NB_SERIES_ATTENDU}.")


def upgrade() -> None:
    _remplacer(op.get_bind(), ANCIENNE, NOUVELLE)


def downgrade() -> None:
    _remplacer(op.get_bind(), NOUVELLE, ANCIENNE)
