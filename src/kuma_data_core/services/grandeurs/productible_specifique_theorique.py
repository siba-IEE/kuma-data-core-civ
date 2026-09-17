"""Calcul `productible_specifique_theorique` (HEP * PR_théorique).

Module orchestrant le calcul de la grandeur Kuma F1 stockée
`productible_specifique_theorique` à partir d'une série amont `hep`
(déjà calculée dans `grandeurs_metier`) multipliée par un coefficient
de Performance Ratio théorique.

Définition :

```
productible_specifique_theorique(periode) := hep(periode) * pr_theorique
```

`pr_theorique` par défaut = **0.8** (industry-standard conservateur,
cohérent IEC 61724-1, NREL PVWatts 0.84).

**Premier module consommant `grandeurs_metier` amont** (pas
`mesures_ressource`) : un calcul Kuma peut consommer une grandeur Kuma
déjà calculée. Cohérent avec le mapping
`methode_collecte='calcul_derive'` + source `kuma_calculs`. Pas de
relecture des mesures GHI journalières - agrégats annuels/mensuels
hérités directement de `hep`.

Pas de politique de complétude propre : la complétude est héritée de
`hep` (filtrée par sa propre politique de complétude). Si `hep` est
absent pour une (localite, annee), `productible_specifique_theorique`
l'est aussi par construction.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypedDict

from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.editorial.niveaux_confiance import (
    calculer_niveau_confiance_derive,
)

GRANDEUR_CODE_PRODUCTIBLE: str = "productible_specifique_theorique"
METHODE_COLLECTE_PRODUCTIBLE: str = "calcul_derive"
GRANDEUR_CODE_HEP: str = "hep"

PR_THEORIQUE_DEFAUT: float = 0.8
"""Performance Ratio théorique par défaut. Valeur conservatrice cohérente
IEC 61724-1 et pratiques bureaux d'études."""


class CalculProductibleResultat(TypedDict):
    """Résultat d'un appel à :func:`calculer_et_inserer_productible_specifique_theorique`."""

    code_serie_productible: str
    nb_annuel_insere: int
    nb_mensuel_insere: int
    pr_theorique_applique: float


class _LigneAgregeeProductible(TypedDict):
    periode_type: str
    annee_debut: int
    annee_fin: int
    mois: int | None
    valeur: float


def _appliquer_pr_theorique(valeur_hep: float, pr_theorique: float) -> float:
    """Applique le coefficient PR théorique à une valeur HEP.

    Args:
        valeur_hep : HEP en h_eq (numériquement équivalent kWh/m²/j * N_jours).
        pr_theorique : Performance Ratio théorique sans dimension (typique 0.8).

    Returns:
        Productible spécifique théorique en kWh/kWc (numérique). À 1 kW/m² STC,
        l'unité h_eq de HEP est équivalente à kWh/kWc.
    """
    return float(valeur_hep) * float(pr_theorique)


def calculer_et_inserer_productible_specifique_theorique(
    *,
    session: Session,
    code_serie_productible: str,
    code_serie_hep_amont: str,
    pr_theorique: float = PR_THEORIQUE_DEFAUT,
    version_formule: int = 1,
) -> CalculProductibleResultat:
    """Calcule productible_specifique_theorique annuel + mensuel et insère
    dans grandeurs_metier.

    Lit les lignes `hep` courantes (annuel + mensuel) de la série amont,
    multiplie par `pr_theorique`, et bulk-insère dans `grandeurs_metier`.
    Pas de relecture des mesures GHI - les périodes sont héritées de `hep`.

    Args:
        session : session SQLAlchemy active.
        code_serie_productible : code naturel de la série cible.
        code_serie_hep_amont : code naturel de la série HEP amont
            (typiquement gin_<ville>_hep_kuma_calculs_2021_2025).
        pr_theorique : Performance Ratio théorique (défaut 0.8).
        version_formule : version de formule en cours (défaut 1).

    Returns:
        :class:`CalculProductibleResultat`.

    Raises:
        RuntimeError : voir docstrings symétriques du module fraction_diffuse.
    """
    # 1. Vérifier alignement version_formule
    version_actuelle = session.execute(
        text("SELECT version_formule_actuelle FROM grandeurs_referentiel WHERE code = :code"),
        {"code": GRANDEUR_CODE_PRODUCTIBLE},
    ).scalar()
    if version_actuelle is None:
        raise RuntimeError(
            f"Grandeur {GRANDEUR_CODE_PRODUCTIBLE!r} introuvable dans grandeurs_referentiel."
        )
    if version_formule != int(version_actuelle):
        raise RuntimeError(
            f"Desalignement version_formule : argument={version_formule}, "
            f"version_formule_actuelle pour {GRANDEUR_CODE_PRODUCTIBLE!r}={int(version_actuelle)}."
        )

    # 2. Récupérer le contexte de la série cible
    serie_cible = session.execute(
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
        {"code": code_serie_productible},
    ).first()
    if serie_cible is None:
        raise RuntimeError(f"Serie productible cible {code_serie_productible!r} introuvable.")
    if serie_cible.grandeur_code != GRANDEUR_CODE_PRODUCTIBLE:
        raise RuntimeError(
            f"Serie cible {code_serie_productible!r} : grandeur_code="
            f"{serie_cible.grandeur_code!r}, attendu {GRANDEUR_CODE_PRODUCTIBLE!r}."
        )
    if serie_cible.methode_collecte != METHODE_COLLECTE_PRODUCTIBLE:
        raise RuntimeError(
            f"Serie cible {code_serie_productible!r} : methode_collecte="
            f"{serie_cible.methode_collecte!r}, attendu {METHODE_COLLECTE_PRODUCTIBLE!r}."
        )

    # 3. Récupérer la série HEP amont
    serie_hep = session.execute(
        text(
            "SELECT id AS serie_id, localite_id, grandeur_code "
            "FROM series_metadonnees WHERE code = :code"
        ),
        {"code": code_serie_hep_amont},
    ).first()
    if serie_hep is None:
        raise RuntimeError(f"Serie HEP amont {code_serie_hep_amont!r} introuvable.")
    if serie_hep.grandeur_code != GRANDEUR_CODE_HEP:
        raise RuntimeError(
            f"Serie {code_serie_hep_amont!r} : grandeur_code="
            f"{serie_hep.grandeur_code!r}, attendu {GRANDEUR_CODE_HEP!r}."
        )

    # 4. Cohérence localite
    localite_cible = int(serie_cible.localite_id)
    if int(serie_hep.localite_id) != localite_cible:
        raise RuntimeError(
            f"Incoherence localite : serie cible {code_serie_productible!r} "
            f"localite_id={localite_cible} vs serie HEP amont "
            f"{code_serie_hep_amont!r} localite_id={int(serie_hep.localite_id)}."
        )

    # 5. Niveau de confiance
    niveau_derive = calculer_niveau_confiance_derive(
        methode_collecte=serie_cible.methode_collecte,
        fiabilite_source=serie_cible.fiabilite_source,
    )

    # 6. Lire les lignes HEP courantes de la série amont (annuel + mensuel)
    # Source : grandeurs_metier (pas mesures_ressource). Filtrage version
    # courante de hep (cohérent avec la vue v_grandeurs_metier_courantes).
    rows_hep = session.execute(
        text(
            """
            SELECT
                gm.periode_type, gm.annee_debut, gm.annee_fin, gm.mois, gm.valeur
            FROM grandeurs_metier gm
            JOIN grandeurs_referentiel gr ON gr.code = gm.grandeur_code
            WHERE gm.series_metadonnees_id = :serie_id
              AND gm.grandeur_code = :grandeur_code
              AND gm.valide_au IS NULL
              AND gm.statut <> 'deprecie'
              AND gm.version_formule = gr.version_formule_actuelle
            ORDER BY gm.annee_debut, gm.mois NULLS FIRST
            """
        ),
        {
            "serie_id": int(serie_hep.serie_id),
            "grandeur_code": GRANDEUR_CODE_HEP,
        },
    ).all()

    if not rows_hep:
        raise RuntimeError(
            f"Aucune ligne HEP courante trouvee pour la serie {code_serie_hep_amont!r}. "
            "Verifier que 1-5D-iii (migration 027) a bien ete applique."
        )

    # 7. Application PR théorique + construction des lignes à insérer
    lignes_a_inserer: list[_LigneAgregeeProductible] = [
        {
            "periode_type": r.periode_type,
            "annee_debut": int(r.annee_debut),
            "annee_fin": int(r.annee_fin),
            "mois": int(r.mois) if r.mois is not None else None,
            "valeur": _appliquer_pr_theorique(float(r.valeur), pr_theorique),
        }
        for r in rows_hep
    ]

    nb_annuel = sum(1 for ligne in lignes_a_inserer if ligne["periode_type"] == "annuel")
    nb_mensuel = sum(1 for ligne in lignes_a_inserer if ligne["periode_type"] == "mensuel")

    # 8. Bulk INSERT
    params: list[dict[str, Any]] = [
        {
            "grandeur_code": GRANDEUR_CODE_PRODUCTIBLE,
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
        for ligne in lignes_a_inserer
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
        "code_serie_productible": code_serie_productible,
        "nb_annuel_insere": nb_annuel,
        "nb_mensuel_insere": nb_mensuel,
        "pr_theorique_applique": float(pr_theorique),
    }


# Re-export pour cohérence avec les autres modules services/grandeurs/
__all__: Sequence[str] = (
    "GRANDEUR_CODE_PRODUCTIBLE",
    "METHODE_COLLECTE_PRODUCTIBLE",
    "PR_THEORIQUE_DEFAUT",
    "CalculProductibleResultat",
    "_appliquer_pr_theorique",
    "calculer_et_inserer_productible_specifique_theorique",
)
