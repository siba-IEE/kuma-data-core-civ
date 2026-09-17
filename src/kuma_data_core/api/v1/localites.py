"""Endpoints `/api/v1/localites` - listing + detail.

Deux endpoints :

- ``GET /v1/localites`` (authentifie) : listing paginee des localites
  presentes dans la table ``localites`` (6 villes Guinee +
  entrees hierarchie : Afrique, Guinee pays, regions administratives).
  Filtrage optionnel par ``pays_iso3``, ``type_localite``,
  ``parent_code``, ``actif``. Pagination offset-based
  ``limit=100/max=1000``.
- ``GET /v1/localites/{code}`` (authentifie) : detail individuel
  identifie par le code naming (slug ASCII pour racines, ou
  ``<code_pays>_<slug>`` pour entites administratives, cf.
  ``db/models/localites.py``).

Pattern miroir de :mod:`kuma_data_core.api.v1.series` (cf. ADR-0001
Data Core). Envelope paginee identique, conventions de typage
identiques, gestion d'erreurs via :class:`ExceptionKuma` +
:class:`CodeErreur` identique.

``parent_code`` denormalise via self-JOIN sur ``localites`` pour
faciliter le routage cote front sans appel en cascade.

Cf. ADR-0002 Data Core.
"""

from __future__ import annotations

import math
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.api.codes_erreur import CodeErreur
from kuma_data_core.api.dependencies import CleApiValidee
from kuma_data_core.api.erreurs import ExceptionKuma
from kuma_data_core.api.v1.schemas.localites import (
    CelluleResolution,
    LocaliteDetail,
    LocaliteListee,
    LocaliteListeePaginee,
    LocaliteResolue,
    PointGeographique,
    ReponseResolution,
)
from kuma_data_core.db.session import obtenir_session

routeur = APIRouter(prefix="/localites", tags=["localites"])


# === Constantes pagination ================================================

_LIMIT_DEFAUT_LISTING: int = 100
_LIMIT_MAX_LISTING: int = 1000


# === Helpers ==============================================================


def _to_float_optional(valeur: object) -> float | None:
    """Convertit ``Decimal | None`` -> ``float | None`` pour serialisation JSON.

    Les colonnes ``latitude`` (Numeric(11,8)) et ``longitude``
    (Numeric(12,8)) sont retournees par SQLAlchemy comme
    :class:`decimal.Decimal`. JSON n'a pas de type decimal natif et
    les consommateurs Kuma (Zod, TypeScript) consomment des
    ``number``. La precision pratique reste >= 1 cm (7-8 decimales sur
    un float64), suffisante pour la cartographie editorial.
    """
    if valeur is None:
        return None
    return float(valeur)  # type: ignore[arg-type]


_RAYON_TERRE_KM = 6371.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance grand cercle entre deux points WGS84 (formule haversine).

    Precision suffisante pour l'affichage d'une distance de transport
    de calage (dizaines de km, arrondie au dixieme dans la reponse).
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * _RAYON_TERRE_KM * math.asin(math.sqrt(a))


# === Endpoint listing =====================================================


@routeur.get(
    "",
    response_model=LocaliteListeePaginee,
    status_code=status.HTTP_200_OK,
    summary="Listing des localites disponibles",
    description=(
        "Retourne la liste paginee des localites de la table "
        "`localites`, dans une envelope `{items, total, limit, offset}`. "
        "Filtrage optionnel par pays_iso3, type_localite, parent_code "
        "ou statut actif. Cf. ADR-0002 Data Core."
    ),
)
def lister_localites(
    _cle: CleApiValidee,
    session: Annotated[Session, Depends(obtenir_session)],
    pays_iso3: Annotated[
        str | None,
        Query(description="Filtre pays ISO 3166-1 alpha-3 (ex. GIN, SEN)"),
    ] = None,
    type_localite: Annotated[
        str | None,
        Query(
            description=(
                "Filtre type : continent, region_supranationale, pays, "
                "region_administrative, commune, site"
            ),
        ),
    ] = None,
    parent_code: Annotated[
        str | None,
        Query(description="Filtre code de la localite parente (ex. gin pour villes guineennes)"),
    ] = None,
    actif: Annotated[
        bool | None, Query(description="Filtre actif (TRUE/FALSE), defaut TRUE")
    ] = True,
    limit: Annotated[int, Query(ge=1, le=_LIMIT_MAX_LISTING)] = _LIMIT_DEFAUT_LISTING,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LocaliteListeePaginee:
    """Listing paginee des localites dans une envelope `{items, total, limit, offset}`.

    Conventions identiques au listing `/v1/series` (ADR-0001) :

    - ``actif`` defaut TRUE (les entrees soft-deleted sont masquees
      par defaut). Passer ``?actif=false`` pour inspecter les entrees
      desactivees.
    - ORDER BY ``code ASC`` (stable et previsible pour la pagination).
    - ``COUNT(*)`` separe du SELECT items pour lisibilite ; le cout
      additionnel est negligeable sur 10-20 localites et
      reste acceptable jusqu'a plusieurs centaines.
    """
    clauses: list[str] = []
    params: dict[str, object] = {"limit": limit, "offset": offset}

    if pays_iso3 is not None:
        clauses.append("L.pays_iso3 = :pays_iso3")
        params["pays_iso3"] = pays_iso3
    if type_localite is not None:
        clauses.append("L.type_localite = :type_localite")
        params["type_localite"] = type_localite
    if parent_code is not None:
        clauses.append("P.code = :parent_code")
        params["parent_code"] = parent_code
    if actif is not None:
        clauses.append("L.actif = :actif")
        params["actif"] = actif

    where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    total = session.execute(
        text(
            f"""
            SELECT COUNT(*) AS n
            FROM localites L
            LEFT JOIN localites P ON L.parent_id = P.id
            {where_sql}
            """
        ),
        {k: v for k, v in params.items() if k not in ("limit", "offset")},
    ).scalar_one()

    rows = session.execute(
        text(
            f"""
            SELECT
                L.id,
                L.code,
                L.nom,
                L.type_localite,
                L.parent_id,
                P.code AS parent_code,
                L.pays_iso3,
                L.latitude,
                L.longitude,
                L.altitude_metres,
                L.population_estimee,
                L.annee_population,
                L.fuseau_horaire,
                L.cree_le AS created_at,
                L.modifie_le AS updated_at,
                L.actif
            FROM localites L
            LEFT JOIN localites P ON L.parent_id = P.id
            {where_sql}
            ORDER BY L.code
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).all()

    items = [
        LocaliteListee(
            id=int(r.id),
            code=r.code,
            nom=r.nom,
            type_localite=r.type_localite,
            parent_id=int(r.parent_id) if r.parent_id is not None else None,
            parent_code=r.parent_code,
            pays_iso3=r.pays_iso3,
            latitude=_to_float_optional(r.latitude),
            longitude=_to_float_optional(r.longitude),
            altitude_metres=int(r.altitude_metres) if r.altitude_metres is not None else None,
            population_estimee=(
                int(r.population_estimee) if r.population_estimee is not None else None
            ),
            annee_population=int(r.annee_population) if r.annee_population is not None else None,
            fuseau_horaire=r.fuseau_horaire,
            created_at=r.created_at,
            updated_at=r.updated_at,
            actif=r.actif,
        )
        for r in rows
    ]
    return LocaliteListeePaginee(items=items, total=int(total), limit=limit, offset=offset)


# === Endpoint resolution au point (ADR-0004) ==============================
# Declare AVANT ``/{code}`` : FastAPI matche les routes dans l'ordre de
# declaration et ``resolution`` serait sinon capture comme un code.


@routeur.get(
    "/resolution",
    response_model=ReponseResolution,
    status_code=status.HTTP_200_OK,
    summary="Resolution d'un point quelconque vers la localite qui l'echantillonne",
    description=(
        "Pour un point (lat, lon), retourne la localite du referentiel "
        "dont la climatologie mensuelle echantillonne la cellule de "
        "grille contenant le point. Le plus-proche-voisin naif est "
        "faux : la localite la plus proche peut appartenir a une autre "
        "cellule (cas demontre : Tokounou est plus proche de Kankan "
        "mais dans la cellule de Kerouane)."
    ),
)
def resoudre_point(
    _cle: CleApiValidee,
    session: Annotated[Session, Depends(obtenir_session)],
    lat: Annotated[float, Query(ge=-90, le=90, description="Latitude WGS84 du point.")],
    lon: Annotated[float, Query(ge=-180, le=180, description="Longitude WGS84 du point.")],
    grandeur: Annotated[str, Query(pattern="^ghi$")] = "ghi",
) -> ReponseResolution:
    """Resout un point vers la localite echantillonnant sa cellule.

    Candidates : les localites actives portant une serie climatologie
    mensuelle active de la grandeur demandee sur la periode de
    reference 1991-2020 (les points d'ingestion du referentiel). La
    cellule est celle de la grille de la source de climatologie
    (1 degre x 1 degre, frontieres aux degres entiers - verification
    empirique du 2026-07-20 : la moyenne 1991-2020 de la serie de
    Kerouane reproduit le releve au point de Tokounou, meme cellule,
    ecart nul sur les 12 mois).

    Si aucune candidate ne partage la cellule du point,
    ``meme_cellule`` vaut ``false`` et la candidate la plus proche est
    renvoyee avec sa distance : au consommateur d'afficher l'hypothese
    de transport. 404 ``RESSOURCE_INTROUVABLE`` si le referentiel ne
    porte aucune candidate (catalogue vide pour la grandeur).
    """
    rows = session.execute(
        text(
            """
            SELECT l.code, l.nom, l.latitude, l.longitude,
                   MIN(sm.code) AS serie_code
            FROM localites l
            JOIN series_metadonnees sm ON sm.localite_id = l.id
            WHERE l.actif = TRUE
              AND l.latitude IS NOT NULL AND l.longitude IS NOT NULL
              AND sm.actif = TRUE
              AND sm.granularite = 'mensuel'
              AND sm.grandeur_code = :grandeur
              AND sm.periode_debut = '1991-01-01'
              AND sm.periode_fin = '2020-12-31'
            GROUP BY l.code, l.nom, l.latitude, l.longitude
            """
        ),
        {"grandeur": grandeur},
    ).all()
    if not rows:
        raise ExceptionKuma(
            code=CodeErreur.RESSOURCE_INTROUVABLE,
            message="Aucun point d'ingestion de climatologie pour cette grandeur.",
            statut_http=status.HTTP_404_NOT_FOUND,
        )

    cellule_lat = math.floor(lat)
    cellule_lon = math.floor(lon)

    candidates = [
        (str(r.code), str(r.nom), float(r.latitude), float(r.longitude), str(r.serie_code))
        for r in rows
    ]
    meilleure: tuple[float, int] | None = None
    meilleure_meme_cellule: tuple[float, int] | None = None
    for indice, (_code, _nom, r_lat, r_lon, _serie) in enumerate(candidates):
        distance = _haversine_km(lat, lon, r_lat, r_lon)
        if meilleure is None or distance < meilleure[0]:
            meilleure = (distance, indice)
        dans_cellule = math.floor(r_lat) == cellule_lat and math.floor(r_lon) == cellule_lon
        if dans_cellule and (
            meilleure_meme_cellule is None or distance < meilleure_meme_cellule[0]
        ):
            meilleure_meme_cellule = (distance, indice)

    assert meilleure is not None  # rows non vide, verifie plus haut
    meme_cellule = meilleure_meme_cellule is not None
    distance_km, indice_retenu = (
        meilleure_meme_cellule if meilleure_meme_cellule is not None else meilleure
    )
    code, nom, retenue_lat, retenue_lon, serie_climatologie = candidates[indice_retenu]

    return ReponseResolution(
        point=PointGeographique(latitude_deg=lat, longitude_deg=lon),
        grandeur=grandeur,
        cellule=CelluleResolution(
            lat_min=float(cellule_lat),
            lat_max=float(cellule_lat + 1),
            lon_min=float(cellule_lon),
            lon_max=float(cellule_lon + 1),
        ),
        localite=LocaliteResolue(
            code=code,
            nom=nom,
            latitude_deg=retenue_lat,
            longitude_deg=retenue_lon,
        ),
        distance_km=round(distance_km, 1),
        meme_cellule=meme_cellule,
        serie_climatologie=serie_climatologie,
    )


# === Endpoint detail ======================================================


@routeur.get(
    "/{code}",
    response_model=LocaliteDetail,
    status_code=status.HTTP_200_OK,
    summary="Detail d'une localite",
    description=(
        "Retourne le detail d'une localite identifiee par son code "
        "(slug ASCII pour racines, `<code_pays>_<slug>` pour entites "
        "administratives)."
    ),
)
def detailler_localite(
    code: str,
    _cle: CleApiValidee,
    session: Annotated[Session, Depends(obtenir_session)],
) -> LocaliteDetail:
    """Detail d'une localite (16 champs catalogue).

    Leve ``ExceptionKuma`` ``RESSOURCE_LOCALITE_INCONNUE`` (HTTP 404)
    si le code ne match aucune entree (y compris les entrees
    desactivees : pas de filtre ``actif`` au detail, le consommateur
    qui appelle un code precis a deja conscience de la ressource
    ciblee).
    """
    row = session.execute(
        text(
            """
            SELECT
                L.id,
                L.code,
                L.nom,
                L.type_localite,
                L.parent_id,
                P.code AS parent_code,
                L.pays_iso3,
                L.latitude,
                L.longitude,
                L.altitude_metres,
                L.population_estimee,
                L.annee_population,
                L.fuseau_horaire,
                L.cree_le AS created_at,
                L.modifie_le AS updated_at,
                L.actif
            FROM localites L
            LEFT JOIN localites P ON L.parent_id = P.id
            WHERE L.code = :code
            """
        ),
        {"code": code},
    ).first()

    if row is None:
        raise ExceptionKuma(
            code=CodeErreur.RESSOURCE_LOCALITE_INCONNUE,
            message=f"Localite {code!r} introuvable.",
            statut_http=status.HTTP_404_NOT_FOUND,
        )

    return LocaliteDetail(
        id=int(row.id),
        code=row.code,
        nom=row.nom,
        type_localite=row.type_localite,
        parent_id=int(row.parent_id) if row.parent_id is not None else None,
        parent_code=row.parent_code,
        pays_iso3=row.pays_iso3,
        latitude=_to_float_optional(row.latitude),
        longitude=_to_float_optional(row.longitude),
        altitude_metres=int(row.altitude_metres) if row.altitude_metres is not None else None,
        population_estimee=(
            int(row.population_estimee) if row.population_estimee is not None else None
        ),
        annee_population=(int(row.annee_population) if row.annee_population is not None else None),
        fuseau_horaire=row.fuseau_horaire,
        created_at=row.created_at,
        updated_at=row.updated_at,
        actif=row.actif,
    )
