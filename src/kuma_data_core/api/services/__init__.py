"""Services internes de la couche API.

Fonctions utilitaires consommees par les routeurs FastAPI sous
``src/kuma_data_core/api/v1/``. Pas de couplage SQLAlchemy direct :
les services API restent au niveau « logique métier de l'API »
(résolution de tables, formatage de réponses, etc.) et délèguent les
accès DB aux dépendances FastAPI standard.
"""
