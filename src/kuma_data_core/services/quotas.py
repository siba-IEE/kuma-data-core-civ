"""Quotas journaliers des clés self-service via Redis (ADR-0003, WP7).

Compteur à fenêtre fixe : une clé Redis ``quota:<empreinte>:<AAAA-MM-JJ>``
est incrémentée à chaque requête authentifiée par une clé self-service,
avec une expiration de 48 h posée au premier incrément (large : la
fenêtre réelle est le jour calendaire, l'expiration ne sert qu'au
nettoyage). Le quota comparé est le ``quota_journalier`` porté par la
ligne ``cles_api`` (WP6).

Le compteur est indexé sur l'**empreinte** de la clé, jamais la clé en
clair : Redis ne détient aucun secret.

**Fail-open assumé** : si Redis est injoignable, la requête passe sans
comptage. Une panne du cache ne doit pas rendre les données publiques
indisponibles - la disponibilité prime sur la stricte comptabilité,
et les clés d'environnement ne passent de toute façon jamais ici.
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from typing import TYPE_CHECKING, cast

from kuma_data_core.core.config import get_settings
from kuma_data_core.core.logging import obtenir_logger

if TYPE_CHECKING:
    import redis

# Expiration des compteurs : 48 h, purement du nettoyage (la fenêtre
# de comptage est le jour calendaire UTC porté par le nom de la clé).
_EXPIRATION_COMPTEUR_SECONDES = 48 * 3600


@lru_cache(maxsize=4)
def _client_pour(hote: str, port: int, mot_de_passe: str | None) -> redis.Redis:
    """Client Redis memoizé par destination (connexions poolées)."""
    import redis

    return redis.Redis(
        host=hote,
        port=port,
        password=mot_de_passe,
        socket_connect_timeout=2,
        socket_timeout=2,
        decode_responses=True,
    )


def obtenir_client() -> redis.Redis:
    """Client Redis selon la configuration courante."""
    settings = get_settings()
    mot_de_passe = (
        settings.redis_password.get_secret_value() if settings.redis_password is not None else None
    )
    return _client_pour(settings.redis_host, settings.redis_port, mot_de_passe)


def consommer_quota(empreinte: str, quota_journalier: int) -> bool:
    """Consomme une requête du quota du jour ; vraie si encore dans le quota.

    Fenêtre fixe sur le jour calendaire UTC. Fail-open : toute erreur
    Redis vaut ``True`` (requête servie, non comptée) et un log
    d'avertissement - jamais une 5xx pour un compteur.
    """
    jour = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    cle_compteur = f"quota:{empreinte}:{jour}"
    try:
        client = obtenir_client()
        # Le client sync renvoie int ; le type redis-py unit sync/async.
        compte = cast(int, client.incr(cle_compteur))
        if compte == 1:
            client.expire(cle_compteur, _EXPIRATION_COMPTEUR_SECONDES)
        return compte <= quota_journalier
    except Exception:
        obtenir_logger("kuma.api.quotas").warning(
            "quota_redis_injoignable_fail_open", compteur=cle_compteur
        )
        return True
