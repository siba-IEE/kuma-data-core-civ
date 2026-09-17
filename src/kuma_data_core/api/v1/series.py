"""Endpoints `/api/v1/series` - listing + detail.

Deux endpoints :

- ``GET /v1/series`` (authentifie) : listing des series disponibles
  (filtrage par localite / grandeur / source / actif, pagination
  offset-based limit=100/max=1000).
- ``GET /v1/series/{code_serie}`` (authentifie) : detail d'une serie
  identifiee par son code naming, avec ses mesures resolues via
  ``resolve_table_from_series_metadata``.
  Pagination limit=1000/max=10 000, filtre temporel ``from``/``to``,
  format JSON ou CSV.

Couvre les 3 tables-cibles :
- ``mesures_ressource`` (journalier)
- ``mesures_ressource_mensuelles`` (mensuel brut)
- ``grandeurs_metier`` (calcule Kuma) - via la vue
  ``v_grandeurs_metier_courantes`` pour semantique « valeurs publiables »
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.api.codes_erreur import CodeErreur
from kuma_data_core.api.dependencies import CleApiValidee
from kuma_data_core.api.erreurs import ExceptionKuma
from kuma_data_core.api.services.serie_lecture import (
    TableMesures,
    resolve_table_from_series_metadata,
)
from kuma_data_core.api.v1.schemas.series import (
    GrandeurMetierValeur,
    MesureJournaliere,
    MesureLue,
    MesureMensuelle,
    SerieDetail,
    SerieListee,
    SerieListeePaginee,
)
from kuma_data_core.db.session import obtenir_session

routeur = APIRouter(prefix="/series", tags=["series"])


# === Constantes pagination ================================================

_LIMIT_DEFAUT_LISTING: int = 100
_LIMIT_MAX_LISTING: int = 1000
_LIMIT_DEFAUT_DETAIL: int = 1000
_LIMIT_MAX_DETAIL: int = 10_000

_FORMATS_SUPPORTES: tuple[str, ...] = ("json", "csv")


# === Helpers ==============================================================


def _parser_borne_temporelle(valeur: str | None, nom_param: str) -> date | None:
    """Parse ``YYYY-MM-DD`` ou ``YYYY-MM`` (interprete 1er du mois).

    Args:
        valeur : chaine a parser ou None.
        nom_param : nom du parametre query pour les messages d'erreur.

    Returns:
        ``date`` parsee ou ``None`` si entree None.

    Raises:
        ExceptionKuma : HTTP 400 ``VALIDATION_FORMAT_DATE_INVALIDE`` si
            format non reconnu.
    """
    if valeur is None:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(valeur, fmt).date()
        except ValueError:
            continue
    raise ExceptionKuma(
        code=CodeErreur.VALIDATION_FORMAT_DATE_INVALIDE,
        message=(
            f"Parametre {nom_param!r} : format attendu YYYY-MM-DD ou YYYY-MM, recu {valeur!r}."
        ),
        statut_http=status.HTTP_400_BAD_REQUEST,
    )


def _valider_format(format_demande: str) -> str:
    """Valide ``format`` parmi ``_FORMATS_SUPPORTES``."""
    if format_demande not in _FORMATS_SUPPORTES:
        raise ExceptionKuma(
            code=CodeErreur.VALIDATION_FORMAT_NON_SUPPORTE,
            message=(
                f"Parametre format={format_demande!r} non supporte. "
                f"Valeurs autorisees : {list(_FORMATS_SUPPORTES)}."
            ),
            statut_http=status.HTTP_400_BAD_REQUEST,
        )
    return format_demande


# === Endpoint listing =====================================================


@routeur.get(
    "",
    response_model=SerieListeePaginee,
    status_code=status.HTTP_200_OK,
    summary="Listing des series disponibles",
    description=(
        "Retourne la liste paginee des series presentes dans "
        "`series_metadonnees`, dans une envelope "
        "`{items, total, limit, offset}`. Filtrage optionnel par "
        "localite, grandeur, source, ou statut actif. Cf. ADR-0001."
    ),
)
def lister_series(
    _cle: CleApiValidee,
    session: Annotated[Session, Depends(obtenir_session)],
    localite: Annotated[str | None, Query(description="Code localite (ex. gin_kindia)")] = None,
    grandeur: Annotated[str | None, Query(description="Code grandeur (ex. ghi, hep)")] = None,
    source: Annotated[
        str | None, Query(description="Code source (ex. nasa_power, kuma_calculs)")
    ] = None,
    actif: Annotated[
        bool | None, Query(description="Filtre actif (TRUE/FALSE), defaut TRUE")
    ] = True,
    limit: Annotated[int, Query(ge=1, le=_LIMIT_MAX_LISTING)] = _LIMIT_DEFAUT_LISTING,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SerieListeePaginee:
    """Listing paginé des séries dans une envelope `{items, total, limit, offset}`.

    La réponse est une envelope paginée (et non un tableau JSON nu).
    Cohérent avec les conventions d'API publique et permet aux
    consommateurs de connaître le nombre total de séries matchant les
    filtres sans boucler jusqu'à une page vide. Cf. ADR-0001 Data Core.
    """
    clauses: list[str] = []
    params: dict[str, object] = {"limit": limit, "offset": offset}

    if localite is not None:
        clauses.append("l.code = :localite_code")
        params["localite_code"] = localite
    if grandeur is not None:
        clauses.append("sm.grandeur_code = :grandeur_code")
        params["grandeur_code"] = grandeur
    if source is not None:
        clauses.append("s.code = :source_code")
        params["source_code"] = source
    if actif is not None:
        clauses.append("sm.actif = :actif")
        params["actif"] = actif

    where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    # Count total filtré (séparé du SELECT items pour lisibilité ; le
    # coût supplémentaire est négligeable sur le volume de séries
    # actuel, à monitorer si la couverture passe à plusieurs centaines).
    # cf. ADR-0001 §performance.
    total = session.execute(
        text(
            f"""
            SELECT COUNT(*) AS n
            FROM series_metadonnees sm
            JOIN localites l ON l.id = sm.localite_id
            JOIN sources s ON s.id = sm.source_id
            {where_sql}
            """
        ),
        {k: v for k, v in params.items() if k not in ("limit", "offset")},
    ).scalar_one()

    rows = session.execute(
        text(
            f"""
            SELECT
                sm.id,
                sm.code,
                sm.libelle,
                sm.localite_id,
                l.code AS localite_code,
                l.nom AS localite_nom,
                l.pays_iso3 AS localite_iso3,
                sm.grandeur_code,
                gr.libelle AS grandeur_label,
                u.symbole AS grandeur_unit,
                sm.source_id,
                s.code AS source_code,
                s.titre AS source_label,
                s.url AS source_url,
                sm.periode_debut,
                sm.periode_fin,
                sm.methode_collecte,
                sm.note_publique AS notes_fr,
                sm.cree_le AS created_at,
                sm.modifie_le AS updated_at,
                sm.actif
            FROM series_metadonnees sm
            JOIN localites l ON l.id = sm.localite_id
            JOIN sources s ON s.id = sm.source_id
            JOIN grandeurs_referentiel gr ON gr.code = sm.grandeur_code
            JOIN unites u ON u.id = gr.unite_id
            {where_sql}
            ORDER BY sm.code
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).all()

    items = [
        SerieListee(
            id=int(r.id),
            code=r.code,
            libelle=r.libelle,
            localite_id=int(r.localite_id),
            localite_code=r.localite_code,
            localite_nom=r.localite_nom,
            localite_iso3=r.localite_iso3,
            grandeur_code=r.grandeur_code,
            grandeur_label=r.grandeur_label,
            grandeur_unit=r.grandeur_unit,
            source_id=int(r.source_id),
            source_code=r.source_code,
            source_label=r.source_label,
            source_url=r.source_url,
            periode_debut=r.periode_debut,
            periode_fin=r.periode_fin,
            methode_collecte=r.methode_collecte,
            notes_fr=r.notes_fr,
            created_at=r.created_at,
            updated_at=r.updated_at,
            actif=r.actif,
        )
        for r in rows
    ]
    return SerieListeePaginee(items=items, total=int(total), limit=limit, offset=offset)


# === Endpoint detail ======================================================


def _lire_mesures_journalier(
    session: Session,
    serie_id: int,
    bornes: tuple[date | None, date | None],
    limit: int,
    offset: int,
) -> list[MesureLue]:
    """Lit les mesures journalieres depuis ``mesures_ressource``."""
    from_d, to_d = bornes
    clauses = ["mr.serie_id = :serie_id", "mr.valide_au IS NULL"]
    params: dict[str, object] = {"serie_id": serie_id, "limit": limit, "offset": offset}
    if from_d is not None:
        clauses.append("mr.instant_mesure >= :from_d")
        params["from_d"] = from_d
    if to_d is not None:
        clauses.append("mr.instant_mesure <= :to_d")
        params["to_d"] = to_d

    rows = session.execute(
        text(
            f"""
            SELECT
                mr.instant_mesure, mr.valeur,
                mr.niveau_confiance_derive, mr.niveau_confiance_override,
                COALESCE(mr.niveau_confiance_override, mr.niveau_confiance_derive)
                  AS niveau_effectif,
                mr.statut
            FROM mesures_ressource mr
            WHERE {" AND ".join(clauses)}
            ORDER BY mr.instant_mesure
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).all()
    return [
        MesureJournaliere(
            instant_mesure=r.instant_mesure,
            valeur=float(r.valeur),
            niveau_confiance_derive=r.niveau_confiance_derive,
            niveau_confiance_override=r.niveau_confiance_override,
            niveau_effectif=r.niveau_effectif,
            statut=r.statut,
        )
        for r in rows
    ]


def _lire_mesures_mensuel(
    session: Session,
    serie_id: int,
    bornes: tuple[date | None, date | None],
    limit: int,
    offset: int,
) -> list[MesureLue]:
    """Lit les mesures mensuelles depuis ``mesures_ressource_mensuelles``."""
    from_d, to_d = bornes
    clauses = ["m.serie_id = :serie_id", "m.valide_au IS NULL"]
    params: dict[str, object] = {"serie_id": serie_id, "limit": limit, "offset": offset}
    if from_d is not None:
        clauses.append("(m.annee, m.mois) >= (:from_y, :from_m)")
        params["from_y"] = from_d.year
        params["from_m"] = from_d.month
    if to_d is not None:
        clauses.append("(m.annee, m.mois) <= (:to_y, :to_m)")
        params["to_y"] = to_d.year
        params["to_m"] = to_d.month

    rows = session.execute(
        text(
            f"""
            SELECT
                m.annee, m.mois, m.valeur,
                m.niveau_confiance_derive, m.niveau_confiance_override,
                COALESCE(m.niveau_confiance_override, m.niveau_confiance_derive)
                  AS niveau_effectif,
                m.statut
            FROM mesures_ressource_mensuelles m
            WHERE {" AND ".join(clauses)}
            ORDER BY m.annee, m.mois
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).all()
    return [
        MesureMensuelle(
            annee=int(r.annee),
            mois=int(r.mois),
            valeur=float(r.valeur),
            niveau_confiance_derive=r.niveau_confiance_derive,
            niveau_confiance_override=r.niveau_confiance_override,
            niveau_effectif=r.niveau_effectif,
            statut=r.statut,
        )
        for r in rows
    ]


def _lire_mesures_grandeurs_metier(
    session: Session,
    serie_id: int,
    bornes: tuple[date | None, date | None],
    limit: int,
    offset: int,
) -> list[MesureLue]:
    """Lit les valeurs grandeurs_metier via la vue v_grandeurs_metier_courantes.

    La vue applique automatiquement les filtres ``valide_au IS NULL`` +
    ``version_formule = version_formule_actuelle`` + ``statut <> 'deprecie'``
    et expose ``niveau_effectif`` resolu.
    """
    from_d, to_d = bornes
    clauses = ["v.series_metadonnees_id = :serie_id"]
    params: dict[str, object] = {"serie_id": serie_id, "limit": limit, "offset": offset}
    if from_d is not None:
        clauses.append("(v.annee_debut, COALESCE(v.mois, 1)) >= (:from_y, :from_m)")
        params["from_y"] = from_d.year
        params["from_m"] = from_d.month
    if to_d is not None:
        clauses.append("(v.annee_fin, COALESCE(v.mois, 12)) <= (:to_y, :to_m)")
        params["to_y"] = to_d.year
        params["to_m"] = to_d.month

    rows = session.execute(
        text(
            f"""
            SELECT
                v.periode_type, v.annee_debut, v.annee_fin, v.mois,
                v.version_formule, v.valeur,
                v.niveau_confiance_derive, v.niveau_confiance_override,
                v.niveau_effectif, v.statut
            FROM v_grandeurs_metier_courantes v
            WHERE {" AND ".join(clauses)}
            ORDER BY v.annee_debut, v.mois NULLS FIRST
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).all()
    return [
        GrandeurMetierValeur(
            periode_type=r.periode_type,
            annee_debut=int(r.annee_debut),
            annee_fin=int(r.annee_fin),
            mois=int(r.mois) if r.mois is not None else None,
            version_formule=int(r.version_formule),
            valeur=float(r.valeur),
            niveau_confiance_derive=r.niveau_confiance_derive,
            niveau_confiance_override=r.niveau_confiance_override,
            niveau_effectif=r.niveau_effectif,
            statut=r.statut,
        )
        for r in rows
    ]


def _serialiser_csv(serie_detail: SerieDetail) -> str:
    """Serialise un SerieDetail en CSV (helper interne)."""
    buffer = io.StringIO()
    w = csv.writer(buffer)
    # Header generique pour les 3 categories de mesures
    w.writerow(
        [
            "code_serie",
            "type",
            "annee",
            "mois",
            "instant_mesure",
            "periode_type",
            "annee_debut",
            "annee_fin",
            "version_formule",
            "valeur",
            "niveau_effectif",
            "statut",
        ]
    )
    for m in serie_detail.mesures:
        if isinstance(m, MesureJournaliere):
            w.writerow(
                [
                    serie_detail.code,
                    m.type,
                    "",
                    "",
                    m.instant_mesure.isoformat(),
                    "",
                    "",
                    "",
                    "",
                    m.valeur,
                    m.niveau_effectif,
                    m.statut,
                ]
            )
        elif isinstance(m, MesureMensuelle):
            w.writerow(
                [
                    serie_detail.code,
                    m.type,
                    m.annee,
                    m.mois,
                    "",
                    "",
                    "",
                    "",
                    "",
                    m.valeur,
                    m.niveau_effectif,
                    m.statut,
                ]
            )
        else:  # GrandeurMetierValeur
            w.writerow(
                [
                    serie_detail.code,
                    m.type,
                    "",
                    m.mois or "",
                    "",
                    m.periode_type,
                    m.annee_debut,
                    m.annee_fin,
                    m.version_formule,
                    m.valeur,
                    m.niveau_effectif,
                    m.statut,
                ]
            )
    return buffer.getvalue()


@routeur.get(
    "/{code_serie}",
    response_model=None,
    status_code=status.HTTP_200_OK,
    summary="Detail d'une serie avec ses mesures",
    description=(
        "Retourne le detail d'une serie identifiee par son code naming "
        "D-32, avec ses mesures resolues sur la table-cible adequate "
        "(mesures_ressource, mesures_ressource_mensuelles, ou "
        "grandeurs_metier via v_grandeurs_metier_courantes)."
    ),
)
def detailler_serie(
    code_serie: str,
    _cle: CleApiValidee,
    session: Annotated[Session, Depends(obtenir_session)],
    from_: Annotated[
        str | None, Query(alias="from", description="Borne basse YYYY-MM ou YYYY-MM-DD")
    ] = None,
    to: Annotated[str | None, Query(description="Borne haute YYYY-MM ou YYYY-MM-DD")] = None,
    format_sortie: Annotated[
        str, Query(alias="format", description="Format de sortie : json (defaut) ou csv")
    ] = "json",
    limit: Annotated[int, Query(ge=1, le=_LIMIT_MAX_DETAIL)] = _LIMIT_DEFAUT_DETAIL,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Response:
    """Detail d'une serie avec ses mesures (3 tables-cibles, format JSON/CSV)."""
    _valider_format(format_sortie)
    from_d = _parser_borne_temporelle(from_, "from")
    to_d = _parser_borne_temporelle(to, "to")

    # Resolution serie + metadonnees enrichies (18 champs SerieListee
    # + unite_code pour SerieDetail).
    row = session.execute(
        text(
            """
            SELECT
                sm.id,
                sm.code,
                sm.libelle,
                sm.localite_id,
                l.code AS localite_code,
                l.nom AS localite_nom,
                l.pays_iso3 AS localite_iso3,
                sm.grandeur_code,
                gr.libelle AS grandeur_label,
                u.symbole AS grandeur_unit,
                sm.source_id,
                s.code AS source_code,
                s.titre AS source_label,
                s.url AS source_url,
                sm.periode_debut,
                sm.periode_fin,
                sm.granularite,
                sm.methode_collecte,
                sm.note_publique AS notes_fr,
                sm.cree_le AS created_at,
                sm.modifie_le AS updated_at,
                sm.actif,
                u.code AS unite_code
            FROM series_metadonnees sm
            JOIN localites l ON l.id = sm.localite_id
            JOIN sources s ON s.id = sm.source_id
            JOIN grandeurs_referentiel gr ON gr.code = sm.grandeur_code
            JOIN unites u ON u.id = gr.unite_id
            WHERE sm.code = :code
            """
        ),
        {"code": code_serie},
    ).first()
    if row is None:
        raise ExceptionKuma(
            code=CodeErreur.RESSOURCE_SERIE_INCONNUE,
            message=f"Serie {code_serie!r} introuvable.",
            statut_http=status.HTTP_404_NOT_FOUND,
        )

    # Resolution table-cible par granularite (source-first)
    table_cible = resolve_table_from_series_metadata(
        source_code=row.source_code,
        granularite=row.granularite,
    )

    bornes = (from_d, to_d)
    mesures: list[MesureLue]
    if table_cible == TableMesures.JOURNALIER:
        mesures = _lire_mesures_journalier(session, int(row.id), bornes, limit, offset)
    elif table_cible == TableMesures.MENSUEL_RESSOURCE:
        mesures = _lire_mesures_mensuel(session, int(row.id), bornes, limit, offset)
    elif table_cible == TableMesures.GRANDEURS_METIER:
        mesures = _lire_mesures_grandeurs_metier(session, int(row.id), bornes, limit, offset)
    else:  # TableMesures.HORAIRE - servi par l'endpoint dedie /v1/horaire
        raise ExceptionKuma(
            code=CodeErreur.RESSOURCE_INTROUVABLE,
            message=(
                "Les mesures horaires ne sont pas exposees via /v1/series ; "
                "l'acces horaire (valide ou passe-plat en repli) se fait par "
                "l'endpoint dedie /v1/horaire/{localite}/{grandeur}."
            ),
            statut_http=status.HTTP_404_NOT_FOUND,
        )

    detail = SerieDetail(
        id=int(row.id),
        code=row.code,
        libelle=row.libelle,
        localite_id=int(row.localite_id),
        localite_code=row.localite_code,
        localite_nom=row.localite_nom,
        localite_iso3=row.localite_iso3,
        grandeur_code=row.grandeur_code,
        grandeur_label=row.grandeur_label,
        grandeur_unit=row.grandeur_unit,
        source_id=int(row.source_id),
        source_code=row.source_code,
        source_label=row.source_label,
        source_url=row.source_url,
        periode_debut=row.periode_debut,
        periode_fin=row.periode_fin,
        methode_collecte=row.methode_collecte,
        notes_fr=row.notes_fr,
        created_at=row.created_at,
        updated_at=row.updated_at,
        actif=row.actif,
        unite_code=row.unite_code,
        mesures=mesures,
    )

    if format_sortie == "csv":
        return Response(content=_serialiser_csv(detail), media_type="text/csv")
    return JSONResponse(content=detail.model_dump(mode="json"))
