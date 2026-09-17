"""Lecture et écriture du fichier Kuma (format ``kuma-ressource-1``).

Seconde vue conforme au format, côté Python, du même document que la vue TS
(``packages/moteur-minireseau/src/fichier-kuma.ts``). L'aller-retour se prouve
sur les **valeurs**, jamais sur les octets : deux implémentations conformes
formatent le même double différemment, sans conséquence puisque le parsing
normalise vers le même flottant.

En-tête JSON, un repère, puis un bloc de données tabulaire pour les deux
séquences horaires.
"""

from __future__ import annotations

import json
from typing import Any

FORMAT_FICHIER_KUMA = "kuma-ressource-1"
REPERE_DONNEES = "===DONNEES==="
COLONNES_DONNEES = "enregistrement,mois,heure,ghi_wm2"


class FichierKumaInvalideError(ValueError):
    """Le fichier Kuma est mal structuré ou incomplet."""


def _nombre_vers_texte(x: float) -> str:
    """Le plus court aller-retournable, point décimal, jamais la virgule."""
    if x == int(x):
        return str(int(x))
    return repr(x)


def _sequence_vers_lignes(enregistrement: str, sequence: dict[str, Any]) -> list[str]:
    return [
        f"{enregistrement},{m},{h},{_nombre_vers_texte(g)}"
        for m, h, g in zip(sequence["mois"], sequence["heures"], sequence["ghi"], strict=True)
    ]


def serialiser(contenu: dict[str, Any]) -> str:
    """Sérialise un contenu (metadonnees, ressource, corrections) en texte."""
    r = contenu["ressource"]
    c = contenu.get("corrections", {})
    entete = {
        "formatVersion": FORMAT_FICHIER_KUMA,
        "metadonnees": contenu["metadonnees"],
        "ressource": {
            "climatologieHep": r["climatologieHep"],
            "climatologieSourceHep": r["climatologieSourceHep"],
            **({"calage": r["calage"]} if r.get("calage") is not None else {}),
            "enregistrementType": {"periode": r["enregistrementType"]["periode"]},
            "enregistrementContraignant": {"periode": r["enregistrementContraignant"]["periode"]},
            **(
                {"selectionContraignante": r["selectionContraignante"]}
                if r.get("selectionContraignante") is not None
                else {}
            ),
            "hepAnnuelleReconstituee": r["hepAnnuelleReconstituee"],
            "domaineValidite": r["domaineValidite"],
            **(
                {"temperaturesConception": r["temperaturesConception"]}
                if r.get("temperaturesConception") is not None
                else {}
            ),
        },
        "corrections": {
            **({"thermique": c["thermique"]} if c.get("thermique") is not None else {}),
            **({"salissure": c["salissure"]} if c.get("salissure") is not None else {}),
        },
    }
    lignes = [json.dumps(entete, ensure_ascii=False, indent=2), REPERE_DONNEES, COLONNES_DONNEES]
    lignes += _sequence_vers_lignes("type", r["enregistrementType"]["sequence"])
    lignes += _sequence_vers_lignes("contraignant", r["enregistrementContraignant"]["sequence"])
    return "\n".join(lignes)


def _nombre(texte: str, contexte: str) -> float:
    if texte.strip() == "":
        raise FichierKumaInvalideError(f"{contexte} : nombre vide")
    try:
        return float(texte)
    except ValueError as e:
        raise FichierKumaInvalideError(f"{contexte} : nombre invalide ({texte})") from e


def lire(texte: str) -> dict[str, Any]:
    """Lit un fichier Kuma texte et rend son contenu.

    Échoue au seuil, jamais en complétant par défaut : un fichier qui a perdu
    sa provenance ne se lit pas en silence.
    """
    lignes = texte.split("\n")
    try:
        i_repere = lignes.index(REPERE_DONNEES)
    except ValueError as e:
        raise FichierKumaInvalideError("repère de données absent") from e

    try:
        entete = json.loads("\n".join(lignes[:i_repere]))
    except json.JSONDecodeError as e:
        raise FichierKumaInvalideError("en-tête non JSON") from e

    if entete.get("formatVersion") != FORMAT_FICHIER_KUMA:
        raise FichierKumaInvalideError(
            f"version de format non reconnue : {entete.get('formatVersion')}"
        )

    if lignes[i_repere + 1] != COLONNES_DONNEES:
        raise FichierKumaInvalideError("colonnes du bloc de données inattendues")

    seqs: dict[str, dict[str, list[float]]] = {
        "type": {"mois": [], "heures": [], "ghi": []},
        "contraignant": {"mois": [], "heures": [], "ghi": []},
    }
    for ligne in lignes[i_repere + 2 :]:
        if ligne == "":
            continue
        champs = ligne.split(",")
        if len(champs) != 4:
            raise FichierKumaInvalideError(f"ligne de données à {len(champs)} colonnes")
        cible = seqs.get(champs[0])
        if cible is None:
            raise FichierKumaInvalideError(f"enregistrement inconnu : {champs[0]}")
        cible["mois"].append(int(_nombre(champs[1], "mois")))
        cible["heures"].append(int(_nombre(champs[2], "heure")))
        cible["ghi"].append(_nombre(champs[3], "ghi_wm2"))

    r = entete["ressource"]
    ressource = {
        "climatologieHep": r["climatologieHep"],
        "climatologieSourceHep": r["climatologieSourceHep"],
        "calage": r.get("calage"),
        "enregistrementType": {
            "periode": r["enregistrementType"]["periode"],
            "sequence": seqs["type"],
        },
        "enregistrementContraignant": {
            "periode": r["enregistrementContraignant"]["periode"],
            "sequence": seqs["contraignant"],
        },
        "selectionContraignante": r.get("selectionContraignante"),
        "temperaturesConception": r.get("temperaturesConception"),
        "hepAnnuelleReconstituee": r["hepAnnuelleReconstituee"],
        "domaineValidite": r["domaineValidite"],
    }
    return {
        "metadonnees": entete["metadonnees"],
        "ressource": ressource,
        "corrections": entete.get("corrections", {}),
    }
