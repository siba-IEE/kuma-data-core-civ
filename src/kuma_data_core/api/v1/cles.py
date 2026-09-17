"""Endpoints ``/v1/cles`` - émission self-service et révocation (WP6).

L'émission est **non authentifiée** (c'est l'inscription) et constitue
la seule surface d'écriture publique du serveur (ADR-0003, D2) : elle
est bornée par adresse IP. La révocation est réservée à la clé
administrateur.

Sur un déploiement sans base de service (``META_DB`` absente, régime
local), l'émission renvoie 404 ``CLES_EMISSION_NON_ACTIVEE`` : le
self-service est une capacité du serveur public, pas du poste de
développement.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from sqlalchemy.orm import Session

from kuma_data_core.api.codes_erreur import CodeErreur
from kuma_data_core.api.dependencies import CleAdminValidee
from kuma_data_core.api.erreurs import ExceptionKuma
from kuma_data_core.api.v1.schemas.cles import (
    DemandeCle,
    ReponseCleCreee,
    ReponseRevocation,
)
from kuma_data_core.core.config import get_settings
from kuma_data_core.services.cles import (
    LIMITE_EMISSIONS_PAR_IP_24H,
    creer_cle,
    nombre_emissions_recentes,
    revoquer_par_prefixe,
)

routeur = APIRouter(prefix="/cles", tags=["cles"])


def _session_meta() -> Session:
    """Session sur la base de service, ou 404 si elle n'existe pas ici."""
    from kuma_data_core.db.session import get_engine_meta

    if get_settings().meta_db is None:
        raise ExceptionKuma(
            code=CodeErreur.CLES_EMISSION_NON_ACTIVEE,
            message="L'emission self-service de cles n'est pas activee sur ce deploiement.",
            statut_http=status.HTTP_404_NOT_FOUND,
        )
    return Session(get_engine_meta())


def _adresse_ip(request: Request) -> str:
    """Adresse du client pour la limite d'émission par IP (ADR-0003 D2).

    Derrière un reverse proxy de confiance (Caddy, WP8), l'adresse réelle
    du client vit dans ``X-Forwarded-For`` ; ``request.client.host`` est
    alors l'IP du proxy (une seule, la limite s'effondrerait). On lit donc
    la **dernière** entrée de la chaîne - celle ajoutée par notre proxy,
    la seule non falsifiable (un client peut préfixer des IP fictives,
    jamais en ajouter après le proxy). Sans proxy de confiance déclaré,
    l'en-tête est ignoré : un client le forgerait pour contourner la
    limite.
    """
    if get_settings().derriere_proxy_confiance:
        transmis = request.headers.get("x-forwarded-for")
        if transmis:
            maillons = [m.strip() for m in transmis.split(",") if m.strip()]
            if maillons:
                return maillons[-1]
    return request.client.host if request.client is not None else "inconnue"


@routeur.post(
    "",
    response_model=ReponseCleCreee,
    status_code=status.HTTP_201_CREATED,
    summary="Émettre une clé API (self-service)",
    description=(
        "Inscription légère : une adresse de contact suffit, la clé est "
        "émise immédiatement. Elle n'est montrée qu'une seule fois - le "
        "serveur n'en conserve que l'empreinte. Émission bornée par "
        "adresse IP."
    ),
)
def emettre_cle(demande: DemandeCle, request: Request) -> ReponseCleCreee:
    """Émet une clé self-service (ADR-0003, D3)."""
    adresse_ip = _adresse_ip(request)
    with _session_meta() as session:
        if nombre_emissions_recentes(session, adresse_ip) >= LIMITE_EMISSIONS_PAR_IP_24H:
            raise ExceptionKuma(
                code=CodeErreur.CLES_LIMITE_EMISSION_ATTEINTE,
                message=(
                    "Limite d'emission de cles atteinte pour cette adresse (24 h glissantes)."
                ),
                statut_http=status.HTTP_429_TOO_MANY_REQUESTS,
                details={"limite_24h": LIMITE_EMISSIONS_PAR_IP_24H},
            )
        cle, enregistrement = creer_cle(
            session,
            email=demande.email,
            usage_prevu=demande.usage_prevu,
            adresse_ip=adresse_ip,
        )
        return ReponseCleCreee(
            cle=cle,
            prefixe=enregistrement.prefixe,
            quota_journalier=enregistrement.quota_journalier,
        )


@routeur.delete(
    "/{prefixe}",
    response_model=ReponseRevocation,
    status_code=status.HTTP_200_OK,
    summary="Révoquer une clé par son préfixe (administrateur)",
)
def revoquer_cle(prefixe: str, _admin: CleAdminValidee) -> ReponseRevocation:
    """Révoque toutes les clés actives portant ce préfixe (soft delete)."""
    with _session_meta() as session:
        revoquees = revoquer_par_prefixe(session, prefixe)
    if revoquees == 0:
        raise ExceptionKuma(
            code=CodeErreur.RESSOURCE_INTROUVABLE,
            message="Aucune cle active ne porte ce prefixe.",
            statut_http=status.HTTP_404_NOT_FOUND,
        )
    return ReponseRevocation(prefixe=prefixe, cles_revoquees=revoquees)
