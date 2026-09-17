"""Catalogue des codes d'erreur stables exposés par l'API Kuma.

Ces codes sont des identifiants techniques destinés aux outils
consommateurs de l'API (Kuma Solar Data Bridge, futurs outils Excel /
Streamlit, etc.). Ils sont **stables** : un code publié ne change plus,
ne disparaît plus. Pour faire évoluer la sémantique, on crée un nouveau
code et on déprécie l'ancien.

Convention de nommage
---------------------
``UPPER_SNAKE_CASE`` français, regroupé par préfixe métier :

* ``AUTH_*``           - authentification, autorisation
* ``VALIDATION_*``     - validation des entrées (Pydantic, contraintes)
* ``RESSOURCE_*``      - état des ressources (existence, conflits)
* ``GRANDEUR_F2_*``    - grandeurs F2 paramétrables
* ``PASSE_PLAT_*``     - passe-plat horaire
* ``PLAGE_*``          - plages temporelles non disponibles
* ``INFRASTRUCTURE_*`` - dépendances externes (base, cache)
* ``SERVEUR_*``        - erreurs internes non classifiées

Périmètre
---------
Seuls ``AUTH_*``, ``INFRASTRUCTURE_*`` et ``SERVEUR_ERREUR_INTERNE``
sont effectivement utilisés. Les autres sont déclarés en avance pour
préfigurer l'usage à venir et stabiliser le contrat dès maintenant.
"""

from __future__ import annotations

from enum import StrEnum


class CodeErreur(StrEnum):
    """Codes d'erreur stables de l'API Kuma."""

    # Authentification (4xx)
    AUTH_HEADER_MANQUANT = "AUTH_HEADER_MANQUANT"
    AUTH_FORMAT_INVALIDE = "AUTH_FORMAT_INVALIDE"
    AUTH_CLE_INVALIDE = "AUTH_CLE_INVALIDE"

    # Validation (4xx)
    VALIDATION_CHAMP_MANQUANT = "VALIDATION_CHAMP_MANQUANT"
    VALIDATION_VALEUR_INVALIDE = "VALIDATION_VALEUR_INVALIDE"
    VALIDATION_FORMAT_DATE_INVALIDE = "VALIDATION_FORMAT_DATE_INVALIDE"
    VALIDATION_FORMAT_NON_SUPPORTE = "VALIDATION_FORMAT_NON_SUPPORTE"
    VALIDATION_LIMIT_HORS_BORNES = "VALIDATION_LIMIT_HORS_BORNES"

    # Ressources (4xx)
    RESSOURCE_INTROUVABLE = "RESSOURCE_INTROUVABLE"
    CALAGE_INDISPONIBLE = "CALAGE_INDISPONIBLE"
    RESSOURCE_SERIE_INCONNUE = "RESSOURCE_SERIE_INCONNUE"
    RESSOURCE_LOCALITE_INCONNUE = "RESSOURCE_LOCALITE_INCONNUE"

    # Grandeurs F2 paramétrables (4xx)
    GRANDEUR_F2_INCONNUE = "GRANDEUR_F2_INCONNUE"
    INCOMPATIBILITE_SOURCE_GRANDEUR = "INCOMPATIBILITE_SOURCE_GRANDEUR"

    # Passe-plat horaire (4xx + 5xx)
    PLAGE_TEMPORELLE_NON_DISPONIBLE = "PLAGE_TEMPORELLE_NON_DISPONIBLE"
    PASSE_PLAT_INDISPONIBLE = "PASSE_PLAT_INDISPONIBLE"

    # Clés API self-service (4xx)
    CLES_EMISSION_NON_ACTIVEE = "CLES_EMISSION_NON_ACTIVEE"
    CLES_LIMITE_EMISSION_ATTEINTE = "CLES_LIMITE_EMISSION_ATTEINTE"
    CLES_QUOTA_JOURNALIER_DEPASSE = "CLES_QUOTA_JOURNALIER_DEPASSE"

    # Serveur (5xx)
    INFRASTRUCTURE_BASE_INDISPONIBLE = "INFRASTRUCTURE_BASE_INDISPONIBLE"
    INFRASTRUCTURE_CACHE_INDISPONIBLE = "INFRASTRUCTURE_CACHE_INDISPONIBLE"
    SERVEUR_ERREUR_INTERNE = "SERVEUR_ERREUR_INTERNE"
