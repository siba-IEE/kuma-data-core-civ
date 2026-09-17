"""Couche service des workflows éditoriaux Kuma Data Core.

Premier consommateur en production des mécaniques transverses : statut
éditorial, versioning temporel et niveau de confiance A/B/C.

Sous-modules :

- ``statuts`` : machine d'état du statut éditorial des données métier.
- ``versioning`` : rotation versionnée atomique des lignes.
- ``niveaux_confiance`` : dérivation et override des niveaux A/B/C.

Toutes les exceptions levées par ces modules dérivent de
``kuma_data_core.exceptions.EditorialeError`` (racine).
"""
