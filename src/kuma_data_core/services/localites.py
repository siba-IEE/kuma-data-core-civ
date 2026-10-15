"""Helper utilitaire : lecture des coordonnees des localites Kuma.

Source de verite : table ``localites`` (referentiel canonique seede
par migration). Le present module evite la duplication de coordonnees
hardcodees dans les modules applicatifs (API, services) en exposant un
accesseur cache memoire au premier appel.

Pattern : ``@lru_cache(maxsize=1)`` sur la fonction sans parametre
:func:`_charger_coordonnees`. Le premier appel ouvre une session SQL
via la factory existante (``get_session_factory``), lit l'ensemble des
``(code, latitude, longitude)`` pour toutes les localites actives, et
construit un dict en cache. Les appels suivants sont en O(1) sans
acces DB.

Robustesse : si la base devient indisponible apres le premier appel,
le cache continue de servir les coordonnees deja chargees (pas
d'invalidation automatique). Pour forcer un rechargement (par exemple
post-update DB), appeler ``_charger_coordonnees.cache_clear()`` puis
``coordonnees_localite(...)``.

Le module est utilitaire (pas une grandeur F2 paramétrable) - le
pattern fonctions pures + orchestrateur I/O ne s'applique pas.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import text

from kuma_data_core.db.session import get_session_factory


@lru_cache(maxsize=1)
def _charger_coordonnees() -> dict[str, tuple[float, float]]:
    """Charge toutes les coordonnees des localites depuis la table ``localites``.

    Lit ``(code, latitude, longitude)`` pour les localites actives
    ayant des coordonnees non NULL. Retourne un dict
    ``{code: (latitude, longitude)}``.

    Cache memoire de premier appel via ``@lru_cache(maxsize=1)``.
    """
    factory = get_session_factory()
    with factory() as session:
        rows = session.execute(
            text(
                "SELECT code, latitude, longitude FROM localites "
                "WHERE actif = TRUE "
                "AND latitude IS NOT NULL AND longitude IS NOT NULL"
            )
        ).all()
    return {row.code: (float(row.latitude), float(row.longitude)) for row in rows}


def coordonnees_localite(code: str) -> tuple[float, float]:
    """Renvoie le tuple ``(latitude, longitude)`` pour une localite Kuma.

    Le helper accepte n'importe quel code actif de la table
    ``localites`` portant des coordonnees, quel que soit son pays :
    aucune liste de villes n'est codee.

    Args:
        code : code naturel complet de la localite (``<pays>_<slug>``).

    Returns:
        Tuple ``(latitude_deg, longitude_deg)`` en degres decimaux WGS84.

    Raises:
        KeyError : si ``code`` n'est pas present dans la table
            ``localites``, est inactif ou n'a pas de coordonnees
            (racine continentale par exemple). L'appelant traduit ce
            cas en erreur explicite (``/v1/horaire`` : 404).
    """
    return _charger_coordonnees()[code]
