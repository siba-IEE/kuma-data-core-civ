"""Calcul HEP (Heures équivalentes pleines) - couche service.

Module orchestrant le calcul de la grandeur Kuma F1 stockée ``hep`` à partir
d'une série GHI amont (typiquement NASA POWER) et l'insertion dans
``grandeurs_metier``.

Définition opérationnelle :

- HEP_jour(t) := GHI_jour(t)   # convention 1 kWh/m²/j ↔ 1 h_eq/j à 1 kW/m² STC
- HEP_mensuel(annee, mois) := somme des HEP_jour sur tous les jours du mois
- HEP_annuel(annee) := somme des HEP_jour sur tous les jours de l'année

Politique de complétude stricte 100% jours civils v1 : aucune ligne
``grandeurs_metier`` créée pour une (annee) ou (annee, mois) qui ne
dispose pas exactement du nombre de jours civils attendus (365/366
pour une année, ``calendar.monthrange`` pour un mois). Pas d'imputation,
pas de niveau dégradé.

Architecture :

- ``_agreger_hep_journaliers`` (fonction privée pure) : agrège une séquence
  de mesures journalières en HEP annuel + mensuel selon la politique de
  complétude. Testable unitairement.
- ``calculer_et_inserer_hep`` (fonction publique) : orchestre la lecture
  SQL des mesures GHI amont, l'appel à l'agrégation pure, et l'INSERT bulk
  dans ``grandeurs_metier``. Pattern d'appel symétrique à
  ``kuma_data_core.ingestion.nasa_power_daily.ingerer_serie_daily``.

Le niveau de confiance dérivé des lignes HEP insérées est calculé via
``kuma_data_core.editorial.niveaux_confiance.calculer_niveau_confiance_derive``
(R1-R4) - cohérence pattern repo (migrations 018, 020, 022).
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from typing import Any, TypedDict

from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.editorial.niveaux_confiance import (
    calculer_niveau_confiance_derive,
)

GRANDEUR_CODE_HEP: str = "hep"
"""Code naturel de la grandeur HEP dans ``grandeurs_referentiel`` (seed 010)."""

METHODE_COLLECTE_HEP: str = "calcul_derive"
"""Methode_collecte attendue sur la série HEP cible (``calcul_derive`` →
stockage dans ``grandeurs_metier``)."""


class CalculHEPResultat(TypedDict):
    """Résultat d'un appel à :func:`calculer_et_inserer_hep`."""

    code_serie_hep: str
    nb_annuel_insere: int
    nb_mensuel_insere: int
    annees_traitees: tuple[int, ...]
    annees_skip_completude: tuple[int, ...]
    mois_skip_completude: tuple[tuple[int, int], ...]


class _LigneAgregeeHEP(TypedDict):
    """Ligne HEP agrégée (intermédiaire), avant matérialisation INSERT."""

    periode_type: str
    annee_debut: int
    annee_fin: int
    mois: int | None
    valeur: float


class _AgregationResultat(TypedDict):
    """Sortie de :func:`_agreger_hep_journaliers`."""

    lignes_annuelles: list[_LigneAgregeeHEP]
    lignes_mensuelles: list[_LigneAgregeeHEP]
    annees_traitees: tuple[int, ...]
    annees_skip_completude: tuple[int, ...]
    mois_skip_completude: tuple[tuple[int, int], ...]


def _agreger_hep_journaliers(
    mesures_journalieres: Sequence[tuple[date, float]],
) -> _AgregationResultat:
    """Agrège des mesures GHI journalières en HEP annuel + mensuel.

    Fonction pure (aucune I/O). Applique la politique de complétude
    stricte 100% jours civils v1.

    Args:
        mesures_journalieres : séquence de tuples ``(date, valeur GHI en
            kWh/m²/j)``. L'ordre n'est pas significatif.

    Returns:
        :class:`_AgregationResultat` : lignes annuelles et mensuelles
        satisfaisant la politique 100% jours civils, plus listing
        exhaustif des (année, mois) skip pour traçabilité.
    """
    valeurs_mensuelles: dict[tuple[int, int], list[float]] = defaultdict(list)
    valeurs_annuelles: dict[int, list[float]] = defaultdict(list)

    for instant, valeur in mesures_journalieres:
        valeurs_mensuelles[(instant.year, instant.month)].append(valeur)
        valeurs_annuelles[instant.year].append(valeur)

    lignes_annuelles: list[_LigneAgregeeHEP] = []
    lignes_mensuelles: list[_LigneAgregeeHEP] = []
    annees_skip: list[int] = []
    mois_skip: list[tuple[int, int]] = []

    # Agrégation mensuelle
    for (annee, mois), valeurs in sorted(valeurs_mensuelles.items()):
        n_jours_attendus = calendar.monthrange(annee, mois)[1]
        if len(valeurs) == n_jours_attendus:
            lignes_mensuelles.append(
                {
                    "periode_type": "mensuel",
                    "annee_debut": annee,
                    "annee_fin": annee,
                    "mois": mois,
                    "valeur": float(sum(valeurs)),
                }
            )
        else:
            mois_skip.append((annee, mois))

    # Agrégation annuelle
    for annee, valeurs in sorted(valeurs_annuelles.items()):
        n_jours_attendus = 366 if calendar.isleap(annee) else 365
        if len(valeurs) == n_jours_attendus:
            lignes_annuelles.append(
                {
                    "periode_type": "annuel",
                    "annee_debut": annee,
                    "annee_fin": annee,
                    "mois": None,
                    "valeur": float(sum(valeurs)),
                }
            )
        else:
            annees_skip.append(annee)

    return {
        "lignes_annuelles": lignes_annuelles,
        "lignes_mensuelles": lignes_mensuelles,
        "annees_traitees": tuple(sorted(valeurs_annuelles.keys())),
        "annees_skip_completude": tuple(annees_skip),
        "mois_skip_completude": tuple(mois_skip),
    }


def calculer_et_inserer_hep(
    *,
    session: Session,
    code_serie_hep: str,
    code_serie_ghi_amont: str,
    version_formule: int = 1,
) -> CalculHEPResultat:
    """Calcule HEP annuel + mensuel et insère dans ``grandeurs_metier``.

    Lit les mesures GHI courantes (``valide_au IS NULL``,
    ``statut <> 'deprecie'``) de la série amont, agrège par année et par
    mois selon politique de complétude 100% jours civils, et bulk-insère
    dans ``grandeurs_metier`` via la série HEP cible.

    Args:
        session : session SQLAlchemy active. La fonction add+flush mais
            ne commit pas (responsabilité du caller).
        code_serie_hep : code naturel de la série HEP calculée dans
            ``series_metadonnees`` (ex.
            ``gin_conakry_hep_kuma_calculs_2021_2025``). Doit exister
            avec ``methode_collecte='calcul_derive'`` et
            ``grandeur_code='hep'``, sinon ``RuntimeError``.
        code_serie_ghi_amont : code naturel de la série GHI amont
            (ex. ``gin_conakry_ghi_nasa_power_2021_2025``). Doit exister
            et partager la même ``localite_id`` que la série HEP cible.
        version_formule : version de formule en cours d'application
            (défaut 1). Doit matcher
            ``grandeurs_referentiel.version_formule_actuelle`` pour
            ``hep``, sinon ``RuntimeError`` (garde-fou).

    Returns:
        :class:`CalculHEPResultat` : décompte des insertions et listing
        des (années, mois) skip par politique de complétude.

    Raises:
        RuntimeError : série amont/aval introuvable, grandeur_code ou
            methode_collecte non conformes sur la série HEP cible,
            incohérence de localité entre les deux séries, ou
            désalignement de ``version_formule`` avec la version actuelle.

    Notes:
        Ne fait pas le commit. Le caller (migration ou test) doit
        appeler ``session.commit()`` ou laisser la transaction Alembic
        s'en charger.

        Pattern d'appel et de bulk INSERT SQL brut symétrique à
        :func:`kuma_data_core.ingestion.nasa_power_daily.ingerer_serie_daily`.
    """
    # 1. Vérifier l'alignement version_formule avec version_formule_actuelle
    version_actuelle = session.execute(
        text("SELECT version_formule_actuelle FROM grandeurs_referentiel WHERE code = :code"),
        {"code": GRANDEUR_CODE_HEP},
    ).scalar()
    if version_actuelle is None:
        raise RuntimeError(
            f"Grandeur {GRANDEUR_CODE_HEP!r} introuvable dans grandeurs_referentiel."
        )
    if version_formule != int(version_actuelle):
        raise RuntimeError(
            f"Desalignement version_formule : argument={version_formule}, "
            f"version_formule_actuelle pour {GRANDEUR_CODE_HEP!r}="
            f"{int(version_actuelle)}."
        )

    # 2. Récupérer le contexte de la série HEP cible (avec fiabilité de la source)
    serie_hep = session.execute(
        text(
            """
            SELECT
                sm.id AS serie_id,
                sm.localite_id,
                sm.grandeur_code,
                sm.methode_collecte,
                s.fiabilite AS fiabilite_source
            FROM series_metadonnees sm
            JOIN sources s ON s.id = sm.source_id
            WHERE sm.code = :code
            """
        ),
        {"code": code_serie_hep},
    ).first()
    if serie_hep is None:
        raise RuntimeError(
            f"Serie HEP cible {code_serie_hep!r} introuvable dans series_metadonnees."
        )
    if serie_hep.grandeur_code != GRANDEUR_CODE_HEP:
        raise RuntimeError(
            f"Serie cible {code_serie_hep!r} : grandeur_code="
            f"{serie_hep.grandeur_code!r}, attendu {GRANDEUR_CODE_HEP!r}."
        )
    if serie_hep.methode_collecte != METHODE_COLLECTE_HEP:
        raise RuntimeError(
            f"Serie cible {code_serie_hep!r} : methode_collecte="
            f"{serie_hep.methode_collecte!r}, attendu "
            f"{METHODE_COLLECTE_HEP!r}."
        )

    # 3. Récupérer le contexte de la série GHI amont
    serie_ghi = session.execute(
        text(
            """
            SELECT
                sm.id AS serie_id,
                sm.localite_id,
                sm.grandeur_code
            FROM series_metadonnees sm
            WHERE sm.code = :code
            """
        ),
        {"code": code_serie_ghi_amont},
    ).first()
    if serie_ghi is None:
        raise RuntimeError(
            f"Serie GHI amont {code_serie_ghi_amont!r} introuvable dans series_metadonnees."
        )
    if int(serie_ghi.localite_id) != int(serie_hep.localite_id):
        raise RuntimeError(
            f"Incoherence localite entre serie HEP {code_serie_hep!r} "
            f"(localite_id={int(serie_hep.localite_id)}) et serie GHI amont "
            f"{code_serie_ghi_amont!r} (localite_id={int(serie_ghi.localite_id)})."
        )

    # 4. Niveau de confiance dérivé via la couche service (R1-R4)
    niveau_derive = calculer_niveau_confiance_derive(
        methode_collecte=serie_hep.methode_collecte,
        fiabilite_source=serie_hep.fiabilite_source,
    )

    # 5. Lire les mesures GHI courantes (valide_au IS NULL, non dépréciées)
    rows_ghi = session.execute(
        text(
            """
            SELECT instant_mesure, valeur
            FROM mesures_ressource
            WHERE serie_id = :serie_id
              AND valide_au IS NULL
              AND statut <> 'deprecie'
            ORDER BY instant_mesure
            """
        ),
        {"serie_id": int(serie_ghi.serie_id)},
    ).all()
    mesures_journalieres: list[tuple[date, float]] = [
        (row.instant_mesure, float(row.valeur)) for row in rows_ghi
    ]

    # 6. Agrégation pure (politique de complétude)
    agregation = _agreger_hep_journaliers(mesures_journalieres)

    # 7. Bulk INSERT (annuelles + mensuelles, server_defaults sur statut,
    #    valide_du, niveau_confiance_override, commentaire_editorial, audit)
    toutes_lignes: list[_LigneAgregeeHEP] = list(agregation["lignes_annuelles"]) + list(
        agregation["lignes_mensuelles"]
    )
    if toutes_lignes:
        params: list[dict[str, Any]] = [
            {
                "grandeur_code": GRANDEUR_CODE_HEP,
                "localite_id": int(serie_hep.localite_id),
                "series_metadonnees_id": int(serie_hep.serie_id),
                "periode_type": ligne["periode_type"],
                "annee_debut": ligne["annee_debut"],
                "annee_fin": ligne["annee_fin"],
                "mois": ligne["mois"],
                "version_formule": version_formule,
                "valeur": ligne["valeur"],
                "niveau_confiance_derive": niveau_derive,
            }
            for ligne in toutes_lignes
        ]
        session.execute(
            text(
                """
                INSERT INTO grandeurs_metier
                    (grandeur_code, localite_id, series_metadonnees_id,
                     periode_type, annee_debut, annee_fin, mois,
                     version_formule, valeur, niveau_confiance_derive)
                VALUES
                    (:grandeur_code, :localite_id, :series_metadonnees_id,
                     :periode_type, :annee_debut, :annee_fin, :mois,
                     :version_formule, :valeur, :niveau_confiance_derive)
                """
            ),
            params,
        )
        session.flush()

    return {
        "code_serie_hep": code_serie_hep,
        "nb_annuel_insere": len(agregation["lignes_annuelles"]),
        "nb_mensuel_insere": len(agregation["lignes_mensuelles"]),
        "annees_traitees": agregation["annees_traitees"],
        "annees_skip_completude": agregation["annees_skip_completude"],
        "mois_skip_completude": agregation["mois_skip_completude"],
    }
