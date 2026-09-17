"""Clients d'API externes utilisés par Kuma Data Core.

Premier client : ``nasa_power``.

Périmètre attendu :
- ``nasa_power`` : client de l'API NASA POWER (substrat solaire + climat
  de base)
- ``ecmwf_era5`` (à venir) : client du Climate Data Store Copernicus
  pour ERA5 (cross-check qualité sémantique)

Distinction conceptuelle avec ``ingestion/`` : ``external/`` expose des
clients HTTP typés retournant des objets pydantic ; ``ingestion/``
consomme ces clients et persiste les résultats dans les tables métier
(``mesures_ressource`` et suivantes).
"""
