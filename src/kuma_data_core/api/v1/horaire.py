"""Endpoints `/api/v1/horaire/<localite>/<grandeur>` - passe-plat horaire.

Deux endpoints distincts :

- ``GET /v1/horaire/{localite}/{grandeur}`` : retourne les données
  horaires passe-plat pour une fenêtre temporelle donnée.
- ``GET /v1/horaire/{localite}/{grandeur}/disponibilite`` : retourne
  la plage temporelle disponible.

Architecture :

1. Validation Pydantic des paramètres (schéma
   :class:`api.v1.schemas.horaire.ParametresHoraire`).
2. Résolution localité contre le référentiel (code complet nominal,
   alias courts historiques des villes pilotes en compatibilité).
3. Appel client externe via
   :func:`external.nasa_power.fetch_hourly` (retry transverse inclus).
4. Conversion réponse amont -> format Kuma cohérent via
   :func:`services.horaire.convertir_valeurs_amont_en_resultats`
   (sentinelles ``-999.0`` -> ``None``, clés ``YYYYMMDDHH`` ->
   ``datetime``, unité cible dérivée).
5. Filtrage sur la plage temporelle demandée, sérialisation JSON ou
   CSV.

Authentification : Bearer existante via ``CleApiValidee``.

Principe « Kuma assume » : aucune mention de la source amont dans les
codes erreur, messages, exemples JSON exposés au consommateur.

Mode calcul disponibilité v1 retenu : **B1 statique** (formule
``fin = mois_courant - 5 mois - 1 jour``). Choix justifié pour v1 par
la simplicité (0 appel externe) et la robustesse contre les variations
de politique amont restant à constater empiriquement. L'option B2
(scan empirique des sentinelles) peut être adoptée ultérieurement si
le besoin d'une borne dynamique précise est observé en production.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.api.codes_erreur import CodeErreur
from kuma_data_core.api.dependencies import CleApiValidee
from kuma_data_core.api.erreurs import ExceptionKuma
from kuma_data_core.api.v1.schemas.horaire import (
    DATE_DEBUT_DISPONIBILITE,
    ParametresHoraire,
    PlageTemporelle,
    ReponseDisponibilite,
    ReponseHoraire,
    ResultatHoraire,
)
from kuma_data_core.core.config import get_settings
from kuma_data_core.db.session import obtenir_session
from kuma_data_core.exceptions import (
    NasaPowerHttpError,
    NasaPowerPayloadError,
    NasaPowerRateLimitError,
    NasaPowerTimeoutError,
)
from kuma_data_core.external.nasa_power import fetch_hourly
from kuma_data_core.services.horaire import (
    code_parametre_amont,
    convertir_valeurs_amont_en_resultats,
    filtrer_resultats_par_plage,
    unite_cible,
)
from kuma_data_core.services.localites import coordonnees_localite

routeur = APIRouter(prefix="/horaire", tags=["horaire-passe-plat"])


# === Resolution de la localite contre le referentiel ======================

_PREFIXE_ALIAS_HISTORIQUE: str = "gin_"
"""Prefixe applique aux codes courts HISTORIQUES des 6 villes pilotes
(kankan, kindia...) pour retrouver le code complet. Compatibilite de
contrat uniquement : le chemin nominal est le code complet de la
table ``localites`` (genericite pays, residu 1 du brief de chantier)."""


def _resoudre_localite(session: Session, localite: str) -> str:
    """Resout le code de localite du path contre le referentiel.

    Ordre : code complet tel quel dans la table ; sinon alias
    historique (prefixe gin_). Localite inconnue : 404
    ``RESSOURCE_LOCALITE_INCONNUE`` (honnete, au lieu du 422 de
    l'ancienne enumeration fermee).
    """
    for candidat in (localite, f"{_PREFIXE_ALIAS_HISTORIQUE}{localite}"):
        existe = session.execute(
            text("SELECT 1 FROM localites WHERE code = :code AND actif = TRUE"),
            {"code": candidat},
        ).first()
        if existe is not None:
            return candidat
    raise ExceptionKuma(
        code=CodeErreur.RESSOURCE_LOCALITE_INCONNUE,
        message=f"Localite '{localite}' introuvable dans le referentiel.",
        statut_http=status.HTTP_404_NOT_FOUND,
    )


# === Mois de latence NRT (option B1 disponibilité) ========================

_LATENCE_NRT_MOIS: int = 5
"""Latence NRT amont observée empiriquement 5 mois.

Utilisée par la formule B1 statique :
``fin_disponible = mois_courant - 5 mois - 1 jour``.
"""


# === Helpers internes =====================================================


def _calculer_plage_disponible(aujourdhui: date | None = None) -> PlageTemporelle:
    """Calcule la plage disponible passe-plat selon la formule B1 statique.

    Returns:
        ``PlageTemporelle`` avec ``debut = 2001-01-01`` (borne historique)
        et ``fin = aujourd_hui - 5 mois - 1 jour``.
    """
    reference = aujourdhui if aujourdhui is not None else date.today()
    # Soustraction "5 mois" approximée à 5 * 30 jours pour robustesse
    # (précision ~jours-week ; option B2 cachée adopterait scan précis).
    fin = reference - timedelta(days=_LATENCE_NRT_MOIS * 30 + 1)
    return PlageTemporelle(debut=DATE_DEBUT_DISPONIBILITE, fin=fin)


def _serialiser_csv(resultats: list[ResultatHoraire]) -> str:
    """Sérialise une liste de ResultatHoraire en CSV."""
    buffer = io.StringIO()
    w = csv.writer(buffer)
    w.writerow(["instant", "valeur", "unite", "statut_editorial"])
    for r in resultats:
        valeur_str = "" if r.valeur is None else str(r.valeur)
        w.writerow([r.instant.isoformat(), valeur_str, r.unite, r.statut_editorial])
    return buffer.getvalue()


def _gerer_erreur_amont(exc: Exception) -> None:
    """Mappe les exceptions du client externe vers ExceptionKuma 503.

    Principe « Kuma assume » : le message ne mentionne pas la source
    amont. Le consommateur reçoit un message générique « service
    passe-plat horaire temporairement indisponible » avec le code
    ``PASSE_PLAT_INDISPONIBLE``.
    """
    if isinstance(
        exc,
        NasaPowerTimeoutError
        | NasaPowerRateLimitError
        | NasaPowerHttpError
        | NasaPowerPayloadError,
    ):
        raise ExceptionKuma(
            code=CodeErreur.PASSE_PLAT_INDISPONIBLE,
            message="Le service passe-plat horaire est temporairement indisponible.",
            statut_http=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc
    raise exc


# === Lever passe_plat : service du stocké validé =========


def _chercher_serie_horaire_stockee(
    session: Session, localite_code_complet: str, grandeur: str
) -> tuple[int, date, date] | None:
    """Cherche la série horaire stockée au catalogue pour (localité, grandeur).

    Renvoie ``(serie_id, periode_debut, periode_fin)`` si une série horaire
    active **portant des mesures stockées** existe pour ce couple, ``None``
    sinon. La jointure sur ``localites.code`` résout le couple
    indépendamment du naming de la série (exception ``gin_conakry`` vs
    ``gin_conakry_kaloum``).

    La clause ``EXISTS`` écarte les séries « coquilles » (métadonnées
    actives sans aucune ligne dans ``mesures_ressource_horaires``).
    Régression observée en production (2026-07-20) : pour (kankan, ghi),
    deux séries horaires actives coexistent - la série substrat
    2001-2025 (métadonnées seules) et la série sol terrain 2021-2023
    (17 520 mesures validées). Le ``LIMIT 1`` sans garde sélectionnait
    la coquille, dont la période couvre toute fenêtre demandée, et
    l'endpoint servait 200 avec zéro résultat au lieu de la mesure
    terrain. Le ``ORDER BY sm.id`` rend la sélection déterministe si
    plusieurs séries portent des mesures.
    """
    row = session.execute(
        text(
            """
            SELECT sm.id, sm.periode_debut, sm.periode_fin
            FROM series_metadonnees sm
            JOIN localites l ON l.id = sm.localite_id
            WHERE l.code = :localite
              AND sm.grandeur_code = :grandeur
              AND sm.granularite = 'horaire'
              AND sm.actif = TRUE
              AND EXISTS (
                  SELECT 1 FROM mesures_ressource_horaires m
                  WHERE m.serie_id = sm.id
              )
            ORDER BY sm.id
            LIMIT 1
            """
        ),
        {"localite": localite_code_complet, "grandeur": grandeur},
    ).first()
    if row is None or row.periode_fin is None:
        return None
    return int(row.id), row.periode_debut, row.periode_fin


def _lire_horaire_validee(
    session: Session,
    serie_id: int,
    grandeur: str,
    periode_debut: date,
    periode_fin: date,
) -> list[ResultatHoraire]:
    """Lit les points horaires ``valide_auto`` d'une série sur la plage.

    Les lignes rejetées par le QC (statut ``brut``) sont exclues. Instant
    renvoyé en UTC naïf, cohérent avec le passe-plat.
    """
    rows = session.execute(
        text(
            """
            SELECT instant_mesure, valeur
            FROM mesures_ressource_horaires
            WHERE serie_id = :serie_id
              AND statut IN ('valide_auto', 'valide_humain', 'publie')
              AND valide_au IS NULL
              AND (instant_mesure AT TIME ZONE 'UTC')::date >= :debut
              AND (instant_mesure AT TIME ZONE 'UTC')::date <= :fin
            ORDER BY instant_mesure
            """
        ),
        {"serie_id": serie_id, "debut": periode_debut, "fin": periode_fin},
    ).all()
    unite = unite_cible(grandeur)
    return [
        ResultatHoraire(
            instant=r.instant_mesure.astimezone(UTC).replace(tzinfo=None),
            valeur=float(r.valeur),
            unite=unite,
            statut_editorial="valide_auto",
        )
        for r in rows
    ]


def _repondre_horaire(params: ParametresHoraire, resultats: list[ResultatHoraire]) -> Response:
    """Sérialise une liste de ResultatHoraire en JSON (défaut) ou CSV."""
    if params.format_sortie == "csv":
        return Response(content=_serialiser_csv(resultats), media_type="text/csv")
    reponse = ReponseHoraire(
        localite=params.localite,
        grandeur=params.grandeur,
        periode_demandee=PlageTemporelle(debut=params.periode_debut, fin=params.periode_fin),
        resultats=resultats,
    )
    return JSONResponse(content=reponse.model_dump(mode="json"))


# === Endpoint data ========================================================


@routeur.get(
    "/{localite}/{grandeur}",
    response_model=None,
    status_code=status.HTTP_200_OK,
    summary="Donnees horaires passe-plat sur une fenetre temporelle",
)
def grandeur_horaire(
    params: Annotated[ParametresHoraire, Depends()],
    _cle: CleApiValidee,
    session: Annotated[Session, Depends(obtenir_session)],
) -> Response:
    """Retourne les valeurs horaires passe-plat pour une plage temporelle.

    Pattern passe-plat : aucune donnée n'est ingérée ni stockée côté
    Kuma. La réponse est calculée à la volée en relayant la requête
    vers le service amont, puis convertie au format Kuma cohérent
    (instant ISO 8601, valeur ou ``null`` si sentinelle, unité cible,
    statut éditorial ``passe_plat_non_valide``).

    Pré-validation : la fenêtre demandée doit être incluse dans la
    plage disponible (option B1 statique). Sinon : 400
    ``PLAGE_TEMPORELLE_NON_DISPONIBLE`` avec détails enrichis.

    Erreurs :

    - 401 ``AUTH_HEADER_MANQUANT`` / ``AUTH_CLE_INVALIDE`` (auth Bearer).
    - 422 ``VALIDATION_VALEUR_INVALIDE`` (paramètre Pydantic hors plage).
    - 400 ``PLAGE_TEMPORELLE_NON_DISPONIBLE`` (plage demandée hors
      disponibilité ; ou, en profil édition figée ADR-0003 D6, plage
      non couverte par le stocké - aucun relais amont n'est tenté).
    - 503 ``PASSE_PLAT_INDISPONIBLE`` (service amont indisponible
      après retry).
    """
    plage_disponible = _calculer_plage_disponible()
    if params.periode_debut < plage_disponible.debut or params.periode_fin > plage_disponible.fin:
        raise ExceptionKuma(
            code=CodeErreur.PLAGE_TEMPORELLE_NON_DISPONIBLE,
            message="La plage demandee n'est pas disponible.",
            statut_http=status.HTTP_400_BAD_REQUEST,
            details={
                "plage_demandee": f"{params.periode_debut} / {params.periode_fin}",
                "plage_disponible": f"{plage_disponible.debut} / {plage_disponible.fin}",
            },
        )

    localite_complet = _resoudre_localite(session, params.localite)

    # Lever passe_plat : si une série horaire stockée couvre la plage
    # demandée, servir la donnée validée (statut valide_auto) au lieu de
    # relayer la source amont non validée.
    serie_stockee = _chercher_serie_horaire_stockee(session, localite_complet, params.grandeur)
    if serie_stockee is not None:
        serie_id, periode_debut_serie, periode_fin_serie = serie_stockee
        if periode_debut_serie <= params.periode_debut and params.periode_fin <= periode_fin_serie:
            resultats_stockes = _lire_horaire_validee(
                session, serie_id, params.grandeur, params.periode_debut, params.periode_fin
            )
            return _repondre_horaire(params, resultats_stockes)

    # Profil édition figée (ADR-0003, D6) : jamais de relais amont. Une
    # plage non couverte par le stocké est indisponible, point - zéro
    # dépendance sortante sur le serveur public.
    if get_settings().edition_figee:
        raise ExceptionKuma(
            code=CodeErreur.PLAGE_TEMPORELLE_NON_DISPONIBLE,
            message=(
                "La plage demandee n'est pas couverte par les donnees stockees de cette edition."
            ),
            statut_http=status.HTTP_400_BAD_REQUEST,
            details={
                "plage_demandee": f"{params.periode_debut} / {params.periode_fin}",
                "raison": "edition_figee_sans_relais_temps_reel",
            },
        )

    # Repli passe-plat (relais NASA POWER, non validé éditorialement).
    latitude, longitude = coordonnees_localite(localite_complet)
    code_amont = code_parametre_amont(params.grandeur)

    try:
        reponse_amont = fetch_hourly(
            latitude=latitude,
            longitude=longitude,
            parameters=[code_amont],
            start=params.periode_debut,
            end=params.periode_fin,
        )
    except Exception as exc:
        _gerer_erreur_amont(exc)
        raise  # unreachable, _gerer_erreur_amont raise toujours

    valeurs_par_cle = reponse_amont.properties.parameter.get(code_amont, {})
    resultats_bruts = convertir_valeurs_amont_en_resultats(
        valeurs_par_cle=valeurs_par_cle,
        grandeur=params.grandeur,
    )
    resultats = filtrer_resultats_par_plage(
        resultats=resultats_bruts,
        periode_debut=params.periode_debut,
        periode_fin=params.periode_fin,
    )
    return _repondre_horaire(params, resultats)


# === Endpoint disponibilité ===============================================


@routeur.get(
    "/{localite}/{grandeur}/disponibilite",
    response_model=ReponseDisponibilite,
    status_code=status.HTTP_200_OK,
    summary="Plage temporelle disponible pour le passe-plat horaire",
)
def disponibilite_horaire(
    localite: str,
    grandeur: str,
    _cle: CleApiValidee,
) -> ReponseDisponibilite:
    """Retourne la plage temporelle disponible pour (localite, grandeur).

    La borne ``debut`` est fixée à la borne historique
    (``2001-01-01``). La borne ``fin`` est calculée dynamiquement par
    formule statique B1 (``aujourd'hui - 5 mois - 1 jour``) reflétant
    la latence NRT amont observée empiriquement (5 mois).

    La validation des combinaisons ``(localite, grandeur)`` reste
    permissive à cet endpoint (renvoie la plage standardisée même si
    le couple est inhabituel) pour éviter une dépendance Pydantic
    Literal sur ce simple méta-endpoint.
    """
    plage = _calculer_plage_disponible()
    return ReponseDisponibilite(
        localite=localite,
        grandeur=grandeur,
        plage_disponible=plage,
    )
