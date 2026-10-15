"""grandeur_kt_indice_clarte

Revision ID: 0041
Revises: 0040
Create Date: 2026-10-15

Matérialise l'**indice de clarté** ``kt`` (id 2, seedé en 0002, F1 ``stockee``,
sans dimension) aux **142 localités** (3 pilotes + 31 régions + 108
départements), pour les **4 sources de GHI** mensuel — ADR-0026, fiche
``docs/methodologie/grandeurs/kt.md`` (version de formule 1) :

    kt(annee, mois) := Σ GHI(t) / Σ H0(t) = GHI_moyen / H0_moyen
    kt(annee)       := Σ_m GHI_m·n_m / Σ_m H0_m·n_m   (12 mois requis)

``H0`` (irradiation extraterrestre horizontale) est calculé **en Python, dans
la migration**, par les fonctions pures ``services/grandeurs/kt.py`` : Duffie &
Beckman éq. 1.10.3, déclinaison et excentricité de Spencer (1971), constante
solaire 1361 W/m² (Kopp & Lean 2011), moyenne des ``H0`` de tous les jours
civils du mois, à la **latitude de la localité lue en base**. Ces paramètres
sont figés ici (pas de valeur par défaut implicite) : le calcul est
déterministe et sans réseau.

Grave 568 séries ``calcul_derive`` (``kuma_calculs``), confiance B :

| Source | Séries | Période | Mensuel | Annuel |
|---|---|---|---:|---:|
| NASA POWER | ``kt_nasa_power_<loc>`` | 1991-2025 | 59 640 | 4 970 |
| CAMS Radiation | ``kt_cams_<loc>`` | 2005-2025 | 35 784 | 2 982 |
| SARAH-3 (PVGIS) | ``kt_sarah3_<loc>`` | 2005-2023 | 32 376 | 2 698 |
| ERA5 (PVGIS) | ``kt_era5_<loc>`` | 2005-2023 | 32 376 | 2 698 |
| **Total** | 568 | | **160 176** | **13 348** |

Les séries dérivées d'ERA5 portent la mise en garde du saut de 2021 (même
phrase que la migration 0033). Insertion des valeurs par ``COPY``.

Garde-fous : grandeur au contrat ; aucune série ni ligne ``kt`` préexistante ;
142 localités avec latitude ; 142 séries GHI **mensuelles** par source, à la
période attendue et complètes (comptes exacts de mesures, GHI > 0) ; comptes
exacts de lignes par série et au total ; domaine ``0 < kt < 1``. ``ANALYZE``
en fin de migration. ``downgrade`` supprime les lignes puis les séries ``kt``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

import sqlalchemy as sa
from alembic import op

from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.services.grandeurs.kt import ModeleSolaire, calculer_kt

# revision identifiers, used by Alembic.
revision: str = "0041"
down_revision: str | Sequence[str] | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANDEUR_CODE: str = "kt"
GRANDEUR_ID: int = 2
SOURCE_CALCUL: str = "kuma_calculs"
VERSION_FORMULE: int = 1
NB_POINTS: int = 142

# Paramètres de H0 figés pour cette migration (fiche kt.md, version 1).
CONSTANTE_SOLAIRE: float = 1361.0  # W/m², Kopp & Lean 2011
MODELE_SOLAIRE: ModeleSolaire = "spencer"  # déclinaison et excentricité de Spencer (1971)

# Phrase de la migration 0033, reprise à l'identique sur les séries dérivées d'ERA5.
CAVEAT_ERA5: str = (
    " Mise en garde : saut probable du produit PVGIS-ERA5 en 2021 (moyenne nationale "
    "GHI +3,6 %, DNI +7,7 % par rapport à 2016-2020, environ trois fois la variabilité "
    "interannuelle), absent des autres sources ; valeurs 2021-2023 à interpréter avec "
    "prudence (ADR-0018)."
)


class SourceKt(NamedTuple):
    """Une source de GHI mensuel et la période de ses séries (ADR-0018).

    ``NamedTuple`` plutôt que ``dataclass`` : Alembic charge ce fichier hors de
    ``sys.modules``, ce que ``dataclasses`` ne supporte pas.
    """

    source_code: str  # source amont du GHI
    jeton: str  # dans le code de série : kt_<jeton>_<localité>
    libelle: str
    annee_debut: int
    annee_fin: int

    def code_serie(self, localite_code: str) -> str:
        return f"kt_{self.jeton}_{localite_code}"

    @property
    def nb_annees(self) -> int:
        return self.annee_fin - self.annee_debut + 1


SOURCES_KT: tuple[SourceKt, ...] = (
    SourceKt("nasa_power", "nasa_power", "NASA POWER", 1991, 2025),
    SourceKt("cams_radiation", "cams", "CAMS Radiation", 2005, 2025),
    SourceKt("sarah3_monthly", "sarah3", "SARAH-3 (PVGIS)", 2005, 2023),
    SourceKt("era5_pvgis", "era5", "ERA5 (PVGIS)", 2005, 2023),
)
NB_SERIES_ATTENDU: int = 568  # 4 sources × 142 localités
NB_MENSUEL_ATTENDU: int = 160_176  # 142 × 12 × (35 + 21 + 19 + 19)
NB_ANNUEL_ATTENDU: int = 13_348  # 142 × (35 + 21 + 19 + 19)


def _note(source: SourceKt) -> str:
    note = (
        f"Indice de clarté kt = H / H0, sans dimension : GHI mensuel {source.libelle} "
        "rapporté à l'irradiation extraterrestre sur plan horizontal H0, Σ GHI / Σ H0 sur "
        "les jours de la période, mensuel et annuel "
        f"{source.annee_debut}-{source.annee_fin}. H0 calculé à la latitude de la localité "
        "(Duffie & Beckman éq. 1.10.3, déclinaison et excentricité de Spencer 1971, "
        "constante solaire 1361 W/m²), moyenne des jours civils du mois. Confiance B "
        "(hérite de l'entrée GHI). ADR-0026."
    )
    return note + CAVEAT_ERA5 if source.source_code == "era5_pvgis" else note


def _codes_kt() -> list[str]:
    return [s.code_serie(code) for s in SOURCES_KT for code, _, _, _ in points_nationaux()]


def upgrade() -> None:
    bind = op.get_bind()

    # 0. La grandeur seedée en 0002 est celle attendue ; rien n'est déjà gravé.
    row = bind.execute(
        sa.text(
            "SELECT g.id, g.famille, g.strategie_calcul, u.code AS unite "
            "FROM grandeurs_referentiel g JOIN unites u ON u.id = g.unite_id WHERE g.code = :c"
        ),
        {"c": GRANDEUR_CODE},
    ).one_or_none()
    if row is None or (row.id, row.famille, row.strategie_calcul, row.unite) != (
        GRANDEUR_ID,
        "F1",
        "stockee",
        "sans_unite",
    ):
        raise RuntimeError(f"Migration 0041 : grandeur {GRANDEUR_CODE!r} hors contrat : {row!r}.")
    deja = bind.execute(
        sa.text(
            "SELECT (SELECT COUNT(*) FROM series_metadonnees WHERE grandeur_code = :g "
            "OR code = ANY(:c)) + (SELECT COUNT(*) FROM grandeurs_metier WHERE grandeur_code = :g)"
        ),
        {"g": GRANDEUR_CODE, "c": _codes_kt()},
    ).scalar_one()
    if deja:
        raise RuntimeError(f"Migration 0041 : {deja} série(s) ou ligne(s) kt préexistante(s).")

    # 1. Localités et latitudes, lues en base.
    points = points_nationaux()
    if len(points) != NB_POINTS:
        raise RuntimeError(f"Migration 0041 : {len(points)} localités, {NB_POINTS} attendues.")
    noms = {code: nom for code, nom, _, _ in points}
    localites = {
        r.code: r
        for r in bind.execute(
            sa.text("SELECT code, id, latitude FROM localites WHERE code = ANY(:c)"),
            {"c": list(noms)},
        ).all()
    }
    sans_lat = sorted(c for c in noms if c not in localites or localites[c].latitude is None)
    if sans_lat:
        raise RuntimeError(
            f"Migration 0041 : localité(s) absente(s) ou sans latitude {sans_lat!r}."
        )
    par_id = {r.id: r for r in localites.values()}

    # 2. GHI mensuel brut de chaque source : 142 séries complètes, à la période attendue.
    ghi: dict[tuple[str, str], dict[tuple[int, int], float]] = {}
    for source in SOURCES_KT:
        series = bind.execute(
            sa.text(
                """
                SELECT s.id, s.localite_id, s.periode_debut, s.periode_fin
                FROM series_metadonnees s JOIN sources x ON x.id = s.source_id
                WHERE x.code = :src AND s.grandeur_code = 'ghi' AND s.granularite = 'mensuel'
                  AND s.localite_id = ANY(:loc)
                """
            ),
            {"src": source.source_code, "loc": list(par_id)},
        ).all()
        periodes = {(str(s.periode_debut), str(s.periode_fin)) for s in series}
        attendue = (f"{source.annee_debut}-01-01", f"{source.annee_fin}-12-31")
        if len(series) != NB_POINTS or periodes != {attendue}:
            raise RuntimeError(
                f"Migration 0041 : GHI {source.source_code} : {len(series)} séries, "
                f"périodes {periodes!r} ; {NB_POINTS} séries {attendue!r} attendues."
            )
        mesures = bind.execute(
            sa.text(
                "SELECT serie_id, annee, mois, valeur FROM mesures_ressource_mensuelles "
                "WHERE serie_id = ANY(:ids)"
            ),
            {"ids": [s.id for s in series]},
        ).all()
        loc_de = {s.id: par_id[s.localite_id].code for s in series}
        for m in mesures:
            ghi.setdefault((source.source_code, loc_de[m.serie_id]), {})[(m.annee, m.mois)] = (
                m.valeur
            )
        incompletes = [
            loc
            for loc in noms
            if len(ghi.get((source.source_code, loc), {})) != 12 * source.nb_annees
        ]
        non_positifs = sum(m.valeur is None or m.valeur <= 0 for m in mesures)
        if incompletes or non_positifs or len(mesures) != NB_POINTS * 12 * source.nb_annees:
            raise RuntimeError(
                f"Migration 0041 : GHI {source.source_code} : {len(mesures)} mesures, "
                f"{non_positifs} non positive(s), incomplètes : {incompletes!r}."
            )

    # 3. Séries calculées (source éditoriale kuma_calculs).
    source_calcul_id = bind.execute(
        sa.text("SELECT id FROM sources WHERE code = :c"), {"c": SOURCE_CALCUL}
    ).scalar_one()
    op.bulk_insert(
        sa.table(
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
        ),
        [
            {
                "code": source.code_serie(code),
                "libelle": (
                    f"Indice de clarté {source.libelle} — {noms[code]} "
                    f"({source.annee_debut}-{source.annee_fin})"
                ),
                "localite_id": localites[code].id,
                "grandeur_code": GRANDEUR_CODE,
                "source_id": source_calcul_id,
                "periode_debut": f"{source.annee_debut}-01-01",
                "periode_fin": f"{source.annee_fin}-12-31",
                "methode_collecte": "calcul_derive",
                "granularite": None,
                "note_publique": _note(source),
            }
            for source in SOURCES_KT
            for code in sorted(noms)
        ],
    )
    ids_series = dict(
        bind.execute(
            sa.text("SELECT code, id FROM series_metadonnees WHERE code = ANY(:c)"),
            {"c": _codes_kt()},
        ).all()
    )
    if len(ids_series) != NB_SERIES_ATTENDU:
        raise RuntimeError(f"Migration 0041 : {len(ids_series)} séries, {NB_SERIES_ATTENDU}.")

    # 4. kt mensuel et annuel (fonctions pures), domaine 0 < kt < 1, puis COPY.
    lignes: list[tuple[object, ...]] = []
    for source in SOURCES_KT:
        for code in sorted(noms):
            calcul = calculer_kt(
                ghi[(source.source_code, code)],
                float(localites[code].latitude),
                constante_solaire=CONSTANTE_SOLAIRE,
                modele=MODELE_SOLAIRE,
            )
            if len(calcul) != 13 * source.nb_annees:
                raise RuntimeError(
                    f"Migration 0041 : {source.code_serie(code)} : {len(calcul)} valeurs, "
                    f"{13 * source.nb_annees} attendues."
                )
            hors = [c for c in calcul if not 0.0 < c["valeur"] < 1.0]
            if hors:
                raise RuntimeError(
                    f"Migration 0041 : {source.code_serie(code)} : {len(hors)} kt hors de "
                    f"]0, 1[ : {hors[:3]!r}."
                )
            lignes += [
                (
                    GRANDEUR_CODE,
                    localites[code].id,
                    ids_series[source.code_serie(code)],
                    c["periode_type"],
                    c["annee"],
                    c["annee"],
                    c["mois"],
                    VERSION_FORMULE,
                    c["valeur"],
                    "B",
                )
                for c in calcul
            ]
    connexion = bind.connection.driver_connection  # psycopg 3 : COPY pour le volume
    with (
        connexion.cursor() as curseur,
        curseur.copy(
            "COPY grandeurs_metier (grandeur_code, localite_id, series_metadonnees_id, "
            "periode_type, annee_debut, annee_fin, mois, version_formule, valeur, "
            "niveau_confiance_derive) FROM STDIN"
        ) as copie,
    ):
        for ligne in lignes:
            copie.write_row(ligne)

    # 5. Garde-fous en base : comptes exacts et domaine.
    comptes = dict(
        bind.execute(
            sa.text(
                "SELECT periode_type, COUNT(*) FROM grandeurs_metier WHERE grandeur_code = :g "
                "GROUP BY periode_type"
            ),
            {"g": GRANDEUR_CODE},
        ).all()
    )
    attendu = {"mensuel": NB_MENSUEL_ATTENDU, "annuel": NB_ANNUEL_ATTENDU}
    if comptes != attendu:
        raise RuntimeError(f"Migration 0041 : lignes {comptes!r}, {attendu!r} attendues.")
    hors_domaine = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM grandeurs_metier WHERE grandeur_code = :g "
            "AND (valeur IS NULL OR valeur <= 0 OR valeur >= 1)"
        ),
        {"g": GRANDEUR_CODE},
    ).scalar_one()
    if hors_domaine:
        raise RuntimeError(f"Migration 0041 : {hors_domaine} valeur(s) hors de ]0, 1[.")
    bind.execute(sa.text("ANALYZE series_metadonnees"))
    bind.execute(sa.text("ANALYZE grandeurs_metier"))


def downgrade() -> None:
    bind = op.get_bind()
    codes = _codes_kt()
    bind.execute(
        sa.text(
            "DELETE FROM grandeurs_metier WHERE series_metadonnees_id IN "
            "(SELECT id FROM series_metadonnees WHERE code = ANY(:c))"
        ),
        {"c": codes},
    )
    bind.execute(sa.text("DELETE FROM series_metadonnees WHERE code = ANY(:c)"), {"c": codes})
    # La grandeur kt (seed 0002) est conservée.
