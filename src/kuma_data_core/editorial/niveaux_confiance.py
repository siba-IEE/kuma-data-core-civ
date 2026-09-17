"""Niveaux de confiance A/B/C : dérivation R1-R4 + override.

Périmètre tables : ``mesures_ressource``, ``grandeurs_metier``.

3 valeurs autorisées (`frozenset` miroir de la CHECK constraint SQL) :

- ``A`` (haute) : donnée mesurée directement par instrument de référence,
  ou calculée par méthode reconnue à partir de mesures elles-mêmes A.
- ``B`` (moyenne) : donnée modélisée, interpolée ou extrapolée selon
  méthodologie documentée, sur source ``fiabilite ∈ {'haute', 'moyenne'}``.
- ``C`` (basse) : donnée estimée par expertise sans validation
  instrumentale, ou produite à partir d'une source ``fiabilite='faible'``.

Règles de dérivation R1-R4, évaluées dans l'ordre.
La **première** qui matche détermine la valeur :

| Ordre | Condition | Résultat |
|---|---|---|
| R1 | ``source.fiabilite = 'faible'`` | ``C`` |
| R2 | ``methode_collecte = 'expertise_humaine'`` (R1 ne matche pas) | ``C`` |
| R3 | ``methode_collecte = 'mesure_directe'`` ET ``source.fiabilite = 'haute'`` | ``A`` |
| R4 | tous les autres cas (catch-all) | ``B`` |

(R3 ne matche qu'après évaluation négative de R1 et R2.)

Override éditorial : ``overrider_niveau_confiance``
pose ``niveau_confiance_override`` sur la ligne avec une justification
obligatoire dans ``commentaire_editorial``. ``retirer_override`` annule
l'override (revient au dérivé).

Ce module reste indépendant de SQLAlchemy pour la dérivation pure
(R1-R4 fonction pure). Les fonctions override/retirer mutent un objet
ligne fourni par le caller (SQLAlchemy ORM ou Pydantic, selon contexte).
"""

from __future__ import annotations

from typing import Protocol

from kuma_data_core.exceptions import JustificationRequise, NiveauConfianceInvalide

NIVEAUX_CONFIANCE_AUTORISES: frozenset[str] = frozenset({"A", "B", "C"})
"""Constante miroir de la CHECK constraint SQL ``ck_<table>_niveau_confiance_*_valide``.

Pattern hérité du module ``statuts``.
"""


class _LigneAvecOverride(Protocol):
    """Protocol structurel pour une ligne supportant les opérations override.

    Permet d'écrire les fonctions override/retirer sans dépendance dure
    sur ``MesureRessource``. Compatible avec ``GrandeurMetier`` à venir
    si elle expose la même surface.
    """

    niveau_confiance_override: str | None
    commentaire_editorial: str | None


def valider_niveau_confiance(niveau: str) -> None:
    """Vérifie que ``niveau`` ∈ ``{'A', 'B', 'C'}`` ; sinon
    ``NiveauConfianceInvalide``.
    """
    if niveau not in NIVEAUX_CONFIANCE_AUTORISES:
        raise NiveauConfianceInvalide(valeur_recue=niveau)


def calculer_niveau_confiance_derive(
    methode_collecte: str | None,
    fiabilite_source: str | None,
) -> str:
    """Applique les règles R1-R4 séquentiellement.

    Args:
        methode_collecte : valeur de ``series_metadonnees.methode_collecte``
            de la série hébergeant la mesure. Peut être None
            (série sans méthode renseignée).
        fiabilite_source : valeur de ``sources.fiabilite`` de la source
            primaire de la série. Valeurs typiques : 'haute', 'moyenne',
            'faible' (cf. modèle ``Source`` migration 004 + 006). Peut
            être None.

    Returns:
        'A', 'B' ou 'C' selon R1-R4.

    Notes:
        R1 est évaluée en premier (priorité à la qualité de source faible).
        R4 est le catch-all terminal - couvre notamment les cas
        ``modele_satellitaire`` qui sont les plus fréquents
        (NASA POWER → niveau B par défaut).
    """
    if fiabilite_source == "faible":
        return "C"
    if methode_collecte == "expertise_humaine":
        return "C"
    if methode_collecte == "mesure_directe" and fiabilite_source == "haute":
        return "A"
    return "B"


def overrider_niveau_confiance(
    ligne: _LigneAvecOverride,
    nouveau_niveau: str,
    justification: str,
) -> None:
    """Pose ``niveau_confiance_override`` sur la ligne avec justification.

    Args:
        ligne : objet exposant les attributs ``niveau_confiance_override``
            (str | None) et ``commentaire_editorial`` (str | None).
            Typiquement une instance SQLAlchemy ``MesureRessource``.
        nouveau_niveau : 'A', 'B' ou 'C'.
        justification : texte non vide expliquant la décision éditoriale.
            Posé dans ``commentaire_editorial``. Concatène si une
            justification précédente existe pour préserver l'historique
            éditorial.

    Raises:
        NiveauConfianceInvalide : si ``nouveau_niveau`` n'est pas A/B/C.
        JustificationRequise : si ``justification`` est None ou vide après
            ``str.strip()``.

    Side-effects :
        Mute ``ligne.niveau_confiance_override`` et
        ``ligne.commentaire_editorial``. Le caller doit s'occuper de
        commit/flush SQLAlchemy.
    """
    valider_niveau_confiance(nouveau_niveau)
    if not justification or not justification.strip():
        raise JustificationRequise(operation="overrider_niveau_confiance")
    ligne.niveau_confiance_override = nouveau_niveau
    if ligne.commentaire_editorial:
        ligne.commentaire_editorial = (
            f"{ligne.commentaire_editorial}\n[Override -> {nouveau_niveau}] {justification.strip()}"
        )
    else:
        ligne.commentaire_editorial = f"[Override -> {nouveau_niveau}] {justification.strip()}"


def retirer_override_niveau_confiance(
    ligne: _LigneAvecOverride,
    justification: str,
) -> None:
    """Annule l'override sur la ligne (revient au niveau dérivé).

    Args:
        ligne : idem ``overrider_niveau_confiance``.
        justification : texte non vide. Concaténé à ``commentaire_editorial``
            pour tracer le retrait. Symétrie avec ``overrider`` : un retrait
            est aussi une décision éditoriale à motiver.

    Raises:
        JustificationRequise : si ``justification`` est None ou vide.

    Side-effects :
        Mute ``ligne.niveau_confiance_override`` à None et
        ``ligne.commentaire_editorial``.
    """
    if not justification or not justification.strip():
        raise JustificationRequise(operation="retirer_override_niveau_confiance")
    ligne.niveau_confiance_override = None
    if ligne.commentaire_editorial:
        ligne.commentaire_editorial = (
            f"{ligne.commentaire_editorial}\n[Retrait override] {justification.strip()}"
        )
    else:
        ligne.commentaire_editorial = f"[Retrait override] {justification.strip()}"
