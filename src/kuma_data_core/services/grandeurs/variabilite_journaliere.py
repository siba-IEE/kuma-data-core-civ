"""Calcul `variabilite_journaliere` (coefficient de variation annuel du GHI)
- couche service.

Module orchestrant le calcul de la grandeur Kuma F1 stockée
`variabilite_journaliere` à partir de la série GHI courante. Périodicité
**annuelle uniquement** (CoV statistiquement non robuste sur 28-31 jours).

Définition :

```
CoV(annee) := sigma(GHI_jour sur annee) / μ(GHI_jour sur annee)
```

Coefficient de variation sans dimension. CoV 0.2 pour climat très
stable (équatorial humide), CoV 0.5 pour climat très variable
(transition saisons).

Politique de complétude stricte 100% jours civils v1 sur la série GHI
amont (héritée de HEP).
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

GRANDEUR_CODE_VARIABILITE: str = "variabilite_journaliere"
METHODE_COLLECTE_VARIABILITE: str = "calcul_derive"
GRANDEUR_CODE_GHI: str = "ghi"


class CalculVariabiliteResultat(TypedDict):
    """Résultat d'un appel à :func:`calculer_et_inserer_variabilite_journaliere`."""

    code_serie_variabilite: str
    nb_annuel_insere: int
    annees_traitees: tuple[int, ...]
    annees_skip_completude: tuple[int, ...]


class _LigneAgregeeVariabilite(TypedDict):
    periode_type: str
    annee_debut: int
    annee_fin: int
    mois: int | None
    valeur: float


class _AgregationResultat(TypedDict):
    lignes_annuelles: list[_LigneAgregeeVariabilite]
    annees_traitees: tuple[int, ...]
    annees_skip_completude: tuple[int, ...]


def _calculer_coefficient_variation(valeurs: Sequence[float]) -> float:
    """Coefficient de variation `sigma / μ` (échantillon, ddof=0).

    Args:
        valeurs : séquence non vide de valeurs (typiquement GHI journalier).

    Returns:
        CoV sans dimension. 0.0 si toutes les valeurs sont identiques.

    Raises:
        ValueError : séquence vide ou moyenne <= 0 (CoV non défini).
    """
    n = len(valeurs)
    if n == 0:
        raise ValueError("Sequence vide, CoV non defini.")
    moyenne = sum(valeurs) / n
    if moyenne <= 0:
        raise ValueError(
            f"Moyenne <= 0 ({moyenne}), CoV non defini (division par zero ou negatif)."
        )
    variance = sum((v - moyenne) ** 2 for v in valeurs) / n
    return float((variance**0.5) / moyenne)


def _agreger_variabilite_journaliere(
    mesures_ghi: Sequence[tuple[date, float]],
) -> _AgregationResultat:
    """Agrège GHI journalier en CoV annuel.

    Fonction pure (aucune I/O). Politique de complétude stricte 100%
    jours civils v1.

    Args:
        mesures_ghi : séquence de (date, GHI en kWh/m²/j).

    Returns:
        :class:`_AgregationResultat` avec 1 ligne annuelle par année
        complète. Pas de mensuel (CoV non robuste sur 28-31 jours).
    """
    par_annee: dict[int, list[float]] = defaultdict(list)
    for d, v in mesures_ghi:
        par_annee[d.year].append(v)

    lignes_annuelles: list[_LigneAgregeeVariabilite] = []
    annees_skip: list[int] = []

    for annee, valeurs in sorted(par_annee.items()):
        n_attendu = 366 if calendar.isleap(annee) else 365
        if len(valeurs) != n_attendu:
            annees_skip.append(annee)
            continue
        try:
            cov = _calculer_coefficient_variation(valeurs)
        except ValueError:
            annees_skip.append(annee)
            continue
        lignes_annuelles.append(
            {
                "periode_type": "annuel",
                "annee_debut": annee,
                "annee_fin": annee,
                "mois": None,
                "valeur": cov,
            }
        )

    return {
        "lignes_annuelles": lignes_annuelles,
        "annees_traitees": tuple(sorted(par_annee.keys())),
        "annees_skip_completude": tuple(annees_skip),
    }


def calculer_et_inserer_variabilite_journaliere(
    *,
    session: Session,
    code_serie_variabilite: str,
    code_serie_ghi_amont: str,
    version_formule: int = 1,
) -> CalculVariabiliteResultat:
    """Calcule variabilite_journaliere annuelle et insère dans grandeurs_metier.

    Lit GHI journalier, calcule le CoV annuel, et bulk-insère 1 ligne
    annuelle par année complète. Pas de ligne mensuelle (CoV non robuste
    sur 28-31 jours).

    Args:
        session : session SQLAlchemy active.
        code_serie_variabilite : code naturel de la série cible.
        code_serie_ghi_amont : code naturel de la série GHI amont.
        version_formule : version de formule en cours (défaut 1).

    Returns:
        :class:`CalculVariabiliteResultat`.

    Raises:
        RuntimeError : voir docstrings symétriques du module fraction_diffuse.
    """
    # 1. Vérifier alignement version_formule
    version_actuelle = session.execute(
        text("SELECT version_formule_actuelle FROM grandeurs_referentiel WHERE code = :code"),
        {"code": GRANDEUR_CODE_VARIABILITE},
    ).scalar()
    if version_actuelle is None:
        raise RuntimeError(
            f"Grandeur {GRANDEUR_CODE_VARIABILITE!r} introuvable dans grandeurs_referentiel."
        )
    if version_formule != int(version_actuelle):
        raise RuntimeError(
            f"Desalignement version_formule : argument={version_formule}, "
            f"version_formule_actuelle pour {GRANDEUR_CODE_VARIABILITE!r}={int(version_actuelle)}."
        )

    # 2. Série cible
    serie_cible = session.execute(
        text(
            """
            SELECT sm.id AS serie_id, sm.localite_id, sm.grandeur_code,
                   sm.methode_collecte, s.fiabilite AS fiabilite_source
            FROM series_metadonnees sm
            JOIN sources s ON s.id = sm.source_id
            WHERE sm.code = :code
            """
        ),
        {"code": code_serie_variabilite},
    ).first()
    if serie_cible is None:
        raise RuntimeError(
            f"Serie variabilite_journaliere cible {code_serie_variabilite!r} introuvable."
        )
    if serie_cible.grandeur_code != GRANDEUR_CODE_VARIABILITE:
        raise RuntimeError(
            f"Serie cible {code_serie_variabilite!r} : grandeur_code="
            f"{serie_cible.grandeur_code!r}, attendu {GRANDEUR_CODE_VARIABILITE!r}."
        )
    if serie_cible.methode_collecte != METHODE_COLLECTE_VARIABILITE:
        raise RuntimeError(
            f"Serie cible {code_serie_variabilite!r} : methode_collecte="
            f"{serie_cible.methode_collecte!r}, attendu {METHODE_COLLECTE_VARIABILITE!r}."
        )

    # 3. Série GHI amont
    serie_ghi = session.execute(
        text(
            "SELECT id AS serie_id, localite_id, grandeur_code "
            "FROM series_metadonnees WHERE code = :code"
        ),
        {"code": code_serie_ghi_amont},
    ).first()
    if serie_ghi is None:
        raise RuntimeError(f"Serie GHI amont {code_serie_ghi_amont!r} introuvable.")
    if serie_ghi.grandeur_code != GRANDEUR_CODE_GHI:
        raise RuntimeError(
            f"Serie {code_serie_ghi_amont!r} : grandeur_code="
            f"{serie_ghi.grandeur_code!r}, attendu {GRANDEUR_CODE_GHI!r}."
        )

    # 4. Cohérence localite
    localite_cible = int(serie_cible.localite_id)
    if int(serie_ghi.localite_id) != localite_cible:
        raise RuntimeError(
            f"Incoherence localite : serie cible {code_serie_variabilite!r} "
            f"localite_id={localite_cible} vs serie GHI amont "
            f"{code_serie_ghi_amont!r} localite_id={int(serie_ghi.localite_id)}."
        )

    # 5. Niveau de confiance
    niveau_derive = calculer_niveau_confiance_derive(
        methode_collecte=serie_cible.methode_collecte,
        fiabilite_source=serie_cible.fiabilite_source,
    )

    # 6. Lecture mesures GHI
    rows_ghi = session.execute(
        text(
            """
            SELECT instant_mesure, valeur FROM mesures_ressource
            WHERE serie_id = :serie_id AND valide_au IS NULL AND statut <> 'deprecie'
            ORDER BY instant_mesure
            """
        ),
        {"serie_id": int(serie_ghi.serie_id)},
    ).all()
    mesures_ghi: list[tuple[date, float]] = [(r.instant_mesure, float(r.valeur)) for r in rows_ghi]

    # 7. Agrégation pure
    agregation = _agreger_variabilite_journaliere(mesures_ghi)

    # 8. Bulk INSERT
    if agregation["lignes_annuelles"]:
        params: list[dict[str, Any]] = [
            {
                "grandeur_code": GRANDEUR_CODE_VARIABILITE,
                "localite_id": localite_cible,
                "series_metadonnees_id": int(serie_cible.serie_id),
                "periode_type": ligne["periode_type"],
                "annee_debut": ligne["annee_debut"],
                "annee_fin": ligne["annee_fin"],
                "mois": ligne["mois"],
                "version_formule": version_formule,
                "valeur": ligne["valeur"],
                "niveau_confiance_derive": niveau_derive,
            }
            for ligne in agregation["lignes_annuelles"]
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
        "code_serie_variabilite": code_serie_variabilite,
        "nb_annuel_insere": len(agregation["lignes_annuelles"]),
        "annees_traitees": agregation["annees_traitees"],
        "annees_skip_completude": agregation["annees_skip_completude"],
    }
