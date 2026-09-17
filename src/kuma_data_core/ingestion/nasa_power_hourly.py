"""Ingestion horaire NASA POWER -> ``mesures_ressource_horaires``.

Pendant horaire de ``nasa_power_monthly.py`` et
``nasa_power_daily.py``. Consomme le client
``kuma_data_core.external.nasa_power.fetch_hourly``, transforme la
réponse en lignes ``mesures_ressource_horaires`` (instant ``TIMESTAMPTZ``
UTC), et fait l'INSERT bulk via SQLAlchemy.

Les données ingérées sont en statut **``brut``** (défaut SQL) : le
contrôle qualité algorithmique fera passer les lignes valides en
``valide_auto``.

La fonction principale ``ingerer_serie_horaire`` boucle **par année**
(un appel ``fetch_hourly`` par année civile, borne <= 366 jours validée
empiriquement) et parse les clés de la réponse au format ``YYYYMMDDHH``
en ``datetime`` UTC tz-aware.

``ingerer_series_horaires_groupe`` est le pendant horaire de
``ingerer_series_daily_groupe`` : un appel multi-paramètres par année
civile pour N grandeurs d'une même localité (facteur N d'économie
réseau), INSERT découpé en lots de 20 000 lignes (borne mémoire).

Variable d'environnement ``KUMA_SKIP_NASA_POWER_INGESTION`` (truthy)
court-circuite l'appel réseau et retourne 0 lignes insérées, comme les
fonctions journalière et mensuelle. Utile pour CI sans accès réseau.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import UTC, date, datetime

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.editorial.niveaux_confiance import (
    calculer_niveau_confiance_derive,
)
from kuma_data_core.external.nasa_power import (
    SENTINELLE_VALEUR_MANQUANTE,
    fetch_hourly,
)

_VARIABLE_ENV_SKIP_INGESTION: str = "KUMA_SKIP_NASA_POWER_INGESTION"
"""Variable d'environnement court-circuitant l'ingestion réseau.

Truthy values : '1', 'true', 'yes' (case-insensitive). Partage la même
variable que les modules daily / monthly : un seul switch désactive
toutes les ingestions NASA POWER (cohérence opérationnelle CI).
"""


def _ingestion_doit_etre_skip() -> bool:
    """Lit la variable d'environnement et retourne True si elle est truthy."""
    valeur = os.environ.get(_VARIABLE_ENV_SKIP_INGESTION, "").strip().lower()
    return valeur in ("1", "true", "yes")


def _parse_cle_yyyymmddhh(cle: str) -> datetime | None:
    """Parse une clé horaire NASA POWER ``YYYYMMDDHH`` en ``datetime`` UTC.

    Retourne un ``datetime`` tz-aware (fuseau UTC, cohérent avec
    ``time_standard='UTC'`` passé à ``fetch_hourly``) si la clé est
    valide, ``None`` sinon (clé non conforme).

    Args:
        cle : chaîne de 10 caractères (ex. ``"2021060112"`` =
            2021-06-01 12:00 UTC).
    """
    if len(cle) != 10 or not cle.isdigit():
        return None
    annee = int(cle[0:4])
    mois = int(cle[4:6])
    jour = int(cle[6:8])
    heure = int(cle[8:10])
    if not (1 <= mois <= 12 and 1 <= jour <= 31 and 0 <= heure <= 23):
        return None
    return datetime(annee, mois, jour, heure, tzinfo=UTC)


def ingerer_serie_horaire(
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
    """Ingère les mesures horaires d'une série NASA POWER dans ``mesures_ressource_horaires``.

    Boucle par année civile (un appel ``fetch_hourly`` par année, borne
    <= 366 jours), filtre les sentinelles ``-999.0``, et insère les
    lignes en statut ``brut`` (défaut SQL).

    Args:
        session : session SQLAlchemy active. La fonction add+flush mais
            ne commit pas (responsabilité du caller).
        code_serie : code naturel de la série dans ``series_metadonnees``
            (ex. ``gin_conakry_ghi_nasa_power_2021_2023``). Doit exister
            sinon ``RuntimeError``.
        parametre_nasa : code NASA POWER à ingérer (ex.
            ``ALLSKY_SFC_SW_DWN`` pour GHI).
        latitude, longitude : coordonnées WGS84 du point de mesure.
        annee_debut, annee_fin : bornes inclusives (années civiles).
        httpx_client : client httpx injectable pour tests via
            ``httpx.MockTransport``. Si None, un client temporaire est
            créé par ``fetch_hourly``.

    Returns:
        Nombre de lignes effectivement insérées dans
        ``mesures_ressource_horaires`` (heures retournées par NASA POWER
        moins les sentinelles ``-999.0`` filtrées et les clés non
        conformes). Retourne ``0`` si ``KUMA_SKIP_NASA_POWER_INGESTION``
        est truthy (court-circuit sans appel réseau ni INSERT).

    Raises:
        RuntimeError : si ``code_serie`` n'existe pas dans
            ``series_metadonnees`` ou si le ``parametre_nasa`` est absent
            d'un payload.
        kuma_data_core.exceptions.NasaPowerError : remontée du client si
            un appel API échoue.
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
    niveau_derive = calculer_niveau_confiance_derive(
        methode_collecte=row.methode_collecte,
        fiabilite_source=row.fiabilite_source,
    )

    lignes_a_inserer: list[dict[str, object]] = []
    for annee in range(annee_debut, annee_fin + 1):
        response = fetch_hourly(
            latitude=latitude,
            longitude=longitude,
            parameters=[parametre_nasa],
            start=date(annee, 1, 1),
            end=date(annee, 12, 31),
            time_standard="UTC",
            httpx_client=httpx_client,
        )
        if parametre_nasa not in response.properties.parameter:
            raise RuntimeError(
                f"Parametre {parametre_nasa!r} absent du payload NASA POWER hourly "
                f"(annee {annee}). Parametres disponibles : "
                f"{list(response.properties.parameter)}"
            )
        for cle, valeur in response.properties.parameter[parametre_nasa].items():
            instant = _parse_cle_yyyymmddhh(cle)
            if instant is None:
                continue
            if valeur == SENTINELLE_VALEUR_MANQUANTE:
                continue
            lignes_a_inserer.append(
                {
                    "serie_id": serie_id,
                    "instant_mesure": instant,
                    "valeur": float(valeur),
                    "niveau_confiance_derive": niveau_derive,
                }
            )

    if not lignes_a_inserer:
        return 0

    session.execute(
        text(
            """
            INSERT INTO mesures_ressource_horaires
                (serie_id, instant_mesure, valeur, niveau_confiance_derive)
            VALUES
                (:serie_id, :instant_mesure, :valeur, :niveau_confiance_derive)
            """
        ),
        lignes_a_inserer,
    )
    session.flush()
    return len(lignes_a_inserer)


_TAILLE_LOT_INSERT: int = 20_000
"""Taille des lots d'INSERT du chemin groupé.

Une année x 9 grandeurs approche 79 000 lignes : le découpage borne la
mémoire et la taille des statements (patron des seeds massifs, migration
107).
"""


def ingerer_series_horaires_groupe(
    *,
    session: Session,
    codes_series: Sequence[str],
    mapping_grandeur_parametre_nasa: dict[str, str],
    latitude: float,
    longitude: float,
    annee_debut: int,
    annee_fin: int,
    httpx_client: httpx.Client | None = None,
) -> dict[str, int]:
    """Ingère N séries horaires d'une même localité en 1 appel NASA POWER par année.

    Pendant horaire de ``ingerer_series_daily_groupe`` : un appel
    multi-paramètres par année civile au lieu d'un appel par (grandeur,
    année) — économie réseau d'un facteur N, et cohérence transactionnelle
    (même release amont CERES SYN1deg + MERRA-2 pour les N grandeurs d'une
    année). Filtrage des sentinelles ``-999.0`` (les grandeurs diurnes
    comme kt n'ont pas de lignes nocturnes) et des clés non conformes,
    statut ``brut`` (défaut SQL).

    Args:
        session : session SQLAlchemy active. La fonction add+flush mais ne
            commit pas (responsabilité du caller).
        codes_series : codes naturels des séries dans ``series_metadonnees``.
            Toutes doivent exister sinon ``RuntimeError`` ; toutes doivent
            partager la même localité (latitude/longitude fournies en
            arguments, pas re-déduites de la série).
        mapping_grandeur_parametre_nasa : pour chaque grandeur_code d'une
            série, le paramètre NASA POWER correspondant.
        latitude, longitude : coordonnées WGS84 du point unique de mesure.
        annee_debut, annee_fin : bornes inclusives (années civiles, un
            appel par année comme ``ingerer_serie_horaire``).
        httpx_client : client httpx injectable pour tests via
            ``httpx.MockTransport``.

    Returns:
        dict[str, int] : pour chaque code de série en entrée, le nombre de
        lignes insérées dans ``mesures_ressource_horaires``. Dict vide
        ``{}`` si ``KUMA_SKIP_NASA_POWER_INGESTION`` est truthy
        (court-circuit sans appel réseau ni INSERT).

    Raises:
        RuntimeError : série absente de ``series_metadonnees``, grandeur
            sans entrée dans le mapping, ou paramètre absent d'un payload.
        kuma_data_core.exceptions.NasaPowerError : remontée du client si
            un appel API échoue.
    """
    if _ingestion_doit_etre_skip():
        return {}
    if not codes_series:
        return {}

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
            f"Séries introuvables dans series_metadonnees : {sorted(codes_manquants)}. "
            f"Vérifier le seed de la migration appelante."
        )
    grandeurs_manquantes = {r.grandeur_code for r in rows} - set(mapping_grandeur_parametre_nasa)
    if grandeurs_manquantes:
        raise RuntimeError(
            f"Grandeurs sans paramètre NASA POWER mappé : {sorted(grandeurs_manquantes)}. "
            f"Vérifier mapping_grandeur_parametre_nasa."
        )

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

    parametres_demandes = sorted(
        {mapping_grandeur_parametre_nasa[g] for g in contexte_par_grandeur}
    )
    decompte_par_serie: dict[str, int] = {
        str(ctx["code_serie"]): 0 for ctx in contexte_par_grandeur.values()
    }
    tampon: list[dict[str, object]] = []

    def _vider_tampon() -> None:
        if not tampon:
            return
        session.execute(
            text(
                """
                INSERT INTO mesures_ressource_horaires
                    (serie_id, instant_mesure, valeur, niveau_confiance_derive)
                VALUES
                    (:serie_id, :instant_mesure, :valeur, :niveau_confiance_derive)
                """
            ),
            tampon,
        )
        tampon.clear()

    for annee in range(annee_debut, annee_fin + 1):
        response = fetch_hourly(
            latitude=latitude,
            longitude=longitude,
            parameters=parametres_demandes,
            start=date(annee, 1, 1),
            end=date(annee, 12, 31),
            time_standard="UTC",
            httpx_client=httpx_client,
        )
        for grandeur_code, ctx in contexte_par_grandeur.items():
            parametre_nasa = mapping_grandeur_parametre_nasa[grandeur_code]
            if parametre_nasa not in response.properties.parameter:
                raise RuntimeError(
                    f"Parametre {parametre_nasa!r} (grandeur {grandeur_code!r}) absent du "
                    f"payload NASA POWER hourly (annee {annee}). Parametres disponibles : "
                    f"{list(response.properties.parameter)}"
                )
            code_serie = str(ctx["code_serie"])
            for cle, valeur in response.properties.parameter[parametre_nasa].items():
                instant = _parse_cle_yyyymmddhh(cle)
                if instant is None:
                    continue
                if valeur == SENTINELLE_VALEUR_MANQUANTE:
                    continue
                tampon.append(
                    {
                        "serie_id": ctx["serie_id"],
                        "instant_mesure": instant,
                        "valeur": float(valeur),
                        "niveau_confiance_derive": ctx["niveau_derive"],
                    }
                )
                decompte_par_serie[code_serie] += 1
                if len(tampon) >= _TAILLE_LOT_INSERT:
                    _vider_tampon()

    _vider_tampon()
    session.flush()
    return decompte_par_serie
