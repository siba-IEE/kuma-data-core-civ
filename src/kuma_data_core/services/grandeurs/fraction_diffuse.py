"""Calcul `fraction_diffuse` (ratio DHI/GHI) - couche service.

Module orchestrant le calcul de la grandeur Kuma F1 stockée
`fraction_diffuse` à partir de deux séries amont (DHI et GHI courantes
NASA POWER) et l'insertion dans `grandeurs_metier`.

Définition :

```
fraction_diffuse(annee)       := sum DHI(t) / sum GHI(t) sur t ∈ jours(annee)
fraction_diffuse(annee, mois) := sum DHI(t) / sum GHI(t) sur t ∈ jours(annee, mois)
```

Politique de complétude stricte 100% jours civils v1 : aucune ligne
créée pour une (annee) ou (annee, mois) qui n'a pas exactement le
nombre de jours civils attendus **sur les deux séries amont
simultanément** (intersection DHI ∩ GHI).

Architecture (fonctions pures + orchestrateur I/O) :

- `_agreger_fraction_diffuse` (fonction privée pure) : agrège deux
  séquences de mesures journalières en fraction_diffuse annuelle +
  mensuelle. Testable unitairement.
- `calculer_et_inserer_fraction_diffuse` (fonction publique) : orchestre
  la lecture SQL des deux séries amont (DHI et GHI), l'appel à
  l'agrégation pure, et l'INSERT bulk dans `grandeurs_metier`.

Pattern bulk INSERT SQL brut (cohérent migration 018 et module HEP).
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

GRANDEUR_CODE_FRACTION_DIFFUSE: str = "fraction_diffuse"
"""Code naturel de la grandeur dans `grandeurs_referentiel`."""

METHODE_COLLECTE_FRACTION_DIFFUSE: str = "calcul_derive"
"""Méthode attendue sur la série cible (calcul_derive → grandeurs_metier)."""

GRANDEUR_CODE_DHI: str = "dhi"
GRANDEUR_CODE_GHI: str = "ghi"


class CalculFractionDiffuseResultat(TypedDict):
    """Résultat d'un appel à :func:`calculer_et_inserer_fraction_diffuse`."""

    code_serie_fraction_diffuse: str
    nb_annuel_insere: int
    nb_mensuel_insere: int
    annees_traitees: tuple[int, ...]
    annees_skip_completude: tuple[int, ...]
    mois_skip_completude: tuple[tuple[int, int], ...]


class _LigneAgregeeFractionDiffuse(TypedDict):
    periode_type: str
    annee_debut: int
    annee_fin: int
    mois: int | None
    valeur: float


class _AgregationResultat(TypedDict):
    lignes_annuelles: list[_LigneAgregeeFractionDiffuse]
    lignes_mensuelles: list[_LigneAgregeeFractionDiffuse]
    annees_traitees: tuple[int, ...]
    annees_skip_completude: tuple[int, ...]
    mois_skip_completude: tuple[tuple[int, int], ...]


def _agreger_fraction_diffuse(
    mesures_dhi: Sequence[tuple[date, float]],
    mesures_ghi: Sequence[tuple[date, float]],
) -> _AgregationResultat:
    """Agrège DHI et GHI journaliers en fraction_diffuse annuelle + mensuelle.

    Fonction pure (aucune I/O). Politique de complétude stricte 100%
    jours civils v1 : la condition est évaluée sur l'**intersection**
    des dates présentes dans DHI et GHI.

    Args:
        mesures_dhi : séquence de (date, valeur DHI en kWh/m²/j).
        mesures_ghi : séquence de (date, valeur GHI en kWh/m²/j).

    Returns:
        :class:`_AgregationResultat` avec lignes annuelles et mensuelles
        satisfaisant la politique, plus listing des skips.

    Notes:
        Si `sum(GHI)` = 0 sur une période (cas pathologique non
        observable physiquement), la période est skipped (division par
        zéro évitée).
    """
    dhi_par_date: dict[date, float] = dict(mesures_dhi)
    ghi_par_date: dict[date, float] = dict(mesures_ghi)
    dates_communes = sorted(set(dhi_par_date) & set(ghi_par_date))

    par_mois: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)
    par_annee: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for d in dates_communes:
        couple = (dhi_par_date[d], ghi_par_date[d])
        par_mois[(d.year, d.month)].append(couple)
        par_annee[d.year].append(couple)

    lignes_annuelles: list[_LigneAgregeeFractionDiffuse] = []
    lignes_mensuelles: list[_LigneAgregeeFractionDiffuse] = []
    annees_skip: list[int] = []
    mois_skip: list[tuple[int, int]] = []

    for (annee, mois), couples in sorted(par_mois.items()):
        n_attendu = calendar.monthrange(annee, mois)[1]
        if len(couples) != n_attendu:
            mois_skip.append((annee, mois))
            continue
        somme_dhi = sum(c[0] for c in couples)
        somme_ghi = sum(c[1] for c in couples)
        if somme_ghi <= 0:
            mois_skip.append((annee, mois))
            continue
        lignes_mensuelles.append(
            {
                "periode_type": "mensuel",
                "annee_debut": annee,
                "annee_fin": annee,
                "mois": mois,
                "valeur": float(somme_dhi / somme_ghi),
            }
        )

    for annee, couples in sorted(par_annee.items()):
        n_attendu = 366 if calendar.isleap(annee) else 365
        if len(couples) != n_attendu:
            annees_skip.append(annee)
            continue
        somme_dhi = sum(c[0] for c in couples)
        somme_ghi = sum(c[1] for c in couples)
        if somme_ghi <= 0:
            annees_skip.append(annee)
            continue
        lignes_annuelles.append(
            {
                "periode_type": "annuel",
                "annee_debut": annee,
                "annee_fin": annee,
                "mois": None,
                "valeur": float(somme_dhi / somme_ghi),
            }
        )

    return {
        "lignes_annuelles": lignes_annuelles,
        "lignes_mensuelles": lignes_mensuelles,
        "annees_traitees": tuple(sorted(par_annee.keys())),
        "annees_skip_completude": tuple(annees_skip),
        "mois_skip_completude": tuple(mois_skip),
    }


def calculer_et_inserer_fraction_diffuse(
    *,
    session: Session,
    code_serie_fraction_diffuse: str,
    code_serie_dhi_amont: str,
    code_serie_ghi_amont: str,
    version_formule: int = 1,
) -> CalculFractionDiffuseResultat:
    """Calcule fraction_diffuse annuelle + mensuelle et insère dans grandeurs_metier.

    Lit les mesures courantes DHI et GHI de la même localité, agrège par
    année et mois selon politique de complétude 100% jours civils, et
    bulk-insère le ratio `sum(DHI) / sum(GHI)` dans `grandeurs_metier`.

    Args:
        session : session SQLAlchemy active. La fonction add+flush mais
            ne commit pas.
        code_serie_fraction_diffuse : code naturel de la série cible
            (ex. `gin_conakry_kaloum_fraction_diffuse_kuma_calculs_2021_2025`).
            Doit exister avec methode_collecte='calcul_derive' et
            grandeur_code='fraction_diffuse'.
        code_serie_dhi_amont : code naturel de la série DHI amont.
        code_serie_ghi_amont : code naturel de la série GHI amont.
        version_formule : version de formule en cours (défaut 1).

    Returns:
        :class:`CalculFractionDiffuseResultat`.

    Raises:
        RuntimeError : série amont/cible introuvable, grandeur_code ou
            methode_collecte non conformes, incohérence de localité
            entre les trois séries, ou désalignement version_formule.
    """
    # 1. Vérifier alignement version_formule
    version_actuelle = session.execute(
        text("SELECT version_formule_actuelle FROM grandeurs_referentiel WHERE code = :code"),
        {"code": GRANDEUR_CODE_FRACTION_DIFFUSE},
    ).scalar()
    if version_actuelle is None:
        raise RuntimeError(
            f"Grandeur {GRANDEUR_CODE_FRACTION_DIFFUSE!r} introuvable dans grandeurs_referentiel."
        )
    if version_formule != int(version_actuelle):
        raise RuntimeError(
            f"Desalignement version_formule : argument={version_formule}, "
            f"version_formule_actuelle pour {GRANDEUR_CODE_FRACTION_DIFFUSE!r}="
            f"{int(version_actuelle)}."
        )

    # 2. Récupérer le contexte de la série cible (fraction_diffuse)
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
        {"code": code_serie_fraction_diffuse},
    ).first()
    if serie_cible is None:
        raise RuntimeError(
            f"Serie fraction_diffuse cible {code_serie_fraction_diffuse!r} "
            "introuvable dans series_metadonnees."
        )
    if serie_cible.grandeur_code != GRANDEUR_CODE_FRACTION_DIFFUSE:
        raise RuntimeError(
            f"Serie cible {code_serie_fraction_diffuse!r} : grandeur_code="
            f"{serie_cible.grandeur_code!r}, attendu "
            f"{GRANDEUR_CODE_FRACTION_DIFFUSE!r}."
        )
    if serie_cible.methode_collecte != METHODE_COLLECTE_FRACTION_DIFFUSE:
        raise RuntimeError(
            f"Serie cible {code_serie_fraction_diffuse!r} : methode_collecte="
            f"{serie_cible.methode_collecte!r}, attendu "
            f"{METHODE_COLLECTE_FRACTION_DIFFUSE!r}."
        )

    # 3. Récupérer les deux séries amont (DHI et GHI)
    serie_dhi = session.execute(
        text(
            """
            SELECT id AS serie_id, localite_id, grandeur_code
            FROM series_metadonnees WHERE code = :code
            """
        ),
        {"code": code_serie_dhi_amont},
    ).first()
    if serie_dhi is None:
        raise RuntimeError(f"Serie DHI amont {code_serie_dhi_amont!r} introuvable.")
    if serie_dhi.grandeur_code != GRANDEUR_CODE_DHI:
        raise RuntimeError(
            f"Serie {code_serie_dhi_amont!r} : grandeur_code="
            f"{serie_dhi.grandeur_code!r}, attendu {GRANDEUR_CODE_DHI!r}."
        )

    serie_ghi = session.execute(
        text(
            """
            SELECT id AS serie_id, localite_id, grandeur_code
            FROM series_metadonnees WHERE code = :code
            """
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

    # 4. Vérifier cohérence localite entre les 3 séries
    localite_cible = int(serie_cible.localite_id)
    if int(serie_dhi.localite_id) != localite_cible:
        raise RuntimeError(
            f"Incoherence localite : serie cible {code_serie_fraction_diffuse!r} "
            f"localite_id={localite_cible} vs serie DHI amont "
            f"{code_serie_dhi_amont!r} localite_id={int(serie_dhi.localite_id)}."
        )
    if int(serie_ghi.localite_id) != localite_cible:
        raise RuntimeError(
            f"Incoherence localite : serie cible {code_serie_fraction_diffuse!r} "
            f"localite_id={localite_cible} vs serie GHI amont "
            f"{code_serie_ghi_amont!r} localite_id={int(serie_ghi.localite_id)}."
        )

    # 5. Niveau de confiance dérivé
    niveau_derive = calculer_niveau_confiance_derive(
        methode_collecte=serie_cible.methode_collecte,
        fiabilite_source=serie_cible.fiabilite_source,
    )

    # 6. Lire les mesures DHI et GHI courantes
    rows_dhi = session.execute(
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
        {"serie_id": int(serie_dhi.serie_id)},
    ).all()
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
    mesures_dhi: list[tuple[date, float]] = [(r.instant_mesure, float(r.valeur)) for r in rows_dhi]
    mesures_ghi: list[tuple[date, float]] = [(r.instant_mesure, float(r.valeur)) for r in rows_ghi]

    # 7. Agrégation pure
    agregation = _agreger_fraction_diffuse(mesures_dhi, mesures_ghi)

    # 8. Bulk INSERT (annuelles + mensuelles)
    toutes_lignes: list[_LigneAgregeeFractionDiffuse] = list(agregation["lignes_annuelles"]) + list(
        agregation["lignes_mensuelles"]
    )
    if toutes_lignes:
        params: list[dict[str, Any]] = [
            {
                "grandeur_code": GRANDEUR_CODE_FRACTION_DIFFUSE,
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
        "code_serie_fraction_diffuse": code_serie_fraction_diffuse,
        "nb_annuel_insere": len(agregation["lignes_annuelles"]),
        "nb_mensuel_insere": len(agregation["lignes_mensuelles"]),
        "annees_traitees": agregation["annees_traitees"],
        "annees_skip_completude": agregation["annees_skip_completude"],
        "mois_skip_completude": agregation["mois_skip_completude"],
    }
