"""Endpoint ``GET /api/v1/calage/{localite}/{grandeur}``.

Sert le référentiel de calage satellite/sol d'une station de
référence (ADR-0004) : biais saisonniers mesurés, facteur dérivé
k = 1/(1+biais), provenance et portée de transport. Donnée
éditoriale de l'édition, lue telle quelle - aucun calcul amont,
conforme au profil édition figée (D6).

Codes localité complets (``gin_kankan``), alignés sur ``/v1/series``
et ``/v1/localites``. 404 ``RESSOURCE_INTROUVABLE`` si aucun
référentiel actif n'existe pour le couple.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.api.codes_erreur import CodeErreur
from kuma_data_core.api.dependencies import CleApiValidee
from kuma_data_core.api.erreurs import ExceptionKuma
from kuma_data_core.api.v1.schemas.calage import (
    ReferentielListe,
    ReponseCalage,
    ReponseCalageListe,
    SaisonCalage,
)
from kuma_data_core.db.session import obtenir_session

routeur = APIRouter(prefix="/calage", tags=["calage"])


@routeur.get(
    "",
    response_model=ReponseCalageListe,
    status_code=status.HTTP_200_OK,
    summary="Listing des referentiels de calage publies",
)
def lister_referentiels_calage(
    _cle: CleApiValidee,
    session: Annotated[Session, Depends(obtenir_session)],
) -> ReponseCalageListe:
    """Retourne les referentiels de calage publies, avec leur domaine.

    Une entree par referentiel (code) : station, grandeur, version,
    serie sol de fondation et localites couvertes. C'est l'endpoint de
    DECOUVERTE des consommateurs d'etude (genericite pays, residu 3) :
    ajouter une station = publier son referentiel, aucun changement
    cote consommateurs.
    """
    rows = session.execute(
        text(
            """
            SELECT rc.code, l.code AS localite, rc.grandeur_code,
                   MIN(rc.version) AS version, MIN(rc.serie_sol) AS serie_sol
            FROM referentiels_calage rc
            JOIN localites l ON l.id = rc.localite_id
            WHERE rc.actif = TRUE
            GROUP BY rc.code, l.code, rc.grandeur_code
            ORDER BY rc.code
            """
        )
    ).all()
    couvertures = session.execute(
        text(
            """
            SELECT cc.referentiel_code, l.code
            FROM calage_couverture cc
            JOIN localites l ON l.id = cc.localite_id
            WHERE cc.actif = TRUE
            ORDER BY cc.referentiel_code, l.code
            """
        )
    ).all()
    par_referentiel: dict[str, list[str]] = {}
    for c in couvertures:
        par_referentiel.setdefault(str(c.referentiel_code), []).append(str(c.code))

    items = [
        ReferentielListe(
            code=str(r.code),
            localite=str(r.localite),
            grandeur=str(r.grandeur_code),
            version=str(r.version),
            serie_sol=str(r.serie_sol),
            localites_couvertes=par_referentiel.get(str(r.code), []),
        )
        for r in rows
    ]
    return ReponseCalageListe(items=items, total=len(items))


@routeur.get(
    "/{localite}/{grandeur}",
    response_model=ReponseCalage,
    status_code=status.HTTP_200_OK,
    summary="Referentiel de calage satellite/sol d'une station de reference",
)
def referentiel_calage(
    localite: str,
    grandeur: str,
    _cle: CleApiValidee,
    session: Annotated[Session, Depends(obtenir_session)],
) -> ReponseCalage:
    """Retourne les biais saisonniers publiés pour (station, grandeur).

    Chaque saison porte le biais mesuré (satellite moins sol, relatif)
    et le facteur dérivé ``k = 1 / (1 + biais)``. La provenance
    (note de calage, script reproductible, série sol de référence) et
    la portée de transport accompagnent les chiffres : jamais un
    nombre nu.
    """
    rows = session.execute(
        text(
            """
            SELECT rc.code, rc.saison, rc.mois, rc.biais, rc.provenance,
                   rc.portee, rc.version, rc.serie_sol
            FROM referentiels_calage rc
            JOIN localites l ON l.id = rc.localite_id
            WHERE l.code = :localite
              AND rc.grandeur_code = :grandeur
              AND rc.actif = TRUE
            ORDER BY rc.id
            """
        ),
        {"localite": localite, "grandeur": grandeur},
    ).all()
    if not rows:
        raise ExceptionKuma(
            code=CodeErreur.RESSOURCE_INTROUVABLE,
            message=("Aucun referentiel de calage publie pour cette station et cette grandeur."),
            statut_http=status.HTTP_404_NOT_FOUND,
        )

    premiere = rows[0]
    couverture = session.execute(
        text(
            """
            SELECT l.code, cc.justification
            FROM calage_couverture cc
            JOIN localites l ON l.id = cc.localite_id
            WHERE cc.referentiel_code = :code
              AND cc.actif = TRUE
            ORDER BY l.code
            """
        ),
        {"code": str(premiere.code)},
    ).all()

    return ReponseCalage(
        localite=localite,
        grandeur=grandeur,
        code=str(premiere.code),
        version=str(premiere.version),
        saisons=[
            SaisonCalage(
                nom=str(row.saison),
                mois=[int(m) for m in row.mois],
                biais=float(row.biais),
                k=1.0 / (1.0 + float(row.biais)),
            )
            for row in rows
        ],
        provenance=str(premiere.provenance),
        portee=str(premiere.portee),
        localites_couvertes=[str(c.code) for c in couverture],
        justification_couverture=str(couverture[0].justification) if couverture else None,
        serie_sol=str(premiere.serie_sol),
    )
