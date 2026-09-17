"""Schémas Pydantic des endpoints `/api/v1/localites` (cycle C-DC-3).

3 schémas exposés :

- :class:`LocaliteListee` : ligne du listing
  (``GET /api/v1/localites``) et payload du détail
  (``GET /api/v1/localites/{code}``).
- :class:`LocaliteListeePaginee` : envelope paginée
  ``{items, total, limit, offset}`` - pattern identique à
  :class:`SerieListeePaginee` (cf. ADR-0001 Data Core).
- :data:`LocaliteDetail` : alias de :class:`LocaliteListee` pour cette
  itération. Si un futur cycle enrichit le détail (séries associées,
  hiérarchie récursive complète, etc.), créer une sous-classe sur le
  pattern :class:`SerieDetail`.

Conventions d'alignement avec :class:`SerieListee` (ADR-0001) :

- IDs en ``int`` natif (BigInteger DB, pas UUID).
- Datetimes en ISO-8601 UTC avec suffixe ``Z`` (géré par Pydantic
  sérialisation par défaut).
- Renommage public ``cree_le`` -> ``created_at``,
  ``modifie_le`` -> ``updated_at`` (cf. nommage public ADR-0001).
- ``latitude``/``longitude`` exposés en ``float`` (converti depuis
  ``Numeric(11,8)`` / ``Numeric(12,8)`` DB pour interop JSON ;
  précision pratique 7 décimales 1 cm).
- ``parent_code`` dénormalisé via self-JOIN ``localites P`` côté
  routeur (évite un appel en cascade côté consommateur Kuma Science
  pour résoudre la hiérarchie).

Cf. ADR-0002 Data Core.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LocaliteListee(BaseModel):
    """Ligne du listing `GET /api/v1/localites` et payload du détail.

    Couvre identité, hiérarchie, géolocalisation, démographie,
    métadonnées techniques et audit.

    Tous les champs viennent directement de la table ``localites`` (cf.
    modèle SQLAlchemy ``Localite``). Aucune déformation côté producteur
    sauf le ``parent_code`` qui est dénormalisé via self-JOIN pour
    éviter aux consommateurs un second appel.
    """

    # === Identifiants ====================================================
    id: int
    code: str = Field(min_length=1, max_length=100)
    nom: str

    # === Type et hiérarchie ==============================================
    type_localite: str  # enum : continent, region_supranationale, pays,
    #                     region_administrative, commune, site
    parent_id: int | None
    parent_code: str | None  # dénormalisé via self-JOIN (LEFT JOIN
    #                          localites P ON L.parent_id = P.id)

    # === Géolocalisation =================================================
    pays_iso3: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    latitude: float | None  # converti Numeric(11,8) -> float
    longitude: float | None  # converti Numeric(12,8) -> float
    altitude_metres: int | None

    # === Démographie =====================================================
    population_estimee: int | None
    annee_population: int | None

    # === Métadonnées techniques ==========================================
    fuseau_horaire: str | None  # IANA TZ (e.g. "Africa/Conakry")

    # === Audit (renommé public) ==========================================
    created_at: datetime  # <- cree_le
    updated_at: datetime  # <- modifie_le

    # === Flag actif ======================================================
    actif: bool


class LocaliteListeePaginee(BaseModel):
    """Envelope paginée du listing `GET /api/v1/localites` (ADR-0002).

    Pattern identique à :class:`SerieListeePaginee` mergée en cycle
    1-7d (ADR-0001). Le champ ``total`` permet aux consommateurs de
    connaître le nombre total de localités matchant les filtres sans
    avoir à boucler jusqu'à une page vide.
    """

    items: list[LocaliteListee]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


# Pour cette première itération, le détail expose les mêmes champs que
# le listing. Si un futur cycle enrichit le détail (séries associées,
# hiérarchie complète via WITH RECURSIVE, etc.), créer une sous-classe
# ``LocaliteDetail(LocaliteListee)`` ajoutant les champs additionnels -
# pattern :class:`SerieDetail`.
LocaliteDetail = LocaliteListee


# === Schemas resolution au point (ADR-0004) ===============================


class PointGeographique(BaseModel):
    """Point WGS84 en degres decimaux."""

    latitude_deg: float
    longitude_deg: float


class CelluleResolution(BaseModel):
    """Cellule de la grille de climatologie contenant le point.

    Grille de la source de climatologie mensuelle : 1 degre x 1 degre,
    frontieres aux degres entiers (verification empirique 2026-07-20 :
    serie de Kerouane vs releve au point de Tokounou, meme cellule,
    ecart nul sur les 12 moyennes mensuelles 1991-2020).
    """

    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float


class LocaliteResolue(BaseModel):
    """Localite du referentiel retenue par la resolution."""

    code: str
    nom: str
    latitude_deg: float
    longitude_deg: float


class ReponseResolution(BaseModel):
    """Reponse de ``GET /v1/localites/resolution``.

    ``meme_cellule`` : vrai si la localite retenue echantillonne la
    cellule du point (sa climatologie est celle du point) ; faux si
    aucune candidate ne partage la cellule - la plus proche est alors
    renvoyee avec sa distance, et le consommateur doit afficher
    l'hypothese de transport.
    """

    point: PointGeographique
    grandeur: str
    cellule: CelluleResolution
    localite: LocaliteResolue
    distance_km: float
    meme_cellule: bool
    serie_climatologie: str = Field(
        description=(
            "Code de la serie de climatologie mensuelle de la localite "
            "retenue : la serie qui represente la cellule du point. Le "
            "Core dit quelle serie consommer, les clients ne le "
            "reconstruisent jamais par convention de nommage (genericite "
            "pays, residu 2 du brief de chantier)."
        )
    )
