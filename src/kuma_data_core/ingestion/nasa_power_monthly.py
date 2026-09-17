"""Ingestion monthly NASA POWER -> ``mesures_ressource_mensuelles``.

Pendant mensuel de ``nasa_power_daily.py``. Consomme le
client ``kuma_data_core.external.nasa_power.fetch_monthly``,
transforme la réponse en lignes ``mesures_ressource_mensuelles``
versionnées, et fait l'INSERT bulk via SQLAlchemy.

Cas d'usage :

- Extension temporelle NASA POWER 1991-2020 pour les 6 villes
  guinéennes pilotes : 30 ans x 12 mois x 6 villes = 2 160 valeurs
  ingérées dans la nouvelle table dédiée.

La fonction principale ``ingerer_serie_monthly`` parse les clés de la
réponse au format ``YYYYMM`` et filtre les clés non-mensuelles
(``YYYY13`` représentant la moyenne annuelle quand elle est présente).

Variable d'environnement ``KUMA_SKIP_NASA_POWER_INGESTION`` (truthy)
court-circuite l'appel réseau et retourne 0 lignes insérées, comme
pour la fonction journalière. Utile pour CI sans accès réseau et tests
d'intégration qui préfèrent mocker le client httpx.

Ingestion **live uniquement** dans cette instance : le repli offline sur
seed committé et son canari de dérive amont (patron de l'instance Guinée)
sont retirés tant qu'aucune donnée n'est versée pour la Côte d'Ivoire.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.editorial.niveaux_confiance import (
    calculer_niveau_confiance_derive,
)
from kuma_data_core.external.nasa_power import (
    SENTINELLE_VALEUR_MANQUANTE,
    fetch_monthly_raw,
    parser_reponse_nasa,
)

_VARIABLE_ENV_SKIP_INGESTION: str = "KUMA_SKIP_NASA_POWER_INGESTION"
"""Variable d'environnement court-circuitant l'ingestion réseau.

Truthy values : '1', 'true', 'yes' (case-insensitive). Partage la même
variable que le module daily pour cohérence opérationnelle CI : un
seul switch suffit à désactiver les deux ingestions NASA POWER.
"""


def _ingestion_doit_etre_skip() -> bool:
    """Lit la variable d'environnement et retourne True si elle est truthy."""
    valeur = os.environ.get(_VARIABLE_ENV_SKIP_INGESTION, "").strip().lower()
    return valeur in ("1", "true", "yes")


def _parse_cle_yyyymm(cle: str) -> tuple[int, int] | None:
    """Parse une clé au format ``YYYYMM``.

    Retourne ``(annee, mois)`` si la clé est mensuelle valide, ``None``
    sinon (typiquement pour ``YYYY13`` représentant la moyenne annuelle
    que NASA POWER inclut parfois dans la réponse monthly).
    """
    if len(cle) != 6 or not cle.isdigit():
        return None
    annee = int(cle[:4])
    mois = int(cle[4:])
    if mois < 1 or mois > 12:
        return None
    return annee, mois


def _fetch_nasa_monthly_raw(
    *,
    latitude: float,
    longitude: float,
    parameters: Sequence[str],
    annee_debut: int,
    annee_fin: int,
    httpx_client: httpx.Client | None,
) -> dict[str, Any]:
    """Renvoie le payload NASA monthly brut via l'appel live ``fetch_monthly_raw``.

    Le parse (``parser_reponse_nasa``) est appliqué en aval par l'appelant.
    """
    return fetch_monthly_raw(
        latitude=latitude,
        longitude=longitude,
        parameters=parameters,
        annee_debut=annee_debut,
        annee_fin=annee_fin,
        httpx_client=httpx_client,
    )


def ingerer_serie_monthly(
    *,
    session: Session,
    code_serie: str,
    parametre_nasa: str,
    latitude: float,
    longitude: float,
    annee_debut: int,
    annee_fin: int,
    httpx_client: httpx.Client | None = None,
) -> int:
    """Ingère les mesures mensuelles d'une série NASA POWER dans ``mesures_ressource_mensuelles``.

    Args:
        session : session SQLAlchemy active. La fonction add+flush mais
            ne commit pas (responsabilité du caller).
        code_serie : code naturel de la série dans ``series_metadonnees``
            (ex. ``gin_conakry_ghi_power_1991_2020``). Doit exister
            sinon ``RuntimeError``.
        parametre_nasa : code NASA POWER à ingérer (ex.
            ``ALLSKY_SFC_SW_DWN`` pour GHI).
        latitude, longitude : coordonnées WGS84 du point de mesure.
        annee_debut, annee_fin : bornes inclusives (années, ex.
            ``1991`` / ``2020``).
        httpx_client : client httpx injectable pour tests via
            ``httpx.MockTransport``. Si None, un client temporaire est
            créé par ``fetch_monthly``.

    Returns:
        Nombre de lignes effectivement insérées dans
        ``mesures_ressource_mensuelles`` (= nombre de mois mensuels
        retournés par NASA POWER moins les sentinelles ``-999.0``
        filtrées et les clés non-mensuelles ``YYYY13``).

        Retourne ``0`` si la variable d'env
        ``KUMA_SKIP_NASA_POWER_INGESTION`` est truthy (court-circuit
        sans appel réseau ni INSERT).

    Raises:
        RuntimeError : si ``code_serie`` n'existe pas dans
            ``series_metadonnees`` ou si le ``parametre_nasa`` demandé
            est absent du payload.
        kuma_data_core.exceptions.NasaPowerError : remontée du client
            si l'appel API échoue.
    """
    if _ingestion_doit_etre_skip():
        return 0

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
            f"Serie {code_serie!r} introuvable dans series_metadonnees. "
            f"Verifier que la migration de seed correspondante a bien ete appliquee."
        )

    serie_id: int = int(row.serie_id)
    methode_collecte: str | None = row.methode_collecte
    fiabilite_source: str | None = row.fiabilite_source

    niveau_derive = calculer_niveau_confiance_derive(
        methode_collecte=methode_collecte,
        fiabilite_source=fiabilite_source,
    )

    # Payload brut : seed committé (offline) ou appel live, puis parse commun
    # (seam offline-seed, fidélité). Client httpx injectable pour les tests.
    payload = _fetch_nasa_monthly_raw(
        latitude=latitude,
        longitude=longitude,
        parameters=[parametre_nasa],
        annee_debut=annee_debut,
        annee_fin=annee_fin,
        httpx_client=httpx_client,
    )
    response = parser_reponse_nasa(payload)

    if parametre_nasa not in response.properties.parameter:
        raise RuntimeError(
            f"Parametre {parametre_nasa!r} absent du payload NASA POWER monthly. "
            f"Parametres disponibles : {list(response.properties.parameter)}"
        )
    valeurs_par_cle: dict[str, float] = response.properties.parameter[parametre_nasa]

    lignes_a_inserer: list[dict[str, object]] = []
    for cle, valeur in valeurs_par_cle.items():
        annee_mois = _parse_cle_yyyymm(cle)
        if annee_mois is None:
            # Clé non mensuelle (typiquement YYYY13 pour moyenne annuelle) : ignoré
            continue
        if valeur == SENTINELLE_VALEUR_MANQUANTE:
            continue
        annee, mois = annee_mois
        lignes_a_inserer.append(
            {
                "serie_id": serie_id,
                "annee": annee,
                "mois": mois,
                "valeur": float(valeur),
                "niveau_confiance_derive": niveau_derive,
            }
        )

    if not lignes_a_inserer:
        return 0

    session.execute(
        text(
            """
            INSERT INTO mesures_ressource_mensuelles
                (serie_id, annee, mois, valeur, niveau_confiance_derive)
            VALUES
                (:serie_id, :annee, :mois, :valeur, :niveau_confiance_derive)
            """
        ),
        lignes_a_inserer,
    )
    session.flush()
    return len(lignes_a_inserer)
