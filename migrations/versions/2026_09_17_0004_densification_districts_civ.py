"""densification_districts_civ

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-17

Densification sourcée des 14 districts de Côte d'Ivoire (passe 2).

La migration 0003 a posé les 14 districts « localités seules » (coordonnées,
population et chef-lieu différés à ``NULL``). Cette migration renseigne, par
``UPDATE`` ciblé sur le ``code`` métier :

- ``latitude`` / ``longitude`` : point représentatif Wikidata (``P625``) de
  l'entité *district* (QID cité dans ``notes``) ;
- ``population_estimee`` / ``annee_population`` (= 2021) : total district du
  RGPH 2021 (INS Côte d'Ivoire), agrégat des comptages régionaux officiels ;
- ``notes`` : chef-lieu, source RGPH, QID Wikidata.

Les valeurs proviennent de ``LOCALITES_SEED`` (même source que le seed 0003 lit
pour les installations neuves) : sur une base neuve l'``UPDATE`` est idempotent
(0003 a déjà inséré ces valeurs) ; sur une base ayant appliqué 0003 avant la
densification, il applique le delta. ``altitude_metres`` reste ``NULL`` (une
région n'a pas d'altitude ponctuelle univoque).

Le trigger d'audit ``BEFORE UPDATE`` sur ``localites`` s'applique normalement ;
``modifie_par`` reste ``NULL`` (pas de ``set_config`` applicatif).

``downgrade`` restaure l'état antérieur exact : coordonnées, population et
année à ``NULL``, et la note « densification différée » d'origine.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.localites_civ_seed_data import LOCALITES_SEED

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Districts densifiés dans cette passe (extraits du seed, source unique de vérité).
_DISTRICTS: tuple[dict[str, Any], ...] = tuple(
    e for e in LOCALITES_SEED if e["type_localite"] == "region_administrative"
)

# --- Éléments nécessaires au downgrade (état d'origine, avant densification) ---
# Note « densification différée » d'origine (migration 0003), réempruntée telle
# quelle pour restaurer l'état exact des 14 districts.
_NOTE_DISTRICT_DENSIFICATION_ORIGINE: str = (
    "Coordonnées, population et chef-lieu à densifier en passe sourcée "
    "(accès réseau requis : Wikidata, HDX/COD-AB, INS Côte d'Ivoire). "
    "Libellé et code issus de la norme ISO 3166-2:CI."
)
# code métier -> (sous-code ISO 3166-2:CI, district autonome ?)
_DISTRICTS_ORIGINE: dict[str, tuple[str, bool]] = {
    "civ_abidjan": ("CI-AB", True),
    "civ_bas_sassandra": ("CI-BS", False),
    "civ_comoe": ("CI-CM", False),
    "civ_denguele": ("CI-DN", False),
    "civ_goh_djiboua": ("CI-GD", False),
    "civ_lacs": ("CI-LC", False),
    "civ_lagunes": ("CI-LG", False),
    "civ_montagnes": ("CI-MG", False),
    "civ_sassandra_marahoue": ("CI-SM", False),
    "civ_savanes": ("CI-SV", False),
    "civ_vallee_du_bandama": ("CI-VB", False),
    "civ_woroba": ("CI-WR", False),
    "civ_yamoussoukro": ("CI-YM", True),
    "civ_zanzan": ("CI-ZZ", False),
}


def upgrade() -> None:
    bind = op.get_bind()
    stmt = sa.text(
        """
        UPDATE localites
        SET latitude = :latitude,
            longitude = :longitude,
            population_estimee = :population_estimee,
            annee_population = :annee_population,
            notes = :notes
        WHERE code = :code
        """
    )
    for entry in _DISTRICTS:
        result = bind.execute(
            stmt,
            {
                "latitude": entry["latitude"],
                "longitude": entry["longitude"],
                "population_estimee": entry["population_estimee"],
                "annee_population": entry["annee_population"],
                "notes": entry["notes"],
                "code": entry["code"],
            },
        )
        if result.rowcount != 1:
            raise RuntimeError(
                f"Migration 0004 : district introuvable lors de la densification : "
                f"{entry['code']!r} (rowcount={result.rowcount}). La migration 0003 "
                f"doit avoir posé les 14 districts au préalable."
            )


def downgrade() -> None:
    bind = op.get_bind()
    stmt = sa.text(
        """
        UPDATE localites
        SET latitude = NULL,
            longitude = NULL,
            population_estimee = NULL,
            annee_population = NULL,
            notes = :notes
        WHERE code = :code
        """
    )
    for code, (iso_3166_2, autonome) in _DISTRICTS_ORIGINE.items():
        qualif = "District autonome" if autonome else "District"
        note = (
            f"{qualif} de Côte d'Ivoire (ISO 3166-2 : {iso_3166_2}). "
            f"{_NOTE_DISTRICT_DENSIFICATION_ORIGINE}"
        )
        bind.execute(stmt, {"notes": note, "code": code})
