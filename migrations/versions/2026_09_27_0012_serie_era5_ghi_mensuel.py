"""serie_era5_ghi_mensuel

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-27

**Troisième source** de GHI mensuel (triangulation inter-source, ADR-0010) :
**ERA5** (réanalyse ECMWF), servie par PVGIS (JRC), aux mêmes 3 points. Première
donnée de **réanalyse** de l'instance CIV.

Grave, dans cet ordre :

1. extension de l'énumération ``methode_collecte`` avec ``'reanalyse'`` — ERA5
   n'est pas satellitaire ; aucune des 6 valeurs ne la décrivait honnêtement
   (cf. ADR-0010). Le modèle SQLAlchemy est mis à jour en miroir ;
2. la source ``era5_pvgis`` (id 16) — ERA5 via PVGIS/JRC, distincte du produit
   CDS ``ecmwf_era5`` : on trace le canal réel, comme ``sarah3_monthly`` ;
3. **3 séries** brutes GHI (``series_metadonnees``) + **576 mesures**
   (``mesures_ressource_mensuelles``), méthode ``reanalyse``, confiance **B**,
   couverture **2005-2020** (fenêtre commune aux trois sources).

Valeur **normalisée** : PVGIS fournit l'irradiation mensuelle totale
(kWh/m²/mois), ramenée en moyenne journalière (÷ jours du mois) pour l'unité
``kwh_par_m2_jour`` de la grandeur ``ghi`` — même convention que SARAH-3 (0010).

Valeurs figées dans le seed ``series_pvgis_era5_ghi_mensuel_civ`` (généré
hors-ligne par ``scripts/ingest_pvgis_era5_mensuel.py``) ; la migration n'accède
jamais au réseau. ``downgrade`` supprime les mesures, les séries, la source,
puis restaure l'énumération à 6 valeurs.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.series_pvgis_era5_ghi_mensuel_civ import (
    GRANDEUR_CODE,
    GRANULARITE,
    METHODE_COLLECTE,
    NIVEAU_CONFIANCE,
    PERIODE_DEBUT,
    PERIODE_FIN,
    SERIES,
    SOURCE_CODE,
)

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_ID: int = 16
_CODES_SERIES: tuple[str, ...] = tuple(s["code"] for s in SERIES)

_CK_METHODE: str = "ck_series_metadonnees_methode_collecte_valide"
_METHODES_6: str = (
    "'mesure_directe', 'modele_satellitaire', 'interpolation_geographique', "
    "'extrapolation_temporelle', 'calcul_derive', 'expertise_humaine'"
)
_METHODES_7: str = _METHODES_6 + ", 'reanalyse'"


def _remplacer_check_methode(valeurs: str) -> None:
    op.drop_constraint(_CK_METHODE, "series_metadonnees", type_="check")
    op.create_check_constraint(
        _CK_METHODE,
        "series_metadonnees",
        f"methode_collecte IS NULL OR methode_collecte IN ({valeurs})",
    )


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Étendre l'énumération methode_collecte : ajout de 'reanalyse'.
    _remplacer_check_methode(_METHODES_7)

    # 2. Source era5_pvgis (id explicite, cf. seed 0002 : sources à id figé).
    op.bulk_insert(
        sa.table(
            "sources",
            sa.column("id", sa.BigInteger),
            sa.column("code", sa.String),
            sa.column("titre", sa.Text),
            sa.column("organisation", sa.Text),
            sa.column("type_source", sa.String),
            sa.column("url", sa.Text),
            sa.column("fiabilite", sa.String),
            sa.column("langue", sa.String),
            sa.column("notes", sa.Text),
        ),
        [
            {
                "id": SOURCE_ID,
                "code": SOURCE_CODE,
                "titre": (
                    "ERA5 (réanalyse ECMWF) — irradiation horizontale mensuelle servie "
                    "par PVGIS (JRC), API v5_3 MRcalc, raddatabase=PVGIS-ERA5"
                ),
                "organisation": (
                    "European Centre for Medium-Range Weather Forecasts (ECMWF) / "
                    "Copernicus Climate Change Service (C3S) ; portage PVGIS par le "
                    "Joint Research Centre (JRC) de la Commission européenne."
                ),
                "type_source": "base_donnees",
                "url": "https://re.jrc.ec.europa.eu/api/v5_3/MRcalc",
                "fiabilite": "haute",
                "langue": "en",
                "notes": (
                    "3ᵉ source GHI pour la triangulation inter-source (ADR-0010). "
                    "Réanalyse atmosphérique ERA5 (Hersbach et al. 2020), classe de "
                    "méthode distincte des sources satellitaires NASA POWER (CERES) et "
                    "SARAH-3 (Meteosat/Heliosat). Servie par PVGIS/JRC (MRcalc, "
                    "raddatabase=PVGIS-ERA5), distincte du produit CDS ecmwf_era5 id 2. "
                    "CAVEAT : le GHI de réanalyse est de moindre qualité que le "
                    "satellite en Afrique de l'Ouest (biais sous ciel nuageux/aérosols, "
                    "Sawadogo et al. 2023 ; Yang & Bright 2020). Utilisée comme source "
                    "de COMPARAISON pour l'écart inter-source, jamais comme référentiel "
                    "ni comme vérité — le dénominateur des écarts reste NASA POWER."
                ),
            }
        ],
    )

    # 3. Séries brutes + mesures (identique au schéma NASA/SARAH-3, migration 0010).
    codes_loc = sorted({s["localite_code"] for s in SERIES})
    loc = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM localites WHERE code = ANY(:c)"), {"c": codes_loc}
        ).all()
    }
    manquants = [c for c in codes_loc if c not in loc]
    if manquants:
        raise RuntimeError(f"Migration 0012 : localité(s) introuvable(s) : {manquants!r}.")

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
    op.bulk_insert(
        series_table,
        [
            {
                "code": s["code"],
                "libelle": s["libelle"],
                "localite_id": loc[s["localite_code"]],
                "grandeur_code": GRANDEUR_CODE,
                "source_id": SOURCE_ID,
                "periode_debut": PERIODE_DEBUT,
                "periode_fin": PERIODE_FIN,
                "methode_collecte": METHODE_COLLECTE,
                "granularite": GRANULARITE,
                "note_publique": (
                    "GHI mensuel ERA5 (réanalyse ECMWF, via PVGIS), moyenne journalière "
                    "du mois (kWh/m²/jour, normalisée depuis l'irradiation mensuelle "
                    "totale), 2005-2020. Confiance B (réanalyse). Source de comparaison "
                    "inter-source, moindre qualité que le satellite en Afrique de "
                    "l'Ouest (Sawadogo 2023) — jamais une vérité sol."
                ),
            }
            for s in SERIES
        ],
    )

    serie_id = {
        row.code: row.id
        for row in bind.execute(
            sa.text("SELECT code, id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": list(_CODES_SERIES)},
        ).all()
    }

    mesures_table = sa.table(
        "mesures_ressource_mensuelles",
        sa.column("serie_id", sa.BigInteger),
        sa.column("annee", sa.SmallInteger),
        sa.column("mois", sa.SmallInteger),
        sa.column("valeur", sa.Float),
        sa.column("statut", sa.String),
        sa.column("niveau_confiance_derive", sa.String),
    )
    payload: list[dict[str, Any]] = []
    for s in SERIES:
        sid = serie_id[s["code"]]
        for annee, mois, valeur in s["mesures"]:
            payload.append(
                {
                    "serie_id": sid,
                    "annee": annee,
                    "mois": mois,
                    "valeur": valeur,
                    "statut": "brut",
                    "niveau_confiance_derive": NIVEAU_CONFIANCE,
                }
            )
    op.bulk_insert(mesures_table, payload)


def downgrade() -> None:
    bind = op.get_bind()
    ids = [
        row.id
        for row in bind.execute(
            sa.text("SELECT id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": list(_CODES_SERIES)},
        ).all()
    ]
    if ids:
        bind.execute(
            sa.text("DELETE FROM mesures_ressource_mensuelles WHERE serie_id = ANY(:ids)"),
            {"ids": ids},
        )
        bind.execute(sa.text("DELETE FROM series_metadonnees WHERE id = ANY(:ids)"), {"ids": ids})
    bind.execute(sa.text("DELETE FROM sources WHERE code = :c"), {"c": SOURCE_CODE})
    # Restaurer l'énumération à 6 valeurs (après suppression des lignes 'reanalyse').
    _remplacer_check_methode(_METHODES_6)
