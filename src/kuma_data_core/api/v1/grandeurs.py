"""Endpoints `/api/v1/grandeurs/<code>` - 5 grandeurs F2 paramétrables.

Cinq endpoints distincts :

- ``GET /v1/grandeurs/poa_parametrable``
- ``GET /v1/grandeurs/productible_correction_thermique``
- ``GET /v1/grandeurs/productible_pr_fourni``
- ``GET /v1/grandeurs/energie_utile_ecs``
- ``GET /v1/grandeurs/degre_jour_climatisation``

Architecture commune :

1. Validation Pydantic des paramètres utilisateur (schémas
   ``api.v1.schemas.grandeurs``).
2. Résolution ``code_serie_source`` -> série + localité (lat/lon).
3. Lecture des mesures journalières depuis ``mesures_ressource`` ; pour
   les grandeurs nécessitant 2+ séries (POA = GHI+DNI+DHI, thermique/
   PR_T/ECS = GHI+T2M), lecture complémentaire automatique en recherchant
   les séries compagnes (même ``localite_id``, ``source_id`` et
   granularité, plage recouvrant la période demandée). La granularité de
   la série source doit correspondre à ``methode`` (journalière ou
   horaire), sinon 400.
4. Appel de la fonction publique pure du module
   ``services.grandeurs.<code>``.
5. Sérialisation JSON (défaut) ou CSV via paramètre ``format_sortie``
   avec alias URL ``format`` (shadow built-in).

Authentification : Bearer existante (``CleApiValidee``).

Format de réponse erreur : enveloppe ``{"erreur": {"code": ...,
"message": ..., "details": ...}}`` (cohérence API publique).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Annotated, Literal, NamedTuple

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.api.codes_erreur import CodeErreur
from kuma_data_core.api.dependencies import CleApiValidee
from kuma_data_core.api.erreurs import ExceptionKuma
from kuma_data_core.api.services.serie_lecture import (
    TableMesures,
    resolve_table_from_series_metadata,
)
from kuma_data_core.api.v1.schemas.grandeurs import (
    DegenerescenceFiche,
    EcartPaireInterSource,
    FichePointIncertitude,
    ParametresBifacial,
    ParametresDegreJourClimatisation,
    ParametresEnergieUtileECS,
    ParametresPOA,
    ParametresProductibleCorrectionThermique,
    ParametresProductiblePRFourni,
    ParametresPRRealiste,
    ReponseGhiExceedance,
    ReponseGrandeurF2,
    ReponseIncertitudeInterSource,
    ReponseIncertitudeInterSourceCollection,
    ReponsePRRealiste,
    ReponseTauxSalissureProxy,
    ResultatJournalier,
    ResultatMensuel,
)
from kuma_data_core.db.session import obtenir_session
from kuma_data_core.services.grandeurs.degre_jour_climatisation import (
    MesureHeureTemperature,
    MesureJourTemperature,
    calculer_degre_jour_climatisation,
    calculer_degre_jour_climatisation_horaire,
)
from kuma_data_core.services.grandeurs.energie_utile_ecs import (
    MesureHeureECS,
    MesureJourECS,
    calculer_energie_utile_ecs,
    calculer_energie_utile_ecs_horaire,
)
from kuma_data_core.services.grandeurs.ghi_exceedance import (
    ANNEE_DEBUT_CLIMATOLOGIE,
    ANNEE_FIN_CLIMATOLOGIE,
    METHODE_PERCENTILE,
    NIVEAU_CONFIANCE_DERIVE,
    UNITE_GHI_EXCEEDANCE,
    calculer_ghi_exceedance,
    calculer_totaux_annuels_climatologiques,
    grouper_jumeaux_pixel,
)
from kuma_data_core.services.grandeurs.poa_bifacial import (
    MesureHeureBifacial,
    MesureJourBifacial,
    albedo_du_jour,
    calculer_poa_bifacial,
    calculer_poa_bifacial_horaire,
)
from kuma_data_core.services.grandeurs.poa_parametrable import (
    MesureHeurePOA,
    MesureJourPOA,
    calculer_poa_parametrable,
    calculer_poa_parametrable_horaire,
)
from kuma_data_core.services.grandeurs.pr_realiste import (
    MesureJourPRRealiste,
    agreger_pr_mensuel,
    calculer_pr_realiste,
)
from kuma_data_core.services.grandeurs.productible_correction_thermique import (
    MesureHeureThermique,
    MesureJourThermique,
    calculer_productible_correction_thermique,
    calculer_productible_correction_thermique_horaire,
)
from kuma_data_core.services.grandeurs.productible_pr_fourni import (
    MesureHeurePRFourni,
    MesureJourPRFourni,
    MesureMoisPRFourni,
    calculer_productible_pr_fourni,
    calculer_productible_pr_fourni_horaire,
    calculer_productible_pr_fourni_mensuel,
)
from kuma_data_core.services.grandeurs.soiling_hsu import (
    CLEANING_THRESHOLD_DEFAUT_MM,
    SURFACE_TILT_DEFAUT,
    MesureEntreeSoiling,
    calculer_taux_salissure_proxy,
)

routeur = APIRouter(prefix="/grandeurs", tags=["grandeurs-F2"])


# === Helpers de résolution série + localité ================================


class SerieSourceResolue(NamedTuple):
    """Résultat de ``_resoudre_serie_source`` (accès par attribut).

    Champ ``source_code`` alimente le dispatch table-cible
    (JOURNALIER / MENSUEL_RESSOURCE / GRANDEURS_METIER).
    Champ ``granularite`` : filtre des séries compagnes par granularité
    ET dispatch table-cible par granularité (la table horaire partage
    ``periode_debut = 2021-01-01`` avec la journalière ; seule la
    granularité les distingue).
    """

    serie_id: int
    localite_id: int
    source_id: int
    grandeur_code: str
    localite_code: str
    periode_debut: date
    source_code: str
    granularite: str | None
    periode_fin: date | None


def _resoudre_serie_source(session: Session, code_serie: str) -> SerieSourceResolue:
    """Résout ``code_serie_source`` vers les métadonnées de la série.

    Le champ ``periode_debut`` est utilisé par les endpoints F2 pour
    matcher la fenêtre temporelle des séries compagnes (cf.
    ``_chercher_serie_compagne``) - nécessaire depuis l'ajout de séries
    climato mensuelle 1991-2020 / 2001-2020 qui coexistent avec les
    séries journalières 2021-2025 pour les mêmes couples (localité,
    grandeur, source).

    Le champ ``source_code`` alimente le dispatch table-cible via
    ``resolve_table_from_series_metadata`` pour les endpoints F2 à
    entrée polymorphe journalier/mensuel.

    Raises:
        ExceptionKuma : HTTP 404 ``RESSOURCE_SERIE_INCONNUE`` si série
            absente.
    """
    row = session.execute(
        text(
            """
            SELECT sm.id, sm.localite_id, sm.source_id, sm.grandeur_code,
                   l.code AS localite_code, sm.periode_debut,
                   s.code AS source_code, sm.granularite, sm.periode_fin
            FROM series_metadonnees sm
            JOIN localites l ON l.id = sm.localite_id
            JOIN sources s ON s.id = sm.source_id
            WHERE sm.code = :code
              AND sm.actif = TRUE
            """
        ),
        {"code": code_serie},
    ).first()
    if row is None:
        raise ExceptionKuma(
            code=CodeErreur.RESSOURCE_SERIE_INCONNUE,
            message=f"Serie source {code_serie!r} introuvable.",
            statut_http=status.HTTP_404_NOT_FOUND,
        )
    return SerieSourceResolue(
        serie_id=int(row.id),
        localite_id=int(row.localite_id),
        source_id=int(row.source_id),
        grandeur_code=row.grandeur_code,
        localite_code=row.localite_code,
        periode_debut=row.periode_debut,
        source_code=row.source_code,
        granularite=row.granularite,
        periode_fin=row.periode_fin,
    )


def _resoudre_coordonnees(session: Session, localite_id: int) -> tuple[float, float]:
    """Résout ``localite_id`` vers ``(latitude_deg, longitude_deg)``.

    Raises:
        ExceptionKuma : HTTP 500 ``SERVEUR_ERREUR_INTERNE`` si localité
            absente (incohérence FK théoriquement impossible).
    """
    row = session.execute(
        text("SELECT latitude, longitude FROM localites WHERE id = :id"),
        {"id": localite_id},
    ).first()
    if row is None or row.latitude is None or row.longitude is None:
        raise ExceptionKuma(
            code=CodeErreur.SERVEUR_ERREUR_INTERNE,
            message=(
                f"Localite id={localite_id} sans coordonnees latitude/longitude "
                "(incoherence FK ou seed incomplet)."
            ),
            statut_http=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return float(row.latitude), float(row.longitude)


_FENETRE_LARGE_DEBUT: date = date(1900, 1, 1)
_FENETRE_LARGE_FIN: date = date(2100, 1, 1)
"""Bornes « toute la série » des lectures sans fenêtre utilisateur (F1 à la volée)."""


def _chercher_serie_compagne(
    session: Session,
    serie: SerieSourceResolue,
    grandeur_code_compagne: str,
    fenetre: tuple[date, date] | None = None,
) -> int | None:
    """Cherche une série compagne (même localité + source, grandeur différente).

    Filtres :

    - même ``localite_id`` + ``source_id``, série active ;
    - ``granularite IS NOT DISTINCT FROM`` celle de la source : distingue
      journalier / mensuel / horaire (une compagne horaire choisie pour un
      calcul journalier serait lue dans la mauvaise table) ;
    - **recouvrement** de la fenêtre de calcul (``fenetre`` = période
      demandée, défaut : la plage de la série source).

    Les grandeurs d'une même source n'ont pas toutes la même profondeur
    (ex. GHI NASA POWER depuis 1991, DNI/DHI depuis 2001) : exiger le même
    ``periode_debut`` que la source raterait ces compagnes. Ordre
    déterministe : plus grand recouvrement de la fenêtre, puis même
    ``periode_debut`` que la source (même famille temporelle), puis ``id``.

    Renvoie ``serie_id`` ou ``None`` si aucune trouvée.
    """
    debut, fin = fenetre or (serie.periode_debut, serie.periode_fin or _FENETRE_LARGE_FIN)
    row = session.execute(
        text(
            """
            SELECT id FROM series_metadonnees
            WHERE localite_id = :localite_id
              AND source_id = :source_id
              AND grandeur_code = :grandeur_code
              AND granularite IS NOT DISTINCT FROM :granularite_source
              AND actif = TRUE
              AND periode_debut <= :fin
              AND (periode_fin IS NULL OR periode_fin >= :debut)
            ORDER BY LEAST(COALESCE(periode_fin, :fin), :fin)
                     - GREATEST(periode_debut, :debut) DESC,
                     (periode_debut = :periode_debut_source) DESC,
                     id
            LIMIT 1
            """
        ),
        {
            "localite_id": serie.localite_id,
            "source_id": serie.source_id,
            "grandeur_code": grandeur_code_compagne,
            "granularite_source": serie.granularite,
            "periode_debut_source": serie.periode_debut,
            "debut": debut,
            "fin": fin,
        },
    ).first()
    return int(row.id) if row else None


def _exiger_grandeur(
    grandeur_code: str,
    code_attendu: str,
    code_serie: str,
    endpoint: str,
) -> None:
    """Vérifie que la série source correspond à la grandeur attendue.

    Raises:
        ExceptionKuma : HTTP 400 ``INCOMPATIBILITE_SOURCE_GRANDEUR`` si
            ``grandeur_code != code_attendu``.
    """
    if grandeur_code != code_attendu:
        raise ExceptionKuma(
            code=CodeErreur.INCOMPATIBILITE_SOURCE_GRANDEUR,
            message=(
                f"Endpoint {endpoint!r} attend une serie source de grandeur "
                f"{code_attendu!r}, mais {code_serie!r} pointe vers {grandeur_code!r}."
            ),
            statut_http=status.HTTP_400_BAD_REQUEST,
        )


def _exiger_granularite_methode(
    serie: SerieSourceResolue,
    methode: Literal["moyenne_journaliere", "integration_horaire"],
    code_serie: str,
    granularites_journalieres: tuple[str, ...] = ("journalier",),
) -> None:
    """Vérifie que la granularité de la série source convient à la méthode F2.

    ``integration_horaire`` lit ``mesures_ressource_horaires`` (série
    horaire) ; ``moyenne_journaliere`` lit ``mesures_ressource`` (série
    journalière ; ``productible_pr_fourni`` admet aussi le mensuel). Sans ce
    contrôle, une série d'une autre granularité serait lue dans la mauvaise
    table et renverrait silencieusement une liste vide.

    Raises:
        ExceptionKuma : HTTP 400 ``VALIDATION_VALEUR_INVALIDE`` si la
            granularité ne correspond pas à la méthode.
    """
    if methode == "integration_horaire":
        admises: tuple[str, ...] = ("horaire",)
    else:
        admises = granularites_journalieres
    if serie.granularite not in admises:
        attendu = " ou ".join(repr(g) for g in admises)
        raise ExceptionKuma(
            code=CodeErreur.VALIDATION_VALEUR_INVALIDE,
            message=(
                f"methode={methode!r} exige une serie source de granularite {attendu}, "
                f"mais {code_serie!r} est de granularite {serie.granularite!r}."
            ),
            statut_http=status.HTTP_400_BAD_REQUEST,
        )


def _exiger_serie_journaliere(serie: SerieSourceResolue, code_serie: str, endpoint: str) -> None:
    """Vérifie qu'une route F1 à la volée reçoit une série journalière.

    Les routes ``taux_salissure_proxy`` et ``pr_realiste`` lisent
    ``mesures_ressource`` (journalier, modèle HSU path-dependant).

    Raises:
        ExceptionKuma : HTTP 400 ``INCOMPATIBILITE_SOURCE_GRANDEUR`` sinon.
    """
    if serie.granularite != "journalier":
        raise ExceptionKuma(
            code=CodeErreur.INCOMPATIBILITE_SOURCE_GRANDEUR,
            message=(
                f"Endpoint {endpoint!r} exige une serie source journaliere, mais "
                f"{code_serie!r} est de granularite {serie.granularite!r}."
            ),
            statut_http=status.HTTP_400_BAD_REQUEST,
        )


# === Helpers de lecture des mesures ========================================


def _lire_mesures_par_serie_id(
    session: Session,
    serie_id: int,
    periode_debut: date,
    periode_fin: date,
) -> dict[date, float]:
    """Lit les valeurs journalières d'une série sur la fenêtre.

    Renvoie un dict ``{instant_mesure: valeur}`` pour indexation rapide
    par date (utilisé pour aligner GHI/DNI/DHI/T2M lors des calculs
    multi-séries).
    """
    rows = session.execute(
        text(
            """
            SELECT instant_mesure, valeur
            FROM mesures_ressource
            WHERE serie_id = :serie_id
              AND valide_au IS NULL
              AND instant_mesure >= :debut
              AND instant_mesure <= :fin
            ORDER BY instant_mesure
            """
        ),
        {"serie_id": serie_id, "debut": periode_debut, "fin": periode_fin},
    ).all()
    return {r.instant_mesure: float(r.valeur) for r in rows}


def _lire_mesures_horaires_par_serie_id(
    session: Session,
    serie_id: int,
    periode_debut: date,
    periode_fin: date,
) -> dict[datetime, float]:
    """Lit les valeurs horaires **validées** d'une série sur la fenêtre.

    Lit ``mesures_ressource_horaires`` (statut ``valide_auto``, lignes
    courantes), renvoie ``{instant_mesure: valeur}`` indexé par datetime
    UTC. Utilisé par l'intégration horaire DJC
    (``methode='integration_horaire'``). Les lignes rejetées par le QC
    (statut ``brut``) sont exclues. Borne de fenêtre sur la date UTC,
    cohérente avec la lecture journalière.
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
    return {r.instant_mesure: float(r.valeur) for r in rows}


def _lire_mesures_mensuel_par_serie_id(
    session: Session,
    serie_id: int,
    periode_debut: date,
    periode_fin: date,
) -> dict[tuple[int, int], float]:
    """Lit les valeurs mensuelles d'une série sur la fenêtre.

    Renvoie un dict ``{(annee, mois): valeur}`` indexé par couple
    année/mois (pattern aligné sur ``mesures_ressource_mensuelles.annee``
    + ``mois`` SMALLINT séparés). Bornes inclusives traduites en
    comparaisons lexicographiques ``(annee, mois) >= (from_y, from_m)``
    et ``<=`` (cf. ``api/v1/series.py:_lire_mesures_mensuel``).

    Réutilisé par les endpoints F2 à entrée polymorphe journalier /
    mensuel (dispatch via ``resolve_table_from_series_metadata``).
    """
    rows = session.execute(
        text(
            """
            SELECT annee, mois, valeur
            FROM mesures_ressource_mensuelles
            WHERE serie_id = :serie_id
              AND valide_au IS NULL
              AND (annee, mois) >= (:from_y, :from_m)
              AND (annee, mois) <= (:to_y, :to_m)
            ORDER BY annee, mois
            """
        ),
        {
            "serie_id": serie_id,
            "from_y": periode_debut.year,
            "from_m": periode_debut.month,
            "to_y": periode_fin.year,
            "to_m": periode_fin.month,
        },
    ).all()
    return {(int(r.annee), int(r.mois)): float(r.valeur) for r in rows}


# === Helpers de sérialisation ==============================================


def _serialiser_csv_journalier(reponse: ReponseGrandeurF2) -> str:
    """Sérialise une réponse à résultats journaliers en CSV."""
    buffer = io.StringIO()
    w = csv.writer(buffer)
    w.writerow(["granularite", "instant", "valeur", "unite", "niveau_confiance"])
    for r in reponse.resultats:
        instant = r.instant.isoformat() if isinstance(r, ResultatJournalier) else r.instant
        w.writerow([r.granularite, instant, r.valeur, r.unite, r.niveau_confiance])
    return buffer.getvalue()


def _construire_reponse(
    code_grandeur: str,
    code_serie_source: str,
    parametres_appliques: dict[str, object],
    resultats: Sequence[ResultatJournalier | ResultatMensuel],
    format_sortie: Literal["json", "csv"],
) -> Response:
    """Construit la réponse HTTP finale (JSON par défaut, CSV si demandé)."""
    reponse = ReponseGrandeurF2(
        code_grandeur=code_grandeur,
        code_serie_source=code_serie_source,
        parametres_appliques=parametres_appliques,
        resultats=list(resultats),
    )
    if format_sortie == "csv":
        return Response(
            content=_serialiser_csv_journalier(reponse),
            media_type="text/csv",
        )
    return JSONResponse(content=reponse.model_dump(mode="json"))


# === Endpoint POA paramétrable ============================================


@routeur.get(
    "/poa_parametrable",
    response_model=None,
    status_code=status.HTTP_200_OK,
    summary="POA paramétrable (modèle Perez 1990 + Liu-Jordan fallback)",
)
def grandeur_poa_parametrable(
    params: Annotated[ParametresPOA, Depends()],
    _cle: CleApiValidee,
    session: Annotated[Session, Depends(obtenir_session)],
) -> Response:
    """Calcule la POA journalière à partir d'une série GHI (+ DNI/DHI compagnes).

    Pattern multi-séries automatique :

    - **Série principale attendue** : ``grandeur_code = 'ghi'``. Une série
      pointant une autre grandeur lève une 400
      ``INCOMPATIBILITE_SOURCE_GRANDEUR``.
    - **Séries compagnes cherchées automatiquement** : DNI et DHI sur la
      même ``localite_id`` + ``source_id`` + granularité, recouvrant la
      période demandée (recherche par ``_chercher_serie_compagne``).
    - **Comportement si compagnes présentes** : modèle Perez 1990
      (décomposition diffus en 3 zones, calcul anisotropique).
    - **Comportement si DNI / DHI absentes** (série ou jour) : fallback
      Liu-Jordan isotrope automatique (décomposition Erbs 1982 GHI -> DNI
      estimé + DHI estimé, puis transposition isotrope) : précision
      dégradée 10-15% sous ciel partiellement couvert.
    - **Granularité** : série source journalière (``moyenne_journaliere``)
      ou horaire (``integration_horaire``) ; sinon 400.
    - **Traçabilité limitée v1** : la réponse JSON n'indique pas
      explicitement quel modèle a été appliqué.
    """
    serie = _resoudre_serie_source(session, params.code_serie_source)
    _exiger_grandeur(serie.grandeur_code, "ghi", params.code_serie_source, "poa_parametrable")
    _exiger_granularite_methode(serie, params.methode, params.code_serie_source)

    latitude, longitude = _resoudre_coordonnees(session, serie.localite_id)

    # Compagnes DNI / DHI : mêmes localité + source + granularité, recouvrant
    # la période demandée (en horaire, la recherche trouve les DNI/DHI horaires).
    fenetre = (params.periode_debut, params.periode_fin)
    dni_serie_id = _chercher_serie_compagne(session, serie, "dni", fenetre)
    dhi_serie_id = _chercher_serie_compagne(session, serie, "dhi", fenetre)

    if params.methode == "integration_horaire":
        # Perez intégré par heure : lève le biais de moyennage
        # (+16 % sur plan incliné). Exige une série source horaire ET les
        # compagnes DNI/DHI horaires (pas de fallback Liu-Jordan en horaire).
        if dni_serie_id is None or dhi_serie_id is None:
            raise ExceptionKuma(
                code=CodeErreur.VALIDATION_VALEUR_INVALIDE,
                message=(
                    "Le POA horaire (Perez) exige des series compagnes DNI et DHI "
                    f"horaires pour la localite de {params.code_serie_source!r} ; absentes."
                ),
                statut_http=status.HTTP_400_BAD_REQUEST,
            )
        ghi_h = _lire_mesures_horaires_par_serie_id(
            session, serie.serie_id, params.periode_debut, params.periode_fin
        )
        dni_h = _lire_mesures_horaires_par_serie_id(
            session, dni_serie_id, params.periode_debut, params.periode_fin
        )
        dhi_h = _lire_mesures_horaires_par_serie_id(
            session, dhi_serie_id, params.periode_debut, params.periode_fin
        )
        mesures_horaires: list[MesureHeurePOA] = [
            {"instant_mesure": instant, "ghi": ghi, "dni": dni_h[instant], "dhi": dhi_h[instant]}
            for instant, ghi in ghi_h.items()
            if instant in dni_h and instant in dhi_h
        ]
        resultats = calculer_poa_parametrable_horaire(
            mesures=mesures_horaires,
            latitude_deg=latitude,
            longitude_deg=longitude,
            parametres=params,
        )
    else:
        ghi_par_jour = _lire_mesures_par_serie_id(
            session, serie.serie_id, params.periode_debut, params.periode_fin
        )
        # Fallback Liu-Jordan automatique dans la fonction pure si DNI/DHI absentes.
        dni_par_jour: dict[date, float] = (
            _lire_mesures_par_serie_id(
                session, dni_serie_id, params.periode_debut, params.periode_fin
            )
            if dni_serie_id is not None
            else {}
        )
        dhi_par_jour: dict[date, float] = (
            _lire_mesures_par_serie_id(
                session, dhi_serie_id, params.periode_debut, params.periode_fin
            )
            if dhi_serie_id is not None
            else {}
        )
        mesures: list[MesureJourPOA] = [
            {
                "instant_mesure": jour,
                "ghi": ghi,
                "dni": dni_par_jour.get(jour),
                "dhi": dhi_par_jour.get(jour),
            }
            for jour, ghi in ghi_par_jour.items()
        ]
        resultats = calculer_poa_parametrable(
            mesures=mesures,
            latitude_deg=latitude,
            longitude_deg=longitude,
            parametres=params,
        )

    return _construire_reponse(
        code_grandeur="poa_parametrable",
        code_serie_source=params.code_serie_source,
        parametres_appliques={
            "inclinaison_deg": params.inclinaison_deg,
            "orientation_deg": params.orientation_deg,
            "albedo_sol": params.albedo_sol,
            "methode": params.methode,
        },
        resultats=resultats,
        format_sortie=params.format_sortie,
    )


# === Endpoint POA bifacial (modèle infinite-sheds) ===============


def _resoudre_serie_albedo_journalier(
    session: Session, localite_id: int, source_id: int
) -> int | None:
    """Résout la série ``albedo_surface`` journalière de la localité + source.

    Indépendant de la période de la série GHI source : l'albédo n'existe qu'en
    **journalier** (et sert même en mode horaire, broadcast intra-jour),
    donc son ``periode_debut`` diffère de celui du GHI horaire - la recherche par
    compagne stricte ne convient pas. Renvoie ``None`` si absente (→ repli sur
    ``params.albedo_sol``).
    """
    row = session.execute(
        text(
            """
            SELECT id FROM series_metadonnees
            WHERE localite_id = :loc AND source_id = :src
              AND grandeur_code = 'albedo_surface' AND granularite = 'journalier'
              AND actif = TRUE
            ORDER BY periode_debut DESC
            LIMIT 1
            """
        ),
        {"loc": localite_id, "src": source_id},
    ).scalar()
    return int(row) if row is not None else None


@routeur.get(
    "/poa_bifacial",
    response_model=None,
    status_code=status.HTTP_200_OK,
    summary="POA bifacial (modèle infinite-sheds row-aware)",
)
def grandeur_poa_bifacial(
    params: Annotated[ParametresBifacial, Depends()],
    _cle: CleApiValidee,
    session: Annotated[Session, Depends(obtenir_session)],
) -> Response:
    """Calcule le POA global bifacial (modèle infinite-sheds row-aware).

    **Distinct du `poa_parametrable` mono-plan** : modèle de champ de rangées
    avec face arrière (gcr, hauteur, pitch, bifacialité). Série principale
    attendue : `grandeur_code='ghi'`. Compagnes **DNI + DHI obligatoires**
    (granularité-aware, recouvrant la période demandée ; pas de fallback
    Liu-Jordan) → 400 si absentes ; seuls les jours portant GHI, DNI et DHI
    sont calculés. Albédo : série `albedo_surface` journalière (réel par
    localité ; repli `albedo_sol` si absente ; broadcast aux heures en mode
    horaire).
    """
    serie = _resoudre_serie_source(session, params.code_serie_source)
    _exiger_grandeur(serie.grandeur_code, "ghi", params.code_serie_source, "poa_bifacial")
    _exiger_granularite_methode(serie, params.methode, params.code_serie_source)
    latitude, longitude = _resoudre_coordonnees(session, serie.localite_id)

    fenetre = (params.periode_debut, params.periode_fin)
    dni_serie_id = _chercher_serie_compagne(session, serie, "dni", fenetre)
    dhi_serie_id = _chercher_serie_compagne(session, serie, "dhi", fenetre)
    if dni_serie_id is None or dhi_serie_id is None:
        raise ExceptionKuma(
            code=CodeErreur.INCOMPATIBILITE_SOURCE_GRANDEUR,
            message=(
                "Le POA bifacial (infinite-sheds) exige des series compagnes DNI et DHI "
                f"pour la localite de {params.code_serie_source!r}, recouvrant la periode "
                "demandee (pas de fallback) ; absentes."
            ),
            statut_http=status.HTTP_400_BAD_REQUEST,
        )

    albedo_serie_id = _resoudre_serie_albedo_journalier(session, serie.localite_id, serie.source_id)
    albedo_jour: dict[date, float] = (
        _lire_mesures_par_serie_id(
            session, albedo_serie_id, params.periode_debut, params.periode_fin
        )
        if albedo_serie_id is not None
        else {}
    )

    if params.methode == "integration_horaire":
        ghi_h = _lire_mesures_horaires_par_serie_id(
            session, serie.serie_id, params.periode_debut, params.periode_fin
        )
        dni_h = _lire_mesures_horaires_par_serie_id(
            session, dni_serie_id, params.periode_debut, params.periode_fin
        )
        dhi_h = _lire_mesures_horaires_par_serie_id(
            session, dhi_serie_id, params.periode_debut, params.periode_fin
        )
        mesures_horaires: list[MesureHeureBifacial] = [
            {
                "instant_mesure": instant,
                "ghi": ghi,
                "dni": dni_h[instant],
                "dhi": dhi_h[instant],
                "albedo": albedo_du_jour(albedo_jour, instant.date(), params.albedo_sol),
            }
            for instant, ghi in ghi_h.items()
            if instant in dni_h and instant in dhi_h
        ]
        resultats = calculer_poa_bifacial_horaire(
            mesures=mesures_horaires,
            latitude_deg=latitude,
            longitude_deg=longitude,
            parametres=params,
        )
    else:
        ghi_j = _lire_mesures_par_serie_id(
            session, serie.serie_id, params.periode_debut, params.periode_fin
        )
        dni_j = _lire_mesures_par_serie_id(
            session, dni_serie_id, params.periode_debut, params.periode_fin
        )
        dhi_j = _lire_mesures_par_serie_id(
            session, dhi_serie_id, params.periode_debut, params.periode_fin
        )
        mesures: list[MesureJourBifacial] = [
            {
                "instant_mesure": jour,
                "ghi": ghi,
                "dni": dni_j[jour],
                "dhi": dhi_j[jour],
                "albedo": albedo_du_jour(albedo_jour, jour, params.albedo_sol),
            }
            for jour, ghi in ghi_j.items()
            if jour in dni_j and jour in dhi_j
        ]
        resultats = calculer_poa_bifacial(
            mesures=mesures,
            latitude_deg=latitude,
            longitude_deg=longitude,
            parametres=params,
        )

    return _construire_reponse(
        code_grandeur="poa_bifacial",
        code_serie_source=params.code_serie_source,
        parametres_appliques={
            "inclinaison_deg": params.inclinaison_deg,
            "orientation_deg": params.orientation_deg,
            "gcr": params.gcr,
            "hauteur_m": params.hauteur_m,
            "pitch_m": params.pitch_m,
            "bifacialite": params.bifacialite,
            "albedo_sol": params.albedo_sol,
            "methode": params.methode,
        },
        resultats=resultats,
        format_sortie=params.format_sortie,
    )


# === Endpoint productible correction thermique ============================


def _lire_t2m_compagne(
    session: Session,
    serie: SerieSourceResolue,
    code_serie_source: str,
    endpoint: str,
    periode_debut: date,
    periode_fin: date,
) -> dict[date, float]:
    """Cherche et lit la série T2M compagne d'une série source (même loc/source).

    La compagne est filtrée par granularité stricte et recouvrement de la
    période demandée (cf. ``_chercher_serie_compagne``).

    Raises:
        ExceptionKuma : HTTP 400 ``INCOMPATIBILITE_SOURCE_GRANDEUR`` si
            aucune série T2M compagne trouvée.
    """
    t2m_serie_id = _chercher_serie_compagne(session, serie, "t2m", (periode_debut, periode_fin))
    if t2m_serie_id is None:
        raise ExceptionKuma(
            code=CodeErreur.INCOMPATIBILITE_SOURCE_GRANDEUR,
            message=(
                f"Endpoint {endpoint!r} requiert une serie T2M compagne de "
                f"{code_serie_source!r} (meme localite, source et granularite, "
                "recouvrant la periode demandee). Aucune trouvee."
            ),
            statut_http=status.HTTP_400_BAD_REQUEST,
        )
    return _lire_mesures_par_serie_id(session, t2m_serie_id, periode_debut, periode_fin)


@routeur.get(
    "/productible_correction_thermique",
    response_model=None,
    status_code=status.HTTP_200_OK,
    summary="Productible avec correction thermique (NOCT simple, Ross 1980)",
)
def grandeur_productible_correction_thermique(
    params: Annotated[ParametresProductibleCorrectionThermique, Depends()],
    _cle: CleApiValidee,
    session: Annotated[Session, Depends(obtenir_session)],
) -> Response:
    """Calcule le productible thermique-corrigé (NOCT simple Ross 1980).

    Pattern multi-séries automatique :

    - **Série principale attendue** : ``grandeur_code = 'ghi'``.
    - **Série compagne cherchée** : T2M (même localité + même source).
    - **Comportement si T2M présente** : modèle NOCT simple appliqué
      ligne par ligne (T_cell = T_amb + (NOCT - 20) * G / 800, puis
      P_AC corrigée).
    - **Comportement si T2M absente** : 400
      ``INCOMPATIBILITE_SOURCE_GRANDEUR`` (la correction thermique ne
      peut être calculée sans température ambiante).

    Note : un mode ``faiman`` (Faiman 2008, dépendant du vent) a été
    codé et testé puis retiré de l'API : Faiman relève du régime
    terrain, calibration locale u0/u1 requise pour éviter une fausse
    confiance B.
    """
    serie = _resoudre_serie_source(session, params.code_serie_source)
    _exiger_grandeur(
        serie.grandeur_code, "ghi", params.code_serie_source, "productible_correction_thermique"
    )
    _exiger_granularite_methode(serie, params.methode, params.code_serie_source)

    if params.methode == "integration_horaire":
        # NOCT appliqué par heure (T_cell sur le GHI horaire réel) : lève le
        # biais de moyennage. Exige GHI horaire + T2M horaire compagne.
        t2m_serie_id = _chercher_serie_compagne(
            session, serie, "t2m", (params.periode_debut, params.periode_fin)
        )
        if t2m_serie_id is None:
            raise ExceptionKuma(
                code=CodeErreur.INCOMPATIBILITE_SOURCE_GRANDEUR,
                message=(
                    "Endpoint 'productible_correction_thermique' requiert une serie T2M "
                    f"horaire compagne de {params.code_serie_source!r}. Aucune trouvee."
                ),
                statut_http=status.HTTP_400_BAD_REQUEST,
            )
        ghi_h = _lire_mesures_horaires_par_serie_id(
            session, serie.serie_id, params.periode_debut, params.periode_fin
        )
        t2m_h = _lire_mesures_horaires_par_serie_id(
            session, t2m_serie_id, params.periode_debut, params.periode_fin
        )
        mesures_horaires: list[MesureHeureThermique] = [
            {"instant_mesure": instant, "t_amb_degc": t2m_h[instant], "irradiance_w_par_m2": ghi}
            for instant, ghi in ghi_h.items()
            if instant in t2m_h
        ]
        resultats = calculer_productible_correction_thermique_horaire(
            mesures=mesures_horaires, parametres=params
        )
    else:
        ghi_par_jour = _lire_mesures_par_serie_id(
            session, serie.serie_id, params.periode_debut, params.periode_fin
        )
        t2m_par_jour = _lire_t2m_compagne(
            session,
            serie,
            params.code_serie_source,
            "productible_correction_thermique",
            params.periode_debut,
            params.periode_fin,
        )
        mesures: list[MesureJourThermique] = [
            {
                "instant_mesure": jour,
                "t_amb_degc": t2m_par_jour[jour],
                "irradiance_kwh_par_m2_jour": ghi,
            }
            for jour, ghi in ghi_par_jour.items()
            if jour in t2m_par_jour
        ]
        resultats = calculer_productible_correction_thermique(mesures=mesures, parametres=params)

    parametres_appliques: dict[str, object] = {
        "noct_degc": params.noct_degc,
        "coeff_temp_pourcent_par_degc": params.coeff_temp_pourcent_par_degc,
        "puissance_stc_wc": params.puissance_stc_wc,
        "methode": params.methode,
    }

    return _construire_reponse(
        code_grandeur="productible_correction_thermique",
        code_serie_source=params.code_serie_source,
        parametres_appliques=parametres_appliques,
        resultats=resultats,
        format_sortie=params.format_sortie,
    )


# === Endpoint productible PR fourni =======================================


@routeur.get(
    "/productible_pr_fourni",
    response_model=None,
    status_code=status.HTTP_200_OK,
    summary="Productible avec PR fourni (brut Marion 2005 + PR_T Dierauf 2013)",
)
def grandeur_productible_pr_fourni(
    params: Annotated[ParametresProductiblePRFourni, Depends()],
    _cle: CleApiValidee,
    session: Annotated[Session, Depends(obtenir_session)],
) -> Response:
    """Calcule le productible avec PR fourni (brut Marion 2005 / PR_T Dierauf 2013).

    Pattern multi-séries automatique selon ``correction`` :

    - **Série principale attendue** : ``grandeur_code = 'ghi'``.
    - **Si ``correction = 'aucune'``** : aucune compagne cherchée. PR brut
      appliqué directement (E_AC = P_STC * G * PR).
    - **Si ``correction = 'temperature'``** :
      - Série T2M cherchée (même localité + même source).
      - Si T2M présente : PR_T appliqué (correction NOCT + facteur
        thermique).
      - Si T2M absente : 400 ``INCOMPATIBILITE_SOURCE_GRANDEUR``.

    Dispatch table-cible via ``resolve_table_from_series_metadata`` :

    - ``JOURNALIER`` (``mesures_ressource``) : flow journalier ci-dessus.
    - ``MENSUEL_RESSOURCE`` (``mesures_ressource_mensuelles``) : branche
      mensuelle climato, mode ``correction='aucune'`` uniquement. Sortie
      :class:`ResultatMensuel` au format ``instant='YYYY-MM'``, sémantique
      « productible quotidien moyen pour le mois ». Mode ``'temperature'``
      sur mensuel rejeté 400 ``INCOMPATIBILITE_SOURCE_GRANDEUR``
      (non-linéarité cubique NOCT incompatible avec moyenne climato).
    - ``GRANDEURS_METIER`` (série calculée Kuma) : rejeté 400
      ``INCOMPATIBILITE_SOURCE_GRANDEUR`` (une série F1 calculée Kuma
      n'est pas admissible comme source brute d'un calcul F2).

    Variantes PR_W et PR_C non exposées v1 (TMY local non disponible).
    """
    serie = _resoudre_serie_source(session, params.code_serie_source)

    # Dispatch table-cible avant vérification grandeur_code : la nature
    # de la source (brute vs calculée Kuma) doit être vérifiée
    # indépendamment de la grandeur portée, pour permettre un message
    # d'erreur explicite « source kuma_calculs non admissible » même
    # quand la série n'est pas un GHI (cas concret : toute série
    # kuma_calculs porte par construction une grandeur_code != 'ghi',
    # donc l'ordre inverse court-circuiterait toujours le dispatch).
    table_cible = resolve_table_from_series_metadata(
        source_code=serie.source_code,
        granularite=serie.granularite,
    )

    if table_cible == TableMesures.GRANDEURS_METIER:
        raise ExceptionKuma(
            code=CodeErreur.INCOMPATIBILITE_SOURCE_GRANDEUR,
            message=(
                f"Endpoint 'productible_pr_fourni' n'accepte pas de serie source "
                f"calculee Kuma (source.code='kuma_calculs'). Serie {params.code_serie_source!r} "
                "pointe sur 'grandeurs_metier'."
            ),
            statut_http=status.HTTP_400_BAD_REQUEST,
        )

    _exiger_grandeur(serie.grandeur_code, "ghi", params.code_serie_source, "productible_pr_fourni")
    _exiger_granularite_methode(
        serie,
        params.methode,
        params.code_serie_source,
        granularites_journalieres=("journalier", "mensuel"),
    )

    if params.methode == "integration_horaire":
        # PR appliqué par heure : pour PR_T (Dierauf) lève le biais de Jensen
        # (T_cell non-linéaire) ; pour PR brut (linéaire) identique au journalier
        # (exposé pour cohérence d'interface). Exige une série source horaire
        # (+ T2M horaire si correction='temperature').
        ghi_h = _lire_mesures_horaires_par_serie_id(
            session, serie.serie_id, params.periode_debut, params.periode_fin
        )
        mesures_horaires: list[MesureHeurePRFourni]
        if params.correction == "temperature":
            t2m_serie_id = _chercher_serie_compagne(
                session, serie, "t2m", (params.periode_debut, params.periode_fin)
            )
            if t2m_serie_id is None:
                raise ExceptionKuma(
                    code=CodeErreur.INCOMPATIBILITE_SOURCE_GRANDEUR,
                    message=(
                        "Endpoint 'productible_pr_fourni' en correction='temperature' horaire "
                        f"requiert une serie T2M horaire compagne de {params.code_serie_source!r}. "
                        "Aucune trouvee."
                    ),
                    statut_http=status.HTTP_400_BAD_REQUEST,
                )
            t2m_h = _lire_mesures_horaires_par_serie_id(
                session, t2m_serie_id, params.periode_debut, params.periode_fin
            )
            mesures_horaires = [
                {
                    "instant_mesure": instant,
                    "irradiance_w_par_m2": ghi,
                    "t_amb_degc": t2m_h[instant],
                }
                for instant, ghi in ghi_h.items()
                if instant in t2m_h
            ]
        else:
            mesures_horaires = [
                {"instant_mesure": instant, "irradiance_w_par_m2": ghi, "t_amb_degc": None}
                for instant, ghi in ghi_h.items()
            ]
        resultats = calculer_productible_pr_fourni_horaire(
            mesures=mesures_horaires, parametres=params
        )
        return _construire_reponse(
            code_grandeur="productible_pr_fourni",
            code_serie_source=params.code_serie_source,
            parametres_appliques={
                "pr_fourni": params.pr_fourni,
                "correction": params.correction,
                "puissance_stc_wc": params.puissance_stc_wc,
                "methode": params.methode,
                **(
                    {
                        "noct_degc": params.noct_degc,
                        "coeff_temp_pourcent_par_degc": params.coeff_temp_pourcent_par_degc,
                    }
                    if params.correction == "temperature"
                    else {}
                ),
            },
            resultats=resultats,
            format_sortie=params.format_sortie,
        )

    if table_cible == TableMesures.MENSUEL_RESSOURCE:
        if params.correction == "temperature":
            raise ExceptionKuma(
                code=CodeErreur.INCOMPATIBILITE_SOURCE_GRANDEUR,
                message=(
                    "Endpoint 'productible_pr_fourni' sur serie mensuelle climato "
                    "n'accepte que correction='aucune' (le mode 'temperature' est "
                    "non-lineaire et incompatible avec une moyenne quotidienne "
                    "agregee sur le mois)."
                ),
                statut_http=status.HTTP_400_BAD_REQUEST,
            )
        ghi_par_mois = _lire_mesures_mensuel_par_serie_id(
            session, serie.serie_id, params.periode_debut, params.periode_fin
        )
        mesures_mensuel: list[MesureMoisPRFourni] = [
            {
                "annee": annee,
                "mois": mois,
                "irradiance_kwh_par_m2_jour": ghi,
            }
            for (annee, mois), ghi in ghi_par_mois.items()
        ]
        resultats_mensuel = calculer_productible_pr_fourni_mensuel(
            mesures=mesures_mensuel, parametres=params
        )
        return _construire_reponse(
            code_grandeur="productible_pr_fourni",
            code_serie_source=params.code_serie_source,
            parametres_appliques={
                "pr_fourni": params.pr_fourni,
                "correction": params.correction,
                "puissance_stc_wc": params.puissance_stc_wc,
                "methode": params.methode,
            },
            resultats=resultats_mensuel,
            format_sortie=params.format_sortie,
        )

    ghi_par_jour = _lire_mesures_par_serie_id(
        session, serie.serie_id, params.periode_debut, params.periode_fin
    )
    t2m_par_jour: dict[date, float] = {}
    if params.correction == "temperature":
        t2m_par_jour = _lire_t2m_compagne(
            session,
            serie,
            params.code_serie_source,
            "productible_pr_fourni",
            params.periode_debut,
            params.periode_fin,
        )

    mesures: list[MesureJourPRFourni] = [
        {
            "instant_mesure": jour,
            "irradiance_kwh_par_m2_jour": ghi,
            "t_amb_degc": t2m_par_jour.get(jour),
        }
        for jour, ghi in ghi_par_jour.items()
        if (params.correction == "aucune") or (jour in t2m_par_jour)
    ]
    resultats = calculer_productible_pr_fourni(mesures=mesures, parametres=params)
    return _construire_reponse(
        code_grandeur="productible_pr_fourni",
        code_serie_source=params.code_serie_source,
        parametres_appliques={
            "pr_fourni": params.pr_fourni,
            "correction": params.correction,
            "puissance_stc_wc": params.puissance_stc_wc,
            "methode": params.methode,
            **(
                {
                    "noct_degc": params.noct_degc,
                    "coeff_temp_pourcent_par_degc": params.coeff_temp_pourcent_par_degc,
                }
                if params.correction == "temperature"
                else {}
            ),
        },
        resultats=resultats,
        format_sortie=params.format_sortie,
    )


# === Endpoint énergie utile ECS ===========================================


@routeur.get(
    "/energie_utile_ecs",
    response_model=None,
    status_code=status.HTTP_200_OK,
    summary="Énergie utile ECS bord-capteur (Hottel-Whillier-Bliss)",
)
def grandeur_energie_utile_ecs(
    params: Annotated[ParametresEnergieUtileECS, Depends()],
    _cle: CleApiValidee,
    session: Annotated[Session, Depends(obtenir_session)],
) -> Response:
    """Calcule l'énergie utile ECS bord-capteur (Hottel-Whillier-Bliss).

    Pattern multi-séries automatique :

    - **Série principale attendue** : ``grandeur_code = 'ghi'``.
    - **Série compagne cherchée** : T2M (même localité + même source).
    - **Comportement si T2M présente** : équation HWB appliquée
      (eta = eta0 - a1 * dT/G - a2 * dT²/G, puis Q_utile = eta * G).
    - **Comportement si T2M absente** : 400
      ``INCOMPATIBILITE_SOURCE_GRANDEUR`` (le rendement HWB dépend de
      la différence T_fluide - T_amb).
    """
    serie = _resoudre_serie_source(session, params.code_serie_source)
    _exiger_grandeur(serie.grandeur_code, "ghi", params.code_serie_source, "energie_utile_ecs")
    _exiger_granularite_methode(serie, params.methode, params.code_serie_source)

    if params.methode == "integration_horaire":
        # Rendement HWB appliqué par heure (G horaire réel) : lève le biais de
        # Jensen (rendement non-linéaire en G). Exige GHI horaire + T2M horaire.
        t2m_serie_id = _chercher_serie_compagne(
            session, serie, "t2m", (params.periode_debut, params.periode_fin)
        )
        if t2m_serie_id is None:
            raise ExceptionKuma(
                code=CodeErreur.INCOMPATIBILITE_SOURCE_GRANDEUR,
                message=(
                    "Endpoint 'energie_utile_ecs' horaire requiert une serie T2M horaire "
                    f"compagne de {params.code_serie_source!r}. Aucune trouvee."
                ),
                statut_http=status.HTTP_400_BAD_REQUEST,
            )
        ghi_h = _lire_mesures_horaires_par_serie_id(
            session, serie.serie_id, params.periode_debut, params.periode_fin
        )
        t2m_h = _lire_mesures_horaires_par_serie_id(
            session, t2m_serie_id, params.periode_debut, params.periode_fin
        )
        mesures_horaires: list[MesureHeureECS] = [
            {"instant_mesure": instant, "t_amb_degc": t2m_h[instant], "irradiance_w_par_m2": ghi}
            for instant, ghi in ghi_h.items()
            if instant in t2m_h
        ]
        resultats = calculer_energie_utile_ecs_horaire(mesures=mesures_horaires, parametres=params)
        return _construire_reponse(
            code_grandeur="energie_utile_ecs",
            code_serie_source=params.code_serie_source,
            parametres_appliques={
                "rendement_optique_eta0": params.rendement_optique_eta0,
                "pertes_lineaires_a1": params.pertes_lineaires_a1,
                "pertes_quadratiques_a2": params.pertes_quadratiques_a2,
                "temperature_fluide_entree_degc": params.temperature_fluide_entree_degc,
                "methode": params.methode,
            },
            resultats=resultats,
            format_sortie=params.format_sortie,
        )

    ghi_par_jour = _lire_mesures_par_serie_id(
        session, serie.serie_id, params.periode_debut, params.periode_fin
    )
    t2m_par_jour = _lire_t2m_compagne(
        session,
        serie,
        params.code_serie_source,
        "energie_utile_ecs",
        params.periode_debut,
        params.periode_fin,
    )

    mesures: list[MesureJourECS] = [
        {
            "instant_mesure": jour,
            "t_amb_degc": t2m_par_jour[jour],
            "irradiance_kwh_par_m2_jour": ghi,
        }
        for jour, ghi in ghi_par_jour.items()
        if jour in t2m_par_jour
    ]
    resultats = calculer_energie_utile_ecs(mesures=mesures, parametres=params)
    return _construire_reponse(
        code_grandeur="energie_utile_ecs",
        code_serie_source=params.code_serie_source,
        parametres_appliques={
            "rendement_optique_eta0": params.rendement_optique_eta0,
            "pertes_lineaires_a1": params.pertes_lineaires_a1,
            "pertes_quadratiques_a2": params.pertes_quadratiques_a2,
            "temperature_fluide_entree_degc": params.temperature_fluide_entree_degc,
            "methode": params.methode,
        },
        resultats=resultats,
        format_sortie=params.format_sortie,
    )


# === Endpoint degré-jour climatisation ====================================


@routeur.get(
    "/degre_jour_climatisation",
    response_model=None,
    status_code=status.HTTP_200_OK,
    summary="Degrés-jours de climatisation (moyenne journalière ou intégration horaire)",
)
def grandeur_degre_jour_climatisation(
    params: Annotated[ParametresDegreJourClimatisation, Depends()],
    _cle: CleApiValidee,
    session: Annotated[Session, Depends(obtenir_session)],
) -> Response:
    """Calcule les degrés-jours de climatisation mensuels (Erbs 1983).

    Pattern série unique (pas de multi-séries) :

    - **Série principale attendue** : ``grandeur_code = 't2m'``. Une série
      pointant une autre grandeur lève une 400
      ``INCOMPATIBILITE_SOURCE_GRANDEUR``.
    - **Aucune série compagne cherchée** : DJC dépend uniquement de la
      température ambiante journalière et de la base T_b utilisateur.
    - **Sortie agrégée mensuel** : la grandeur produit des
      :class:`ResultatMensuel` au format ``instant="YYYY-MM"`` par
      sommation des écarts journaliers positifs sur le mois.
    - **Granularité** : série T2M journalière (``moyenne_journaliere``) ou
      horaire (``integration_horaire``) ; une série mensuelle est refusée
      (400), la moyenne mensuelle écraserait les écarts journaliers.
    """
    serie = _resoudre_serie_source(session, params.code_serie_source)
    _exiger_grandeur(
        serie.grandeur_code, "t2m", params.code_serie_source, "degre_jour_climatisation"
    )
    _exiger_granularite_methode(serie, params.methode, params.code_serie_source)

    if params.methode == "integration_horaire":
        # Lève le biais de moyennage journalier (-5 à -15 % tropical).
        # Exige une série source horaire (T2M stocké et validé).
        t2m_par_heure = _lire_mesures_horaires_par_serie_id(
            session, serie.serie_id, params.periode_debut, params.periode_fin
        )
        mesures_horaires: list[MesureHeureTemperature] = [
            {"instant_mesure": instant, "t_degc": valeur}
            for instant, valeur in t2m_par_heure.items()
        ]
        resultats = calculer_degre_jour_climatisation_horaire(
            mesures=mesures_horaires, parametres=params
        )
    else:
        t2m_par_jour = _lire_mesures_par_serie_id(
            session, serie.serie_id, params.periode_debut, params.periode_fin
        )
        mesures: list[MesureJourTemperature] = [
            {"instant_mesure": jour, "t_moy_degc": valeur} for jour, valeur in t2m_par_jour.items()
        ]
        resultats = calculer_degre_jour_climatisation(mesures=mesures, parametres=params)

    return _construire_reponse(
        code_grandeur="degre_jour_climatisation",
        code_serie_source=params.code_serie_source,
        parametres_appliques={
            "base_temperature_degc": params.base_temperature_degc,
            "methode": params.methode,
        },
        resultats=resultats,
        format_sortie=params.format_sortie,
    )


# === Endpoint ghi_exceedance (F1 calculee_volee) =======


def _resoudre_serie_ghi_mensuelle_climatologique(
    session: Session, code_localite: str
) -> tuple[int, str]:
    """Résout (serie_id, code_serie) de la série GHI mensuelle couvrant la normale.

    Cherche dans ``series_metadonnees`` la série active de la localité
    ciblée avec ``grandeur_code = 'ghi'``, ``source.code = 'nasa_power'``,
    ``granularite = 'mensuel'`` et une plage couvrant toute la fenêtre
    climatologique 1991-2020 (une série prolongée au-delà, ou commençant
    avant, convient : seules ses années 1991-2020 sont lues). La
    granularité est exigée : une série journalière NASA POWER peut débuter
    elle aussi en 1991 mais ses mesures ne vivent pas dans la table
    mensuelle. Ordre déterministe (début le plus récent, puis ``id``).

    Raises:
        ExceptionKuma : HTTP 404 ``RESSOURCE_LOCALITE_INCONNUE`` si la
            localité n'est pas trouvée ou si aucune série GHI NASA POWER
            mensuelle couvrant 1991-2020 n'y est rattachée.
    """
    row = session.execute(
        text(
            """
            SELECT sm.id AS serie_id, sm.code AS code_serie
            FROM series_metadonnees sm
            JOIN localites l ON l.id = sm.localite_id
            JOIN sources s ON s.id = sm.source_id
            WHERE l.code = :code_localite
              AND sm.grandeur_code = 'ghi'
              AND s.code = 'nasa_power'
              AND sm.granularite = 'mensuel'
              AND sm.periode_debut <= :debut_climatologie
              AND (sm.periode_fin IS NULL OR sm.periode_fin >= :fin_climatologie)
              AND sm.actif = TRUE
            ORDER BY sm.periode_debut DESC, sm.id
            LIMIT 1
            """
        ),
        {
            "code_localite": code_localite,
            "debut_climatologie": date(ANNEE_DEBUT_CLIMATOLOGIE, 1, 1),
            "fin_climatologie": date(ANNEE_FIN_CLIMATOLOGIE, 12, 31),
        },
    ).first()
    if row is None:
        raise ExceptionKuma(
            code=CodeErreur.RESSOURCE_LOCALITE_INCONNUE,
            message=(
                f"Aucune serie GHI NASA POWER mensuelle couvrant {ANNEE_DEBUT_CLIMATOLOGIE}-"
                f"{ANNEE_FIN_CLIMATOLOGIE} trouvee pour la localite {code_localite!r}. "
                "La grandeur ghi_exceedance n'est disponible que pour les localites "
                "dotees d'une telle serie (cf. /v1/series?grandeur=ghi&source=nasa_power)."
            ),
            statut_http=status.HTTP_404_NOT_FOUND,
        )
    return int(row.serie_id), str(row.code_serie)


def _lire_mensuelles_climatologiques(
    session: Session, serie_id: int
) -> list[tuple[int, int, float]]:
    """Lit les mesures mensuelles courantes d'une série sur la fenêtre 1991-2020.

    Renvoie une liste de tuples ``(annee, mois, valeur)`` ordonnés
    chronologiquement (360 lignes pour une normale complète). Filtre
    standard ``valide_au IS NULL`` (version courante) ; les années hors
    normale d'une série prolongée ne sont pas lues.
    """
    rows = session.execute(
        text(
            """
            SELECT annee, mois, valeur
            FROM mesures_ressource_mensuelles
            WHERE serie_id = :serie_id AND valide_au IS NULL
              AND annee BETWEEN :annee_debut AND :annee_fin
            ORDER BY annee, mois
            """
        ),
        {
            "serie_id": serie_id,
            "annee_debut": ANNEE_DEBUT_CLIMATOLOGIE,
            "annee_fin": ANNEE_FIN_CLIMATOLOGIE,
        },
    ).all()
    return [(int(r.annee), int(r.mois), float(r.valeur)) for r in rows]


def _lire_vecteurs_ghi_nasa_climatologiques(session: Session) -> dict[str, tuple[float, ...]]:
    """Vecteurs GHI NASA POWER mensuels 1991-2020 de toutes les localités.

    Une requête (agrégat ordonné par série) ; base de la détection des
    jumeaux de pixel (``grouper_jumeaux_pixel`` : égalité exacte des vecteurs).
    Une localité portant plusieurs séries retient la même que
    ``_resoudre_serie_ghi_mensuelle_climatologique`` (début le plus récent,
    puis ``id``).
    """
    rows = session.execute(
        text(
            """
            SELECT l.code AS code_localite,
                   array_agg(m.valeur ORDER BY m.annee, m.mois) AS valeurs
            FROM series_metadonnees sm
            JOIN sources s ON s.id = sm.source_id
            JOIN localites l ON l.id = sm.localite_id
            JOIN mesures_ressource_mensuelles m ON m.serie_id = sm.id
            WHERE s.code = 'nasa_power'
              AND sm.grandeur_code = 'ghi'
              AND sm.granularite = 'mensuel'
              AND sm.actif = TRUE
              AND sm.periode_debut <= :debut_climatologie
              AND (sm.periode_fin IS NULL OR sm.periode_fin >= :fin_climatologie)
              AND m.valide_au IS NULL
              AND m.annee BETWEEN :annee_debut AND :annee_fin
            GROUP BY l.code, sm.periode_debut, sm.id
            ORDER BY l.code, sm.periode_debut DESC, sm.id
            """
        ),
        {
            "debut_climatologie": date(ANNEE_DEBUT_CLIMATOLOGIE, 1, 1),
            "fin_climatologie": date(ANNEE_FIN_CLIMATOLOGIE, 12, 31),
            "annee_debut": ANNEE_DEBUT_CLIMATOLOGIE,
            "annee_fin": ANNEE_FIN_CLIMATOLOGIE,
        },
    ).all()
    vecteurs: dict[str, tuple[float, ...]] = {}
    for r in rows:
        vecteurs.setdefault(str(r.code_localite), tuple(float(v) for v in r.valeurs))
    return vecteurs


def _jumeaux_pixel_nasa_ghi(session: Session) -> dict[str, list[str]]:
    """``{code_localite: [autres localités au vecteur GHI NASA identique]}``.

    Détection à la lecture de la dégénérescence de pixel sur la grille NASA
    POWER (identité exacte des séries climatologiques mensuelles, aucune
    grille supposée).
    """
    return grouper_jumeaux_pixel(_lire_vecteurs_ghi_nasa_climatologiques(session))


def _construire_limite_ghi_exceedance(base_annees: int, jumeaux: Sequence[str]) -> str:
    """Compose le champ ``limite`` de la réponse, enrichi le cas échéant.

    Le texte de base avertit que la valeur est inter-annuelle uniquement
    (et non un P90 bancable complet). Si la localité partage sa cellule
    NASA POWER avec d'autres (jumeaux de pixel détectés à la lecture), une
    mention explicite de l'identité de leurs P50 / P90 est ajoutée.
    """
    base = (
        "Exceedance inter-annuelle uniquement (variabilite annee a annee sur "
        f"{base_annees} ans, normale {ANNEE_DEBUT_CLIMATOLOGIE}-{ANNEE_FIN_CLIMATOLOGIE}). "
        "Ne propage pas l'incertitude de modele satellitaire NASA POWER : ce n'est "
        "pas un P90 bancable complet (qui necessiterait un modele d'erreur explicite, "
        "type PRUVE, et idealement une calibration sol)."
    )
    if jumeaux:
        base += (
            f" Jumeaux de pixel : cette localite partage sa cellule NASA POWER (grille "
            f"~1 deg) avec {len(jumeaux)} autre(s) localite(s) ({', '.join(jumeaux)}) ; "
            f"leurs series GHI mensuelles {ANNEE_DEBUT_CLIMATOLOGIE}-{ANNEE_FIN_CLIMATOLOGIE} "
            "sont strictement identiques et leurs P50 / P90 le sont donc aussi."
        )
    return base


@routeur.get(
    "/ghi_exceedance/{code_localite}",
    response_model=ReponseGhiExceedance,
    status_code=status.HTTP_200_OK,
    summary="Exceedance inter-annuelle P50 / P90 de l'irradiation annuelle (GHI)",
    tags=["grandeurs-F1"],
)
def grandeur_ghi_exceedance(
    code_localite: str,
    _cle: CleApiValidee,
    session: Annotated[Session, Depends(obtenir_session)],
) -> ReponseGhiExceedance:
    """Calcule à la volée P50 et P90 de l'irradiation annuelle d'une localité.

    Pipeline :

    1. Résolution de la série GHI NASA POWER **mensuelle** couvrant la
       normale 1991-2020 (404 ``RESSOURCE_LOCALITE_INCONNUE`` sinon).
    2. Lecture des mesures mensuelles courantes **restreintes à 1991-2020**
       (kWh/m²/jour), même si la série est prolongée au-delà.
    3. Totaux annuels (kWh/m²/an) des années complètes, par pondération
       journalière ``calendar.monthrange`` (années bissextiles incluses) ;
       422 ``PLAGE_TEMPORELLE_NON_DISPONIBLE`` si moins de 2 années.
    4. Percentiles P50 (médiane) et P90 (= percentile 10, scénario
       conservateur). P90 < P50 par construction.
    5. Construction de la réponse ; le champ ``limite`` cite les jumeaux de
       pixel éventuels (localités à série NASA identique, P50/P90 identiques).
    """
    serie_id, code_serie = _resoudre_serie_ghi_mensuelle_climatologique(session, code_localite)
    mensuelles = _lire_mensuelles_climatologiques(session, serie_id)
    totaux_par_annee = calculer_totaux_annuels_climatologiques(mensuelles)
    if len(totaux_par_annee) < 2:
        raise ExceptionKuma(
            code=CodeErreur.PLAGE_TEMPORELLE_NON_DISPONIBLE,
            message=(
                f"Serie {code_serie!r} : {len(totaux_par_annee)} annee(s) complete(s) sur "
                f"{ANNEE_DEBUT_CLIMATOLOGIE}-{ANNEE_FIN_CLIMATOLOGIE} ; au moins 2 sont "
                "necessaires au calcul des percentiles."
            ),
            statut_http=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    resultat = calculer_ghi_exceedance(list(totaux_par_annee.values()))
    jumeaux = _jumeaux_pixel_nasa_ghi(session).get(code_localite, [])
    return ReponseGhiExceedance(
        code_localite=code_localite,
        code_serie_source=code_serie,
        periode=f"{ANNEE_DEBUT_CLIMATOLOGIE}-{ANNEE_FIN_CLIMATOLOGIE}",
        base_annees=len(totaux_par_annee),
        p50=resultat.p50,
        p90=resultat.p90,
        unite=UNITE_GHI_EXCEEDANCE,
        methode_percentile=METHODE_PERCENTILE,
        niveau_confiance=NIVEAU_CONFIANCE_DERIVE,
        limite=_construire_limite_ghi_exceedance(len(totaux_par_annee), jumeaux),
    )


# === Endpoint taux_salissure_proxy (F1 calculee_volee, soiling) =======


SOURCE_PLUIE_SALISSURE: str = "gpm_imerg"
"""Source de la pluie journalière des épisodes de lessivage (salissure, PR réaliste).

GPM IMERG (servi par NASA POWER, ``IMERG_PRECTOT``), et non la pluie NASA POWER
``PRECTOTCORR`` : celle-ci est recalée par pentade sur CMAP « temps réel » et
porte des jours extrêmes fantômes et une rupture vers 2016-2017 (ADR-0032) ; le
modèle HSU, qui nettoie les modules au-delà d'un seuil de pluie journalière, en
serait directement faussé (ADR-0033)."""


def _chercher_serie_pluie_salissure(
    session: Session,
    localite_id: int,
    periode_debut: date,
    periode_fin: date | None,
) -> int | None:
    """Résout la série de pluie journalière des épisodes de lessivage d'une localité.

    Résolveur **dédié** : la pluie vient de ``SOURCE_PLUIE_SALISSURE`` (GPM IMERG,
    ADR-0033), source différente des PM ``cams_eac4`` et du GHI ;
    ``_chercher_serie_compagne`` filtre sur ``source_id`` et la raterait. La source
    est **épinglée explicitement** : la pluie NASA POWER (``PRECTOTCORR``), présente
    aux mêmes localités, n'est jamais retenue. Si une localité porte plusieurs séries
    de cette source (fenêtres distinctes), la série retenue est celle dont la plage
    **recouvre la fenêtre de la série appelante** ; ordre stable sur
    ``periode_debut, id``.
    """
    row = session.execute(
        text(
            """
            SELECT sm.id FROM series_metadonnees sm
            JOIN sources s ON s.id = sm.source_id
            WHERE sm.localite_id = :localite_id
              AND s.code = :source
              AND sm.grandeur_code = 'precipitation'
              AND sm.granularite = 'journalier'
              AND sm.actif = TRUE
              AND (sm.periode_fin IS NULL OR sm.periode_fin >= :periode_debut)
              AND (CAST(:periode_fin AS DATE) IS NULL OR sm.periode_debut <= :periode_fin)
            ORDER BY sm.periode_debut, sm.id
            LIMIT 1
            """
        ),
        {
            "localite_id": localite_id,
            "periode_debut": periode_debut,
            "periode_fin": periode_fin,
            "source": SOURCE_PLUIE_SALISSURE,
        },
    ).first()
    return int(row.id) if row else None


def _verifier_contiguite_journaliere(dates: list[date], code_serie_source: str) -> None:
    """Garde-fou : le modèle HSU est path-dependant (il intègre la salissure depuis
    le début), l'index journalier doit être **trié croissant et sans trou** ; sinon
    l'accumulation est faussée. ``dates`` est supposé déjà trié."""
    for i in range(1, len(dates)):
        if dates[i] != dates[i - 1] + timedelta(days=1):
            raise ExceptionKuma(
                code=CodeErreur.PLAGE_TEMPORELLE_NON_DISPONIBLE,
                message=(
                    f"Serie source {code_serie_source!r} : trou dans l'index "
                    f"journalier (entre {dates[i - 1]} et {dates[i]}). Le modele "
                    "HSU est path-dependant et exige une serie sans trou ; le "
                    "calcul de salissure ne peut aboutir sur cette fenetre."
                ),
                statut_http=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )


@routeur.get(
    "/taux_salissure_proxy/{code_serie_source}",
    response_model=ReponseTauxSalissureProxy,
    status_code=status.HTTP_200_OK,
    summary="Proxy de salissure (perte de transmission %, modele HSU)",
    tags=["grandeurs-F1"],
)
def grandeur_taux_salissure_proxy(
    code_serie_source: str,
    _cle: CleApiValidee,
    session: Annotated[Session, Depends(obtenir_session)],
) -> ReponseTauxSalissureProxy:
    """Perte de transmission par salissure (% = (1 - ratio HSU) x 100), à la volée.

    Pipeline :

    1. ``code_serie_source`` = la série **PM2.5** journalière (EAC4) ; résolution +
       contrôle de grandeur et de granularité (400 si ce n'est pas une série
       ``pm2_5`` journalière).
    2. Compagne **PM10** (même source ``cams_eac4``, ``_chercher_serie_compagne``)
       + pluie journalière **GPM IMERG** (``SOURCE_PLUIE_SALISSURE``, résolveur
       dédié, ADR-0033).
       L'une absente -> 400.
    3. Lecture des 3 séries (``mesures_ressource``, courantes) ; alignement par
       **intersection des dates** (fenêtre effective = overlap PM ∩ pluie, bornée
       par la plage des PM) ; garde-fou de contiguïté (HSU path-dependant).
    4. Modèle HSU (pvlib) sur la fenêtre complète depuis le début (le spin-up n'est
       amorti qu'une fois) ; tilt / seuil de nettoyage = défauts F1 documentés.
    """
    serie = _resoudre_serie_source(session, code_serie_source)
    _exiger_grandeur(serie.grandeur_code, "pm2_5", code_serie_source, "taux_salissure_proxy")
    _exiger_serie_journaliere(serie, code_serie_source, "taux_salissure_proxy")

    pm10_serie_id = _chercher_serie_compagne(session, serie, "pm10")
    pluie_serie_id = _chercher_serie_pluie_salissure(
        session, serie.localite_id, serie.periode_debut, serie.periode_fin
    )
    if pm10_serie_id is None or pluie_serie_id is None:
        raise ExceptionKuma(
            code=CodeErreur.INCOMPATIBILITE_SOURCE_GRANDEUR,
            message=(
                "Le proxy de salissure (HSU) exige la compagne PM10 (meme source EAC4) "
                "et la serie de precipitation journaliere (source "
                f"{SOURCE_PLUIE_SALISSURE}) pour la localite de {code_serie_source!r} ; "
                "au moins une est absente."
            ),
            statut_http=status.HTTP_400_BAD_REQUEST,
        )

    pm2_5 = _lire_mesures_par_serie_id(
        session, serie.serie_id, _FENETRE_LARGE_DEBUT, _FENETRE_LARGE_FIN
    )
    pm10 = _lire_mesures_par_serie_id(
        session, pm10_serie_id, _FENETRE_LARGE_DEBUT, _FENETRE_LARGE_FIN
    )
    pluie = _lire_mesures_par_serie_id(
        session, pluie_serie_id, _FENETRE_LARGE_DEBUT, _FENETRE_LARGE_FIN
    )

    dates = sorted(pm2_5.keys() & pm10.keys() & pluie.keys())
    _verifier_contiguite_journaliere(dates, code_serie_source)

    entrees: list[MesureEntreeSoiling] = [
        {
            "instant_mesure": jour,
            "rainfall_mm": pluie[jour],
            "pm2_5": pm2_5[jour],
            "pm10": pm10[jour],
        }
        for jour in dates
    ]
    resultat = calculer_taux_salissure_proxy(entrees)
    periode = f"{dates[0].isoformat()}/{dates[-1].isoformat()}" if dates else "aucune"

    return ReponseTauxSalissureProxy(
        code_serie_source=code_serie_source,
        code_localite=serie.localite_code,
        periode=periode,
        surface_tilt_deg=SURFACE_TILT_DEFAUT,
        cleaning_threshold_mm=CLEANING_THRESHOLD_DEFAUT_MM,
        mesures=resultat.mesures,
        limite=resultat.limite,
    )


# === Endpoint pr_realiste (F1 calculee_volee, PR réaliste saisonnier) =======


def _chercher_serie_pm_cams(session: Session, localite_id: int, grandeur_code: str) -> int | None:
    """Résout une série PM (``pm2_5`` / ``pm10``) journalière EAC4 d'une localité.

    Résolveur **cross-source dédié** : les PM sont ``cams_eac4``, source différente du
    GHI source (typiquement ``nasa_power``) ; ``_chercher_serie_compagne`` filtre sur
    ``source_id`` et les raterait. **Symétrique** du ``_chercher_serie_pluie_salissure``,
    mais en sens inverse : ici c'est la PM qui est cross-source (la pluie
    l'était dans l'autre résolveur). Source épinglée explicitement, ordre stable.
    """
    row = session.execute(
        text(
            """
            SELECT sm.id FROM series_metadonnees sm
            JOIN sources s ON s.id = sm.source_id
            WHERE sm.localite_id = :localite_id
              AND s.code = 'cams_eac4'
              AND sm.grandeur_code = :grandeur_code
              AND sm.granularite = 'journalier'
              AND sm.actif = TRUE
            ORDER BY sm.periode_debut, sm.id
            LIMIT 1
            """
        ),
        {"localite_id": localite_id, "grandeur_code": grandeur_code},
    ).first()
    return int(row.id) if row else None


@routeur.get(
    "/pr_realiste/{code_serie_source}",
    response_model=ReponsePRRealiste,
    status_code=status.HTTP_200_OK,
    summary="PR realiste saisonnier (PR effectif site-specifique, journalier + mensuel)",
    tags=["grandeurs-F1"],
)
def grandeur_pr_realiste(
    code_serie_source: str,
    params: Annotated[ParametresPRRealiste, Depends()],
    _cle: CleApiValidee,
    session: Annotated[Session, Depends(obtenir_session)],
) -> ReponsePRRealiste:
    """PR effectif = ``PR_fourni x ratio_T x (1 - salissure)`` selon le mode, à la volée.

    Source = série **GHI journalière** (fournit G + l'index de dates ; 400 si grandeur
    != ghi ou granularité != journalier). Compagnes selon le mode : T2M (même source
    et granularité que le GHI), pluie GPM IMERG (``SOURCE_PLUIE_SALISSURE``, ADR-0033)
    et PM2.5/PM10 (cross-source EAC4). Alignement par
    intersection des séries du mode ; la fenêtre effective diverge donc par mode (les
    modes salissure sont bornés à l'overlap PM EAC4), avec garde-fou de contiguïté (HSU
    path-dependant). Sorties journalier + mensuel (la courbe mensuelle = la PR
    saisonnière).
    """
    serie = _resoudre_serie_source(session, code_serie_source)
    _exiger_grandeur(serie.grandeur_code, "ghi", code_serie_source, "pr_realiste")
    _exiger_serie_journaliere(serie, code_serie_source, "pr_realiste")
    besoin_thermique = params.correction in ("temperature", "temperature_salissure")
    besoin_salissure = params.correction in ("salissure", "temperature_salissure")

    if besoin_thermique and (
        params.noct_degc is None or params.coeff_temp_pourcent_par_degc is None
    ):
        raise ExceptionKuma(
            code=CodeErreur.VALIDATION_CHAMP_MANQUANT,
            message=(
                f"correction={params.correction!r} requiert noct_degc et "
                "coeff_temp_pourcent_par_degc."
            ),
            statut_http=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    ghi = _lire_mesures_par_serie_id(
        session, serie.serie_id, _FENETRE_LARGE_DEBUT, _FENETRE_LARGE_FIN
    )
    ensembles_dates: list[set[date]] = [set(ghi.keys())]

    t2m: dict[date, float] = {}
    if besoin_thermique:
        t2m_id = _chercher_serie_compagne(session, serie, "t2m")
        if t2m_id is None:
            raise ExceptionKuma(
                code=CodeErreur.INCOMPATIBILITE_SOURCE_GRANDEUR,
                message=(
                    "La correction temperature exige une serie T2M compagne pour la "
                    f"localite de {code_serie_source!r} ; absente."
                ),
                statut_http=status.HTTP_400_BAD_REQUEST,
            )
        t2m = _lire_mesures_par_serie_id(session, t2m_id, _FENETRE_LARGE_DEBUT, _FENETRE_LARGE_FIN)
        ensembles_dates.append(set(t2m.keys()))

    pluie: dict[date, float] = {}
    pm2_5: dict[date, float] = {}
    pm10: dict[date, float] = {}
    if besoin_salissure:
        pluie_id = _chercher_serie_pluie_salissure(
            session, serie.localite_id, serie.periode_debut, serie.periode_fin
        )
        pm2_5_id = _chercher_serie_pm_cams(session, serie.localite_id, "pm2_5")
        pm10_id = _chercher_serie_pm_cams(session, serie.localite_id, "pm10")
        if pluie_id is None or pm2_5_id is None or pm10_id is None:
            raise ExceptionKuma(
                code=CodeErreur.INCOMPATIBILITE_SOURCE_GRANDEUR,
                message=(
                    "La correction salissure exige les compagnes PM2.5/PM10 (EAC4) et "
                    f"precipitation ({SOURCE_PLUIE_SALISSURE}) pour la localite de "
                    f"{code_serie_source!r} ; "
                    "au moins une est absente."
                ),
                statut_http=status.HTTP_400_BAD_REQUEST,
            )
        pluie = _lire_mesures_par_serie_id(
            session, pluie_id, _FENETRE_LARGE_DEBUT, _FENETRE_LARGE_FIN
        )
        pm2_5 = _lire_mesures_par_serie_id(
            session, pm2_5_id, _FENETRE_LARGE_DEBUT, _FENETRE_LARGE_FIN
        )
        pm10 = _lire_mesures_par_serie_id(
            session, pm10_id, _FENETRE_LARGE_DEBUT, _FENETRE_LARGE_FIN
        )
        ensembles_dates += [set(pluie.keys()), set(pm2_5.keys()), set(pm10.keys())]

    dates_communes = ensembles_dates[0]
    for autre in ensembles_dates[1:]:
        dates_communes = dates_communes & autre
    dates = sorted(dates_communes)
    _verifier_contiguite_journaliere(dates, code_serie_source)

    entrees: list[MesureJourPRRealiste] = [
        {
            "instant_mesure": jour,
            "ghi_kwh_par_m2_jour": ghi[jour] if besoin_thermique else None,
            "t_amb_degc": t2m.get(jour) if besoin_thermique else None,
            "rainfall_mm": pluie.get(jour) if besoin_salissure else None,
            "pm2_5": pm2_5.get(jour) if besoin_salissure else None,
            "pm10": pm10.get(jour) if besoin_salissure else None,
        }
        for jour in dates
    ]
    resultat = calculer_pr_realiste(
        entrees,
        pr_fourni=params.pr_fourni,
        correction=params.correction,
        noct_degc=params.noct_degc,
        gamma_pmax_pct=params.coeff_temp_pourcent_par_degc,
    )
    periode = f"{dates[0].isoformat()}/{dates[-1].isoformat()}" if dates else "aucune"

    return ReponsePRRealiste(
        code_serie_source=code_serie_source,
        code_localite=serie.localite_code,
        periode=periode,
        correction=params.correction,
        pr_fourni=params.pr_fourni,
        mesures_journalier=resultat.mesures,
        mesures_mensuel=agreger_pr_mensuel(resultat.mesures),
        limite=resultat.limite,
    )


# === Endpoint incertitude_inter_source (atlas Temps 2, F1 lecture/assemblage) ===

_AN_DEBUT_ATLAS = 2021
_AN_FIN_ATLAS = 2023
_FENETRE_ATLAS_STR = "2021-2023"
_GRILLE_CERES = "CERES SYN1deg (1 deg / 110 km)"


class _PaireEcartAtlas(NamedTuple):
    """Une paire d'écart inter-source candidate de la fiche.

    ``paire`` se lit « A vs B » et ``grandeur_ecart`` stocke ``(A - B) / B x 100``
    (la source de référence est au dénominateur, nommée en second) : le signe de
    ``ecart_signe_pct`` se lit donc « A plus haut que B » quand il est positif.
    """

    grandeur: Literal["ghi", "dni"]
    grandeur_ecart: str
    paire: str


# Par grandeur, la PREMIÈRE paire portant des écarts sur la fenêtre est retenue.
# Deux conventions de nommage coexistent dans le référentiel des grandeurs :
_PAIRES_ECART_ATLAS: tuple[_PaireEcartAtlas, ...] = (
    # « ecart_relatif_<g>_<src>_nasa » : (comparée - nasa) / nasa, NASA POWER référence.
    _PaireEcartAtlas("ghi", "ecart_relatif_ghi_sarah3_nasa", "PVGIS-SARAH3 vs NASA POWER"),
    _PaireEcartAtlas("dni", "ecart_relatif_dni_cams_nasa", "CAMS vs NASA POWER"),
    # Codes historiques : (nasa - ref) / ref, la référence satellite au dénominateur.
    _PaireEcartAtlas("ghi", "ecart_relatif_referentiel", "NASA POWER vs PVGIS-SARAH3"),
    _PaireEcartAtlas("dni", "ecart_relatif_dni_cams", "NASA POWER vs CAMS"),
)


def _mediane_abs(valeurs: Sequence[float]) -> float:
    """Médiane des valeurs absolues (pur). ``valeurs`` non vide (garanti par l'appelant)."""
    absolues = sorted(abs(v) for v in valeurs)
    n = len(absolues)
    milieu = n // 2
    if n % 2 == 1:
        return absolues[milieu]
    return (absolues[milieu - 1] + absolues[milieu]) / 2.0


def _lire_ecart_paire_recent(
    session: Session, code_localite: str, grandeur_ecart: str
) -> tuple[list[float], list[tuple[str, str | None]]]:
    """Lit les écarts mensuels RECENTS (2021-2023) d'une (localité, grandeur d'écart).

    Filtre ``annee_debut`` dans 2021-2023 : isole la fenêtre récente commune aux
    paires (anti-mélange de fenêtres). Renvoie ``(valeurs_signees, niveaux)`` sur
    les mois non-NULL, ou ``([], [])`` si aucune (localité hors atlas).
    """
    rows = session.execute(
        text(
            """
            SELECT gm.valeur, gm.niveau_confiance_derive AS derive,
                   gm.niveau_confiance_override AS override
            FROM grandeurs_metier gm
            JOIN localites l ON l.id = gm.localite_id
            WHERE l.code = :loc AND gm.grandeur_code = :g
              AND gm.periode_type = 'mensuel'
              AND gm.annee_debut BETWEEN :a1 AND :a2
              AND gm.valide_au IS NULL
            ORDER BY gm.annee_debut, gm.mois
            """
        ),
        {"loc": code_localite, "g": grandeur_ecart, "a1": _AN_DEBUT_ATLAS, "a2": _AN_FIN_ATLAS},
    ).all()
    valeurs = [float(r.valeur) for r in rows if r.valeur is not None]
    niveaux = [(str(r.derive), r.override) for r in rows if r.valeur is not None]
    return valeurs, niveaux


def _lire_ecarts_atlas(
    session: Session, code_localite: str
) -> tuple[list[EcartPaireInterSource], list[tuple[str, str | None]]]:
    """Écarts agrégés de la fiche : une paire par grandeur (première portant des écarts)."""
    ecarts: list[EcartPaireInterSource] = []
    niveaux: list[tuple[str, str | None]] = []
    grandeurs_couvertes: set[str] = set()
    for paire in _PAIRES_ECART_ATLAS:
        if paire.grandeur in grandeurs_couvertes:
            continue
        valeurs, niv = _lire_ecart_paire_recent(session, code_localite, paire.grandeur_ecart)
        if not valeurs:
            continue
        grandeurs_couvertes.add(paire.grandeur)
        ecarts.append(
            EcartPaireInterSource(
                grandeur=paire.grandeur,
                paire=paire.paire,
                ecart_abs_pct=round(_mediane_abs(valeurs), 4),
                ecart_signe_pct=round(sum(valeurs) / len(valeurs), 4),
                n_mois=len(valeurs),
            )
        )
        niveaux += niv
    return ecarts, niveaux


def _lire_degenerescence_localite(
    session: Session, code_localite: str
) -> tuple[DegenerescenceFiche | None, list[tuple[str, str | None]]]:
    """Lit la dégénérescence matérialisée niveau-localité (grille NASA CERES, série ghi).

    GHI et DNI partagent la grille CERES -> la ligne rattachée à la série
    ``nasa_power`` + ``ghi`` **mensuelle** est représentative ; ordre déterministe
    si plusieurs (début le plus récent, puis ``id``). Renvoie ``(fiche, niveaux)``,
    ou ``(None, [])`` si la grandeur n'est pas matérialisée pour la localité.
    """
    row = session.execute(
        text(
            """
            SELECT gm.valeur, gm.commentaire_editorial AS note,
                   gm.niveau_confiance_derive AS derive,
                   gm.niveau_confiance_override AS override
            FROM grandeurs_metier gm
            JOIN localites l ON l.id = gm.localite_id
            JOIN series_metadonnees sm ON sm.id = gm.series_metadonnees_id
            JOIN sources s ON s.id = sm.source_id
            WHERE l.code = :loc AND gm.grandeur_code = 'degenerescence_pixel'
              AND s.code = 'nasa_power' AND sm.grandeur_code = 'ghi'
              AND sm.granularite = 'mensuel'
              AND gm.valide_au IS NULL
            ORDER BY sm.periode_debut DESC, sm.id, gm.id
            """
        ),
        {"loc": code_localite},
    ).first()
    if row is None or row.valeur is None:
        return None, []
    fiche = DegenerescenceFiche(
        n_jumeaux=int(row.valeur), grille=_GRILLE_CERES, note=str(row.note or "")
    )
    return fiche, [(str(row.derive), row.override)]


def _degenerescence_detectee(
    code_localite: str, jumeaux_pixel: dict[str, list[str]]
) -> tuple[DegenerescenceFiche | None, list[tuple[str, str | None]]]:
    """Dégénérescence établie à la lecture quand elle n'est pas matérialisée.

    ``jumeaux_pixel`` = ``_jumeaux_pixel_nasa_ghi`` (identité exacte des séries GHI
    NASA POWER mensuelles 1991-2020, méthode de la grandeur ``degenerescence_pixel``) :
    un test d'égalité sur la donnée brute, pas un calcul de substrat. Confiance B
    (fait structurel exact, mais A est réservée à la mesure terrain). ``(None, [])``
    si la localité n'a pas de série GHI NASA POWER mensuelle climatologique.
    """
    if code_localite not in jumeaux_pixel:
        return None, []
    jumeaux = jumeaux_pixel[code_localite]
    periode = f"{ANNEE_DEBUT_CLIMATOLOGIE}-{ANNEE_FIN_CLIMATOLOGIE}"
    if jumeaux:
        note = (
            f"Degenerescence de pixel detectee a la lecture : partage la cellule "
            f"{_GRILLE_CERES} avec {len(jumeaux)} autre(s) point(s) ({', '.join(jumeaux)}). "
            f"Series GHI NASA POWER mensuelles {periode} strictement identiques (meme pixel "
            "source) -> ne pas presenter comme des mesures independantes."
        )
    else:
        note = (
            f"Point resolu sur {_GRILLE_CERES} : aucune autre localite ne partage sa serie "
            f"GHI NASA POWER mensuelle {periode} (detection a la lecture)."
        )
    fiche = DegenerescenceFiche(n_jumeaux=len(jumeaux), grille=_GRILLE_CERES, note=note)
    return fiche, [("B", None)]


def _assurer_confiance_b(
    niveaux: Sequence[tuple[str, str | None]], code_localite: str
) -> Literal["B"]:
    """Confiance effective (override sinon derive). Exige ``{'B'}``, sinon 500.

    Garde d'honnêteté (au lieu d'un 'B' codé en dur) : si une ligne écart/dégénérescence
    n'est pas B, la fiche ne doit JAMAIS afficher B -> 500 explicite (la donnée a dérivé).
    """
    effectifs = {(override if override is not None else derive) for derive, override in niveaux}
    if effectifs != {"B"}:
        raise ExceptionKuma(
            code=CodeErreur.SERVEUR_ERREUR_INTERNE,
            message=(
                f"Incoherence de confiance pour {code_localite!r} : la fiche inter-source "
                f"attend des donnees en confiance B, trouve {sorted(effectifs)}. "
                "L'atlas est inter-source (B) ; A est reserve a la mesure terrain."
            ),
            statut_http=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return "B"


def _construire_limite_incertitude_inter_source(ecarts: Sequence[EcartPaireInterSource]) -> str:
    """Avertissement éditorial anti-survente (paires effectivement exposées)."""
    paires = " ; ".join(f"{e.grandeur.upper()} : {e.paire}" for e in ecarts)
    return (
        f"Incertitude inter-source / relative : divergence entre sources satellitaires "
        f"({paires} ; ecart signe = (A - B) / B pour la paire 'A vs B'), fenetre "
        f"{_FENETRE_ATLAS_STR}, confiance B. Ne quantifie PAS l'incertitude absolue vs "
        "mesure sol (regime terrain) : ce n'est pas une barre d'erreur calibree au sol."
    )


def _assembler_fiche(
    session: Session,
    code_localite: str,
    jumeaux_pixel: dict[str, list[str]] | None,
) -> tuple[list[EcartPaireInterSource], DegenerescenceFiche, list[tuple[str, str | None]]] | None:
    """Écarts + dégénérescence + niveaux d'une localité ; ``None`` si aucun écart.

    La dégénérescence matérialisée est lue en priorité ; à défaut elle est
    détectée à la lecture (``jumeaux_pixel`` calculé à la demande si ``None``).

    Raises:
        ExceptionKuma : HTTP 500 si des écarts existent sans dégénérescence
            matérialisée ni série GHI NASA POWER climatologique (incohérence).
    """
    ecarts, niveaux = _lire_ecarts_atlas(session, code_localite)
    if not ecarts:
        return None
    degenerescence, niv_degen = _lire_degenerescence_localite(session, code_localite)
    if degenerescence is None:
        if jumeaux_pixel is None:
            jumeaux_pixel = _jumeaux_pixel_nasa_ghi(session)
        degenerescence, niv_degen = _degenerescence_detectee(code_localite, jumeaux_pixel)
    if degenerescence is None:
        raise ExceptionKuma(
            code=CodeErreur.SERVEUR_ERREUR_INTERNE,
            message=(
                f"Incoherence : ecart inter-source present pour {code_localite!r} mais "
                "degenerescence_pixel (NASA/ghi) ni materialisee ni detectable (pas de "
                "serie GHI NASA POWER mensuelle climatologique)."
            ),
            statut_http=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return ecarts, degenerescence, niveaux + niv_degen


@routeur.get(
    "/incertitude_inter_source/{code_localite}",
    response_model=ReponseIncertitudeInterSource,
    status_code=status.HTTP_200_OK,
    summary="Fiche d'incertitude inter-source (ecart + degenerescence de pixel)",
    tags=["grandeurs-F1"],
)
def grandeur_incertitude_inter_source(
    code_localite: str,
    _cle: CleApiValidee,
    session: Annotated[Session, Depends(obtenir_session)],
) -> ReponseIncertitudeInterSource:
    """Assemble en LECTURE la fiche d'incertitude inter-source d'une localité (atlas Temps 2).

    Deux axes d'honnêteté DISTINCTS, non fusionnés :

    - ``ecarts`` : écart inter-source par paire/grandeur (GHI : NASA POWER et
      PVGIS-SARAH3 ; DNI : NASA POWER et CAMS ; fenêtre récente 2021-2023), lu dans
      les écarts matérialisés. ``ecart_abs_pct`` (médiane des |écarts|) = signal
      primaire ; ``ecart_signe_pct`` orientationnel seulement, signe selon la paire
      « A vs B » = ``(A - B) / B``.
    - ``degenerescence`` : propriété niveau-localité (grille NASA CERES), rendue une
      fois ; lue si matérialisée, sinon détectée à la lecture (identité exacte des
      séries GHI NASA POWER mensuelles 1991-2020).

    Zéro calcul de substrat. Confiance B lue et assérée (jamais A : A = terrain).
    404 si la localité ne porte aucun écart inter-source sur la fenêtre.
    """
    fiche = _assembler_fiche(session, code_localite, jumeaux_pixel=None)
    if fiche is None:
        raise ExceptionKuma(
            code=CodeErreur.RESSOURCE_LOCALITE_INCONNUE,
            message=(
                f"Localite {code_localite!r} non couverte par l'atlas d'incertitude "
                f"inter-source : aucun ecart inter-source materialise sur {_FENETRE_ATLAS_STR}."
            ),
            statut_http=status.HTTP_404_NOT_FOUND,
        )
    ecarts, degenerescence, niveaux = fiche
    return ReponseIncertitudeInterSource(
        code_localite=code_localite,
        fenetre=_FENETRE_ATLAS_STR,
        ecarts=ecarts,
        degenerescence=degenerescence,
        niveau_confiance=_assurer_confiance_b(niveaux, code_localite),
        limite=_construire_limite_incertitude_inter_source(ecarts),
    )


def _lister_points_atlas(session: Session) -> list[tuple[int, str]]:
    """(localite_id, code) des points portant l'écart inter-source récent = périmètre atlas.

    Data-driven : les localités ayant un écart 2021-2023 pour l'une des paires de
    ``_PAIRES_ECART_ATLAS``. Robuste à une densification future (la liste suit la
    donnée, pas une énumération figée).
    """
    rows = session.execute(
        text(
            """
            SELECT DISTINCT l.id, l.code
            FROM grandeurs_metier gm
            JOIN localites l ON l.id = gm.localite_id
            WHERE gm.grandeur_code = ANY(:codes)
              AND gm.periode_type = 'mensuel'
              AND gm.annee_debut BETWEEN :a1 AND :a2
              AND gm.valeur IS NOT NULL AND gm.valide_au IS NULL
            ORDER BY l.code
            """
        ),
        {
            "codes": [p.grandeur_ecart for p in _PAIRES_ECART_ATLAS],
            "a1": _AN_DEBUT_ATLAS,
            "a2": _AN_FIN_ATLAS,
        },
    ).all()
    return [(int(r.id), str(r.code)) for r in rows]


def _assembler_fiche_point(
    session: Session,
    localite_id: int,
    code_localite: str,
    jumeaux_pixel: dict[str, list[str]] | None = None,
) -> FichePointIncertitude:
    """Assemble la fiche d'un point de l'atlas (fiche Temps 2 + coordonnées), pour la collection.

    Réutilise les mêmes helpers que l'endpoint par-localité (deux axes distincts, confiance B
    lue + assérée, limite éditoriale). Lève 500 sur incohérence (un point du périmètre sans écart ou
    sans dégénérescence ne devrait pas exister).
    """
    fiche = _assembler_fiche(session, code_localite, jumeaux_pixel)
    if fiche is None:
        raise ExceptionKuma(
            code=CodeErreur.SERVEUR_ERREUR_INTERNE,
            message=(
                f"Incoherence collection atlas : point {code_localite!r} sans ecart "
                "(devrait etre garanti par le perimetre data-driven)."
            ),
            statut_http=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    ecarts, degenerescence, niveaux = fiche
    latitude, longitude = _resoudre_coordonnees(session, localite_id)
    return FichePointIncertitude(
        code_localite=code_localite,
        fenetre=_FENETRE_ATLAS_STR,
        ecarts=ecarts,
        degenerescence=degenerescence,
        niveau_confiance=_assurer_confiance_b(niveaux, code_localite),
        limite=_construire_limite_incertitude_inter_source(ecarts),
        latitude_deg=latitude,
        longitude_deg=longitude,
    )


@routeur.get(
    "/incertitude_inter_source",
    response_model=ReponseIncertitudeInterSourceCollection,
    status_code=status.HTTP_200_OK,
    summary="Collection des fiches d'incertitude inter-source (points de l'atlas)",
    tags=["grandeurs-F1"],
)
def grandeur_incertitude_inter_source_collection(
    _cle: CleApiValidee,
    session: Annotated[Session, Depends(obtenir_session)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ReponseIncertitudeInterSourceCollection:
    """Toutes les fiches d'incertitude inter-source des points de l'atlas, paginées.

    Un appel pour le snapshot média (carte) au lieu de N. Chaque item = la MÊME fiche
    que l'endpoint par-localité (deux axes distincts, B, limite éditoriale) + lat/lon.
    Lecture/assemblage des écarts déjà matérialisés + dégénérescence (matérialisée ou
    détectée à la lecture, une seule détection pour la page), zéro substrat.
    Enveloppe paginée identique à /v1/series (items / total / limit / offset).
    """
    points = _lister_points_atlas(session)
    total = len(points)
    page = points[offset : offset + limit]
    jumeaux_pixel = _jumeaux_pixel_nasa_ghi(session) if page else {}
    items = [_assembler_fiche_point(session, loc_id, code, jumeaux_pixel) for loc_id, code in page]
    return ReponseIncertitudeInterSourceCollection(
        items=items, total=total, limit=limit, offset=offset
    )
