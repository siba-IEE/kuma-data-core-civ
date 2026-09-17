"""Ingestion daily NASA POWER → ``mesures_ressource``.

Consomme le client ``kuma_data_core.external.nasa_power``, transforme la
réponse en lignes ``mesures_ressource`` versionnées, et fait l'INSERT
bulk via SQLAlchemy.

Le module expose deux fonctions complémentaires :

- ``ingerer_serie_daily`` : ingère **1 série** (1 paramètre
  NASA POWER) en 1 appel. Utilisé par la migration 018 pour Conakry
  GHI initial.

- ``ingerer_series_daily_groupe`` : ingère **N séries** d'une
  même localité en **1 seul appel multi-paramètres** NASA POWER.
  Cohérence transactionnelle des N grandeurs garantie (même version
  API, même release CERES SYN1deg + MERRA-2). La fonction 1-série est
  préservée pour rétrocompatibilité, la multi-séries est l'extension
  API du module.

Variable d'environnement ``KUMA_SKIP_NASA_POWER_INGESTION`` (truthy)
court-circuite l'appel réseau et retourne 0 lignes insérées (ou un
dict vide). Utile pour CI sans accès réseau et pour les tests
d'intégration qui préfèrent mocker le client httpx via ``httpx_client``.

Ingestion **live uniquement** dans cette instance : le repli offline sur
seed committé (patron de l'instance Guinée) et son canari de dérive amont
sont retirés tant qu'aucune donnée n'est versée pour la Côte d'Ivoire.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.editorial.niveaux_confiance import (
    calculer_niveau_confiance_derive,
)
from kuma_data_core.external.nasa_power import (
    SENTINELLE_VALEUR_MANQUANTE,
    fetch_daily_raw,
    parser_reponse_nasa,
)

_VARIABLE_ENV_SKIP_INGESTION: str = "KUMA_SKIP_NASA_POWER_INGESTION"
"""Variable d'environnement court-circuitant l'ingestion réseau.

Truthy values : '1', 'true', 'yes' (case-insensitive). Utile en CI ou
quand le test d'intégration mock le client httpx en aval. La fonction
retourne 0 quand activée.
"""


def _ingestion_doit_etre_skip() -> bool:
    """Lit la variable d'environnement et retourne True si elle est truthy."""
    valeur = os.environ.get(_VARIABLE_ENV_SKIP_INGESTION, "").strip().lower()
    return valeur in ("1", "true", "yes")


def _parse_cle_date_nasa(cle: str) -> date:
    """Parse une clé date NASA POWER au format ``YYYYMMDD`` en ``date``."""
    return datetime.strptime(cle, "%Y%m%d").replace(tzinfo=None).date()


def _fetch_nasa_daily_raw(
    *,
    latitude: float,
    longitude: float,
    parameters: Sequence[str],
    periode_debut: date,
    periode_fin: date,
    httpx_client: httpx.Client | None,
) -> dict[str, Any]:
    """Renvoie le payload NASA daily brut via l'appel live ``fetch_daily_raw``.

    Le parse (``parser_reponse_nasa``) est appliqué en aval par l'appelant.
    """
    return fetch_daily_raw(
        latitude=latitude,
        longitude=longitude,
        parameters=parameters,
        start=periode_debut,
        end=periode_fin,
        httpx_client=httpx_client,
    )


def ingerer_serie_daily(
    *,
    session: Session,
    code_serie: str,
    parametre_nasa: str,
    latitude: float,
    longitude: float,
    periode_debut: date,
    periode_fin: date,
    httpx_client: httpx.Client | None = None,
) -> int:
    """Ingère les mesures journalières d'une série NASA POWER dans ``mesures_ressource``.

    Args:
        session : session SQLAlchemy active. La fonction add+flush mais ne
            commit pas (responsabilité du caller).
        code_serie : code naturel de la série dans ``series_metadonnees``
            (ex. ``gin_conakry_ghi_nasa_power_2021_2025``). Doit exister
            sinon ``RuntimeError``.
        parametre_nasa : code NASA POWER à ingérer (ex.
            ``ALLSKY_SFC_SW_DWN`` pour GHI).
        latitude, longitude : coordonnées WGS84 du point de mesure.
        periode_debut, periode_fin : bornes inclusives (dates).
        httpx_client : client httpx injectable pour tests via
            ``httpx.MockTransport``. Si None, un client temporaire est
            créé par ``fetch_daily``.

    Returns:
        Nombre de lignes effectivement insérées dans ``mesures_ressource``
        (= nombre de jours retournés par NASA POWER moins les sentinelles
        ``-999.0`` filtrées).

        Retourne ``0`` si la variable d'env
        ``KUMA_SKIP_NASA_POWER_INGESTION`` est truthy (court-circuit
        sans appel réseau ni INSERT).

    Raises:
        RuntimeError : si ``code_serie`` n'existe pas dans
            ``series_metadonnees``.
        kuma_data_core.exceptions.NasaPowerError : remontée du client
            si l'appel API échoue.
    """
    if _ingestion_doit_etre_skip():
        return 0

    # Récupération du contexte série + source en une seule requête JOIN
    row = session.execute(
        text(
            """
            SELECT
                sm.id AS serie_id,
                sm.methode_collecte,
                s.fiabilite AS fiabilite_source
            FROM series_metadonnees sm
            JOIN sources s ON s.id = sm.source_id
            WHERE sm.code = :code
            """
        ),
        {"code": code_serie},
    ).first()
    if row is None:
        raise RuntimeError(
            f"Série {code_serie!r} introuvable dans series_metadonnees. "
            f"Vérifier que la migration 016 a bien ete appliquee."
        )

    serie_id: int = int(row.serie_id)
    methode_collecte: str | None = row.methode_collecte
    fiabilite_source: str | None = row.fiabilite_source

    # Toutes les mesures de la série partagent la même methode_collecte
    # et la même fiabilite_source : niveau dérivé identique pour toutes.
    niveau_derive = calculer_niveau_confiance_derive(
        methode_collecte=methode_collecte,
        fiabilite_source=fiabilite_source,
    )

    # Payload NASA POWER brut : seed committé (offline) ou appel live, puis
    # parse commun (seam offline-seed, fidélité). Client httpx injectable.
    payload = _fetch_nasa_daily_raw(
        latitude=latitude,
        longitude=longitude,
        parameters=[parametre_nasa],
        periode_debut=periode_debut,
        periode_fin=periode_fin,
        httpx_client=httpx_client,
    )
    response = parser_reponse_nasa(payload)

    # Extraction des valeurs (clé date -> valeur)
    if parametre_nasa not in response.properties.parameter:
        raise RuntimeError(
            f"Paramètre {parametre_nasa!r} absent du payload NASA POWER. "
            f"Paramètres disponibles : {list(response.properties.parameter)}"
        )
    valeurs_par_cle: dict[str, float] = response.properties.parameter[parametre_nasa]

    # Filtrage des sentinelles + construction des lignes à insérer
    lignes_a_inserer: list[dict[str, object]] = []
    for cle_date, valeur in valeurs_par_cle.items():
        if valeur == SENTINELLE_VALEUR_MANQUANTE:
            continue
        lignes_a_inserer.append(
            {
                "serie_id": serie_id,
                "instant_mesure": _parse_cle_date_nasa(cle_date),
                "valeur": float(valeur),
                "niveau_confiance_derive": niveau_derive,
                # statut, valide_du, valide_au, cree_le, modifie_le
                # laissés aux server_defaults (statut='brut',
                # valide_du=now(), valide_au=NULL, etc.)
            }
        )

    if not lignes_a_inserer:
        return 0

    # Bulk INSERT en SQL brut pour exploiter les server_defaults
    session.execute(
        text(
            """
            INSERT INTO mesures_ressource
                (serie_id, instant_mesure, valeur, niveau_confiance_derive)
            VALUES
                (:serie_id, :instant_mesure, :valeur, :niveau_confiance_derive)
            """
        ),
        lignes_a_inserer,
    )
    session.flush()
    return len(lignes_a_inserer)


def ingerer_series_daily_groupe(
    *,
    session: Session,
    codes_series: Sequence[str],
    mapping_grandeur_parametre_nasa: dict[str, str],
    latitude: float,
    longitude: float,
    periode_debut: date,
    periode_fin: date,
    httpx_client: httpx.Client | None = None,
) -> dict[str, int]:
    """Ingère N séries d'une même localité en 1 appel NASA POWER multi-paramètres.

    Élargissement Conakry à toutes grandeurs brutes.
    Économie réseau (1 appel pour N grandeurs) + cohérence transactionnelle
    (même version API, même release CERES SYN1deg + MERRA-2 pour les N
    valeurs ingérées).

    Args:
        session : session SQLAlchemy active. La fonction add+flush mais ne
            commit pas (responsabilité du caller).
        codes_series : codes naturels des séries dans
            ``series_metadonnees`` (ex. ``['gin_conakry_dni_nasa_power_2021_2025',
            'gin_conakry_dhi_*', 'gin_conakry_t2m_*', 'gin_conakry_rh2m_*']``).
            Toutes doivent exister sinon ``RuntimeError``. Toutes doivent
            partager la même localité (latitude/longitude fournies en
            arguments, pas re-déduites de la série).
        mapping_grandeur_parametre_nasa : pour chaque grandeur_code d'une
            série, le paramètre NASA POWER correspondant. Ex.
            ``{'dni': 'ALLSKY_SFC_SW_DNI', 'dhi': 'ALLSKY_SFC_SW_DIFF',
            't2m': 'T2M', 'rh2m': 'RH2M'}``. Chaque grandeur_code des
            séries en argument doit avoir une entrée dans le mapping.
        latitude, longitude : coordonnées WGS84 du point unique de mesure
            (commun aux N séries de la même localité).
        periode_debut, periode_fin : bornes inclusives (dates).
        httpx_client : client httpx injectable pour tests via
            ``httpx.MockTransport``. Si None, un client temporaire est
            créé par ``fetch_daily``.

    Returns:
        dict[str, int] : pour chaque code de série en entrée, le nombre de
        lignes effectivement insérées dans ``mesures_ressource`` (= nombre
        de jours retournés moins sentinelles ``-999.0`` filtrées).

        Retourne un dict vide ``{}`` si la variable d'env
        ``KUMA_SKIP_NASA_POWER_INGESTION`` est truthy (court-circuit
        sans appel réseau ni INSERT).

    Raises:
        RuntimeError : si une série de ``codes_series`` n'existe pas, ou
            si une grandeur_code de série n'a pas d'entrée dans
            ``mapping_grandeur_parametre_nasa``, ou si un paramètre
            attendu est absent de la réponse NASA POWER.
        kuma_data_core.exceptions.NasaPowerError : remontée du client
            si l'appel API échoue.
    """
    if _ingestion_doit_etre_skip():
        return {}

    if not codes_series:
        return {}

    # Récupération du contexte série + source + grandeur pour les N séries
    # en une seule requête JOIN.
    rows = session.execute(
        text(
            """
            SELECT
                sm.id AS serie_id,
                sm.code AS code_serie,
                sm.grandeur_code,
                sm.methode_collecte,
                s.fiabilite AS fiabilite_source
            FROM series_metadonnees sm
            JOIN sources s ON s.id = sm.source_id
            WHERE sm.code = ANY(:codes)
            """
        ),
        {"codes": list(codes_series)},
    ).all()

    if len(rows) != len(codes_series):
        codes_trouves = {r.code_serie for r in rows}
        codes_manquants = set(codes_series) - codes_trouves
        raise RuntimeError(
            f"Séries introuvables dans series_metadonnees : "
            f"{sorted(codes_manquants)}. Vérifier le seed (migration 019)."
        )

    # Vérification que chaque grandeur_code a son paramètre NASA POWER mappé.
    grandeurs_manquantes = {r.grandeur_code for r in rows} - set(mapping_grandeur_parametre_nasa)
    if grandeurs_manquantes:
        raise RuntimeError(
            f"Grandeurs sans paramètre NASA POWER mappé : "
            f"{sorted(grandeurs_manquantes)}. Vérifier "
            f"mapping_grandeur_parametre_nasa."
        )

    # Construction du contexte par série (id, grandeur, niveau dérivé).
    # Toutes les séries partagent la même methode_collecte / fiabilite_source
    # en pratique (toutes NASA POWER modele_satellitaire), mais on calcule
    # le niveau série par série pour ne pas l'assumer en dur.
    contexte_par_grandeur: dict[str, dict[str, object]] = {}
    for row in rows:
        niveau_derive = calculer_niveau_confiance_derive(
            methode_collecte=row.methode_collecte,
            fiabilite_source=row.fiabilite_source,
        )
        contexte_par_grandeur[row.grandeur_code] = {
            "serie_id": int(row.serie_id),
            "code_serie": str(row.code_serie),
            "niveau_derive": niveau_derive,
        }

    # 1 seul appel NASA POWER avec tous les paramètres demandés.
    parametres_demandes = sorted(
        {mapping_grandeur_parametre_nasa[g] for g in contexte_par_grandeur}
    )
    payload = _fetch_nasa_daily_raw(
        latitude=latitude,
        longitude=longitude,
        parameters=parametres_demandes,
        periode_debut=periode_debut,
        periode_fin=periode_fin,
        httpx_client=httpx_client,
    )
    response = parser_reponse_nasa(payload)

    # Pour chaque grandeur, extraction + filtrage sentinelles + lignes prêtes.
    lignes_a_inserer: list[dict[str, object]] = []
    decompte_par_serie: dict[str, int] = {
        ctx["code_serie"]: 0  # type: ignore[misc]
        for ctx in contexte_par_grandeur.values()
    }
    for grandeur_code, ctx in contexte_par_grandeur.items():
        parametre_nasa = mapping_grandeur_parametre_nasa[grandeur_code]
        if parametre_nasa not in response.properties.parameter:
            raise RuntimeError(
                f"Paramètre {parametre_nasa!r} (grandeur {grandeur_code!r}) "
                f"absent du payload NASA POWER. Paramètres disponibles : "
                f"{list(response.properties.parameter)}"
            )
        valeurs_par_cle: dict[str, float] = response.properties.parameter[parametre_nasa]
        code_serie = ctx["code_serie"]
        for cle_date, valeur in valeurs_par_cle.items():
            if valeur == SENTINELLE_VALEUR_MANQUANTE:
                continue
            lignes_a_inserer.append(
                {
                    "serie_id": ctx["serie_id"],
                    "instant_mesure": _parse_cle_date_nasa(cle_date),
                    "valeur": float(valeur),
                    "niveau_confiance_derive": ctx["niveau_derive"],
                }
            )
            decompte_par_serie[code_serie] += 1  # type: ignore[index]

    if not lignes_a_inserer:
        return decompte_par_serie

    session.execute(
        text(
            """
            INSERT INTO mesures_ressource
                (serie_id, instant_mesure, valeur, niveau_confiance_derive)
            VALUES
                (:serie_id, :instant_mesure, :valeur, :niveau_confiance_derive)
            """
        ),
        lignes_a_inserer,
    )
    session.flush()
    return decompte_par_serie
