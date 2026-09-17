"""Calcul `indicateur_qualite_donnees` (score qualité 1-5) - couche service.

Module orchestrant le calcul du score qualité (1 à 5) sur une série
brute ingérée et l'insertion d'1 ligne dans `grandeurs_metier`.

Formule v1 :

```
score_continu = 0.5 * C1 + 0.3 * C2 + 0.2 * C3

C1 = min(nb_mesures_courantes / nb_jours_attendus, 1.0)        # complétude
C2 = moyenne pondérée des niveau_confiance_derive (A=1, B=0.7, C=0.4)
C3 = mapping sources.fiabilite (haute=1, moyenne=0.7, faible=0.4)
```

Binning vers échelle 1-5 entier (intervalles fermé-ouvert sauf le
dernier) : `[0, 0.2) → 1`, `[0.2, 0.4) → 2`, `[0.4, 0.6) → 3`,
`[0.6, 0.8) → 4`, `[0.8, 1.0] → 5`.

Cas des séries brutes NASA POWER :
- `methode_collecte='modele_satellitaire'` → niveau dérivé R4 = B → C2 = 0.7.
- `sources.nasa_power.fiabilite='haute'` → C3 = 1.0.
- Score = 0.5·C1 + 0.41, plage discrétisée {3, 4, 5}.

Exception méthodologique : la ligne `grandeurs_metier` produite pointe
vers la **série évaluée** (`series_metadonnees_id = ID de la série
brute`), pas vers une série calculée propre à l'indicateur.
Conséquence : `gm.grandeur_code = 'indicateur_qualite_donnees'` ne
correspond pas à `sm.grandeur_code` de la série pointée.

Pattern fonctions pures + orchestrateur I/O : `_calculer_score`
fonction pure, `calculer_et_inserer_indicateur_qualite_donnees`
orchestrateur I/O.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict

from sqlalchemy import text
from sqlalchemy.orm import Session

GRANDEUR_CODE_INDICATEUR: str = "indicateur_qualite_donnees"
METHODE_COLLECTE_INDICATEUR: str = "calcul_derive"
SOURCE_CODE_INDICATEUR: str = "kuma_calculs"

POIDS_COMPLETUDE: float = 0.5
POIDS_CONFIANCE_MOYENNE: float = 0.3
POIDS_FIABILITE_SOURCE: float = 0.2

NIVEAU_VALEUR: dict[str, float] = {"A": 1.0, "B": 0.7, "C": 0.4}
"""Mapping niveau_confiance_derive -> valeur numerique pour la composante C2."""

FIABILITE_VALEUR: dict[str, float] = {"haute": 1.0, "moyenne": 0.7, "faible": 0.4}
"""Mapping sources.fiabilite -> valeur numerique pour la composante C3."""

BORNES_BINNING: tuple[float, ...] = (0.2, 0.4, 0.6, 0.8)
"""Bornes superieures (exclusives) des bins 1, 2, 3, 4.

Bin 5 = [0.8, 1.0] (intervalle ferme a droite, cas par defaut).
"""


class _CalculScoreResultat(TypedDict):
    c1_completude: float
    c2_confiance_moyenne: float
    c3_fiabilite_source: float
    score_continu: float
    score_discret: int


class CalculIndicateurResultat(TypedDict):
    """Resultat d'un appel a :func:`calculer_et_inserer_indicateur_qualite_donnees`."""

    code_serie_evaluee: str
    nb_lignes_inseres: int  # toujours 0 ou 1
    score_continu: float
    score_discret: int
    c1_completude: float
    c2_confiance_moyenne: float
    c3_fiabilite_source: float
    nb_mesures_courantes: int
    nb_jours_attendus: int


def _binning_score(score_continu: float) -> int:
    """Projette le score continu [0, 1] vers l'echelle discrete {1..5}.

    Intervalles ferme-ouvert pour les bins 1-4, ferme pour le bin 5
    (couvre exactement la valeur 1.0).

    Args:
        score_continu : valeur dans [0, 1].

    Returns:
        Bin entier dans {1, 2, 3, 4, 5}.
    """
    for bin_idx, borne_sup in enumerate(BORNES_BINNING, start=1):
        if score_continu < borne_sup:
            return bin_idx
    return 5


def _calculer_score(
    *,
    nb_mesures_courantes: int,
    nb_jours_attendus: int,
    niveaux_confiance: Sequence[str],
    fiabilite_source: str,
) -> _CalculScoreResultat:
    """Calcule le score qualite selon formule v1.

    Fonction pure (aucune I/O). Retourne les 3 composantes, le score
    continu et le score discret.

    Args:
        nb_mesures_courantes : nombre de mesures non depreciees
            courantes (`valide_au IS NULL AND statut <> 'deprecie'`)
            de la serie evaluee.
        nb_jours_attendus : nombre de jours civils attendus sur la
            plage (1826 sur 2021-2025).
        niveaux_confiance : sequence des `niveau_confiance_derive`
            des mesures courantes. Longueur attendue = nb_mesures_courantes.
        fiabilite_source : valeur de `sources.fiabilite` de la source
            de la serie evaluee (typiquement 'haute').

    Returns:
        :class:`_CalculScoreResultat`.
    """
    c1 = min(nb_mesures_courantes / nb_jours_attendus, 1.0) if nb_jours_attendus > 0 else 0.0

    if niveaux_confiance:
        somme_ponderee = sum(NIVEAU_VALEUR.get(n, 0.0) for n in niveaux_confiance)
        c2 = somme_ponderee / len(niveaux_confiance)
    else:
        c2 = 0.0

    c3 = FIABILITE_VALEUR.get(fiabilite_source, 0.0)

    score_continu = (
        POIDS_COMPLETUDE * c1 + POIDS_CONFIANCE_MOYENNE * c2 + POIDS_FIABILITE_SOURCE * c3
    )
    score_discret = _binning_score(score_continu)

    return {
        "c1_completude": c1,
        "c2_confiance_moyenne": c2,
        "c3_fiabilite_source": c3,
        "score_continu": score_continu,
        "score_discret": score_discret,
    }


def _nb_jours_civils_plage(annee_debut: int, annee_fin: int) -> int:
    """Compte le nombre de jours civils sur [annee_debut, annee_fin] inclusifs."""
    from datetime import date

    debut = date(annee_debut, 1, 1)
    fin = date(annee_fin, 12, 31)
    return (fin - debut).days + 1


def calculer_et_inserer_indicateur_qualite_donnees(
    *,
    session: Session,
    code_serie_evaluee: str,
    annee_debut: int = 2021,
    annee_fin: int = 2025,
    version_formule: int = 1,
) -> CalculIndicateurResultat:
    """Evalue la serie designee et insere 1 ligne grandeurs_metier.

    La ligne inseree porte `grandeur_code='indicateur_qualite_donnees'`,
    `periode_type='statique'`, `series_metadonnees_id` pointant vers
    la serie evaluee (exception methodologique).

    Args:
        session : session SQLAlchemy active.
        code_serie_evaluee : code naturel de la serie a evaluer
            (typiquement une serie brute NASA POWER).
        annee_debut : annee debut de la plage (defaut 2021).
        annee_fin : annee fin de la plage (defaut 2025).
        version_formule : version de formule en cours (defaut 1).

    Returns:
        :class:`CalculIndicateurResultat` avec score et composantes.

    Raises:
        RuntimeError : version_formule desalignee avec
            grandeurs_referentiel.version_formule_actuelle, serie
            evaluee introuvable ou source introuvable.
    """
    version_actuelle = session.execute(
        text("SELECT version_formule_actuelle FROM grandeurs_referentiel WHERE code = :code"),
        {"code": GRANDEUR_CODE_INDICATEUR},
    ).scalar()
    if version_actuelle is None:
        raise RuntimeError(
            f"Grandeur {GRANDEUR_CODE_INDICATEUR!r} introuvable dans grandeurs_referentiel."
        )
    if version_formule != int(version_actuelle):
        raise RuntimeError(
            f"Desalignement version_formule : argument={version_formule}, "
            f"version_formule_actuelle pour {GRANDEUR_CODE_INDICATEUR!r}={int(version_actuelle)}."
        )

    serie = session.execute(
        text(
            """
            SELECT
                sm.id AS serie_id,
                sm.localite_id,
                sm.grandeur_code AS grandeur_code_evaluee,
                sm.methode_collecte,
                s.fiabilite AS fiabilite_source
            FROM series_metadonnees sm
            JOIN sources s ON s.id = sm.source_id
            WHERE sm.code = :code
            """
        ),
        {"code": code_serie_evaluee},
    ).first()
    if serie is None:
        raise RuntimeError(
            f"Serie evaluee {code_serie_evaluee!r} introuvable dans series_metadonnees."
        )

    rows = session.execute(
        text(
            """
            SELECT niveau_confiance_derive
            FROM mesures_ressource
            WHERE serie_id = :serie_id
              AND valide_au IS NULL
              AND statut <> 'deprecie'
            """
        ),
        {"serie_id": int(serie.serie_id)},
    ).all()
    niveaux_confiance: list[str] = [r.niveau_confiance_derive for r in rows]
    nb_mesures_courantes = len(niveaux_confiance)
    nb_jours_attendus = _nb_jours_civils_plage(annee_debut, annee_fin)

    score = _calculer_score(
        nb_mesures_courantes=nb_mesures_courantes,
        nb_jours_attendus=nb_jours_attendus,
        niveaux_confiance=niveaux_confiance,
        fiabilite_source=serie.fiabilite_source,
    )

    session.execute(
        text(
            """
            INSERT INTO grandeurs_metier (
                grandeur_code, localite_id, series_metadonnees_id,
                periode_type, annee_debut, annee_fin, mois,
                version_formule, valeur, niveau_confiance_derive
            )
            VALUES (
                :grandeur_code, :localite_id, :series_metadonnees_id,
                'statique', :annee_debut, :annee_fin, NULL,
                :version_formule, :valeur, 'B'
            )
            """
        ),
        {
            "grandeur_code": GRANDEUR_CODE_INDICATEUR,
            "localite_id": int(serie.localite_id),
            "series_metadonnees_id": int(serie.serie_id),
            "annee_debut": annee_debut,
            "annee_fin": annee_fin,
            "version_formule": version_formule,
            "valeur": score["score_discret"],
        },
    )
    session.flush()

    return {
        "code_serie_evaluee": code_serie_evaluee,
        "nb_lignes_inseres": 1,
        "score_continu": score["score_continu"],
        "score_discret": score["score_discret"],
        "c1_completude": score["c1_completude"],
        "c2_confiance_moyenne": score["c2_confiance_moyenne"],
        "c3_fiabilite_source": score["c3_fiabilite_source"],
        "nb_mesures_courantes": nb_mesures_courantes,
        "nb_jours_attendus": nb_jours_attendus,
    }
