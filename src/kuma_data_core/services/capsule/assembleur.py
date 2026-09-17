"""Assemblage pur de la ressource, brut ou calibré selon la présence du calage.

Prend la donnée déjà en main (métadonnées, séquences, climatologie, et en ligne
le calage), dérive les deux valeurs arithmétiques manquantes, et rend le contenu
prêt à sérialiser. L'acquisition de la donnée (résolution, horaire, climatologie
du Core, appel kuma-calage) est au-dessus, pas ici.

Un seul assembleur pour les deux fonctionnements : ``calage=None`` produit une
capsule brute (hors-ligne), un calage présent produit la ressource calibrée
(en ligne). La séquence horaire reste brute dans les deux cas ; le moteur cale
la climatologie via le champ ``calage``.
"""

from __future__ import annotations

from typing import Any

from kuma_data_core.services.capsule.arithmetique import (
    climatologie_source_hep,
    hep_annuelle_reconstituee,
)


def assembler_ressource(
    *,
    metadonnees: dict[str, Any],
    periode: dict[str, Any],
    sequence_type: dict[str, Any],
    climatologie_hep: list[float],
    domaine_validite: dict[str, Any],
    sequence_contraignant: dict[str, Any] | None = None,
    calage: dict[str, Any] | None = None,
    corrections: dict[str, Any] | None = None,
    temperatures_conception: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble le contenu du fichier Kuma.

    Args:
        metadonnees: identité, édition, provenance de chaque série.
        periode: {debut, fin} des enregistrements.
        sequence_type: {mois, heures, ghi} horaire brut, année type.
        climatologie_hep: 12 valeurs mensuelles au point (brutes ; le moteur cale).
        domaine_validite: {debut, fin} de validité de la ressource.
        sequence_contraignant: l'année liante ; défaut = la type (v1, une station).
        calage: référentiel de calage {saisons: [...]} ; ``None`` pour une capsule
            brute (hors-ligne).
        corrections: {thermique?, salissure?} ; défaut aucune.
        temperatures_conception: extrêmes {froidC, chaudC, fenetre} au point,
            bruts NASA, hors calage ; ``None`` tant que le Core ne les sert pas
            (le bloc est alors omis, le dimensionnement retombe sur la saisie).
    """
    seq_contraignant = sequence_contraignant if sequence_contraignant is not None else sequence_type
    saisons = calage["saisons"] if calage is not None else None

    ressource = {
        "climatologieHep": climatologie_hep,
        "climatologieSourceHep": climatologie_source_hep(
            sequence_type["mois"], sequence_type["ghi"]
        ),
        "calage": calage,
        "enregistrementType": {"periode": periode, "sequence": sequence_type},
        "enregistrementContraignant": {"periode": periode, "sequence": seq_contraignant},
        "hepAnnuelleReconstituee": hep_annuelle_reconstituee(climatologie_hep, saisons),
        "domaineValidite": domaine_validite,
        **(
            {"temperaturesConception": temperatures_conception}
            if temperatures_conception is not None
            else {}
        ),
    }
    return {
        "metadonnees": metadonnees,
        "ressource": ressource,
        "corrections": corrections or {},
    }
