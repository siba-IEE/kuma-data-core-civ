"""Cycle de vie des clés API self-service (ADR-0003, D3 / WP6).

Toute la logique vit ici, le routeur (``api/v1/cles.py``) ne fait que
l'orchestration HTTP. Principes :

- La clé complète (``kuma_`` + 43 caractères URL-safe, 256 bits
  d'entropie) n'existe qu'au moment de l'émission : elle est renvoyée
  une seule fois au demandeur, seule son empreinte SHA-256 est stockée.
- Le préfixe (``kuma_`` + 8 premiers caractères) est l'identifiant
  public : affichable, loggable, suffisant pour révoquer.
- L'émission est la seule surface d'écriture publique du serveur (D2) :
  elle est bornée par IP (``LIMITE_EMISSIONS_PAR_IP_24H``).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kuma_data_core.db.meta import CleApi

PREFIXE_CLE = "kuma_"
_LONGUEUR_PREFIXE_PUBLIC = len(PREFIXE_CLE) + 8

# Émissions maximales par adresse IP sur 24 h glissantes. Volontairement
# bas : un développeur légitime n'a besoin que d'une clé ; la limite ne
# gêne que les robots.
LIMITE_EMISSIONS_PAR_IP_24H = 3


def generer_cle() -> tuple[str, str, str]:
    """Génère une clé neuve : ``(cle_complete, prefixe, empreinte)``.

    La clé complète ne doit jamais être persistée ni loggée : elle
    transite vers le demandeur puis n'existe plus que chez lui.
    """
    cle = f"{PREFIXE_CLE}{secrets.token_urlsafe(32)}"
    return cle, cle[:_LONGUEUR_PREFIXE_PUBLIC], hacher_cle(cle)


def hacher_cle(cle: str) -> str:
    """Empreinte SHA-256 (hex) d'une clé - la seule forme stockée."""
    return hashlib.sha256(cle.encode("utf-8")).hexdigest()


def nombre_emissions_recentes(session: Session, adresse_ip: str) -> int:
    """Nombre de clés émises par cette IP sur les dernières 24 h."""
    resultat = session.execute(
        select(func.count())
        .select_from(CleApi)
        .where(
            CleApi.adresse_ip_creation == adresse_ip,
            # make_interval positionnel (years, months, weeks, days, hours) :
            # les 4 premiers à 0, hours=24. Les kwargs Python ne sont pas
            # traduits en named args PostgreSQL par SQLAlchemy, d'où le positionnel.
            CleApi.cree_le > func.now() - func.make_interval(0, 0, 0, 0, 24),
        )
    ).scalar()
    return int(resultat or 0)


def creer_cle(
    session: Session,
    email: str,
    usage_prevu: str | None,
    adresse_ip: str,
) -> tuple[str, CleApi]:
    """Émet une clé : retourne ``(cle_complete, enregistrement)``.

    La limite d'émission par IP est vérifiée par l'appelant (le routeur
    la traduit en 429) : cette fonction ne fait qu'émettre.
    """
    cle, prefixe, empreinte = generer_cle()
    enregistrement = CleApi(
        cle_hash=empreinte,
        prefixe=prefixe,
        email=email,
        usage_prevu=usage_prevu,
        adresse_ip_creation=adresse_ip,
    )
    session.add(enregistrement)
    session.commit()
    session.refresh(enregistrement)
    return cle, enregistrement


def quota_si_active(session: Session, cle: str) -> int | None:
    """Quota journalier si l'empreinte de ``cle`` est une clé active.

    ``None`` = clé inconnue ou révoquée (l'appelant refuse). Le quota
    retourné alimente le rate limiting (WP7).
    """
    resultat = session.execute(
        select(CleApi.quota_journalier).where(
            CleApi.cle_hash == hacher_cle(cle),
            CleApi.actif.is_(True),
        )
    ).scalar()
    return int(resultat) if resultat is not None else None


def revoquer_par_prefixe(session: Session, prefixe: str) -> int:
    """Révoque (soft delete) toutes les clés actives portant ce préfixe.

    Retourne le nombre de clés révoquées (0 si préfixe inconnu ou déjà
    révoqué - l'appelant décide du 404).
    """
    cles = (
        session.execute(select(CleApi).where(CleApi.prefixe == prefixe, CleApi.actif.is_(True)))
        .scalars()
        .all()
    )
    for cle in cles:
        cle.actif = False
        cle.desactive_le = datetime.now(tz=UTC)
    session.commit()
    return len(cles)
