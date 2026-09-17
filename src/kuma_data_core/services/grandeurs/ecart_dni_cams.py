"""Calcul de la grandeur d'écart inter-source ``ecart_relatif_dni_cams``.

Écart relatif **du DNI** entre NASA POWER (primaire) et CAMS Radiation (référence
d'écart, DNI aérosol-corrigé), **iso-période 2004-2020**, **par (année, mois)**.

Orientation arbitrée : ``(nasa - cams) / cams x 100`` - NASA primaire au
numérateur, CAMS (référentiel d'écart) au dénominateur, miroir fidèle de l'écart
inter-source référentiel. Réutilise **tel quel** le helper pur
``_calcul_ecart_relatif(valeur_nasa, valeur_cams)``.

Pattern fonctions pures + orchestrateur I/O : ce module **importe** les 3
helpers de :mod:`referentiels` (``_calcul_ecart_relatif``, ``_lire_mensuel``,
``_bulk_insert_grandeurs_metier``) **sans toucher** l'orchestrateur figé
``calculer_et_inserer_referentiels`` ni ses constantes.

Le **signe** de l'écart est un **résultat empirique** (observé -26 % en
moyenne, NASA lit moins de DNI que CAMS), documenté dans le
``commentaire_editorial`` des séries - pas un choix de design. Confiance
dérivée ``B`` (signal indirect par construction). Calcul **déterministe depuis
la base, aucun réseau**.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict

from sqlalchemy.orm import Session

from kuma_data_core.services.grandeurs.referentiels import (
    _bulk_insert_grandeurs_metier,
    _calcul_ecart_relatif,
    _lire_mensuel,
)

# === Constantes module =====================================================

GRANDEUR_ECART_DNI_CAMS: str = "ecart_relatif_dni_cams"
NIVEAU_CONFIANCE_DERIVE: str = "B"
VERSION_FORMULE: int = 1


# === Types ================================================================


class ContexteVilleEcartDniCams(TypedDict):
    """Contexte par localité pour le calcul de l'écart DNI CAMS."""

    localite_id: int
    code_serie_nasa: str
    code_serie_cams: str
    series_metadonnees_id: int


class ResultatEcartDniCams(TypedDict):
    """Résultat d'un appel à :func:`calculer_et_inserer_ecart_dni_cams`."""

    nb_insere: int


# === Orchestrateur I/O ====================================================


def calculer_et_inserer_ecart_dni_cams(
    *,
    session: Session,
    contextes_villes: Sequence[ContexteVilleEcartDniCams],
) -> ResultatEcartDniCams:
    """Calcule et insère l'écart relatif DNI CAMS dans ``grandeurs_metier``.

    Pour chaque ville : lit les séries DNI NASA et CAMS depuis
    ``mesures_ressource_mensuelles`` (helper ``_lire_mensuel``), itère
    l'**intersection** des (année, mois) communs (exclut 2004-01 absent côté
    CAMS, et tout mois manquant), applique ``(nasa - cams) / cams x 100`` et
    insère une ligne ``grandeurs_metier`` par mois commun
    (``periode_type='mensuel'``, ``annee_debut = annee_fin = annee``).

    Args:
        session : session SQLAlchemy active (add+flush, l'appelant commit).
        contextes_villes : séquence par localité avec
            ``localite_id``, ``code_serie_nasa``, ``code_serie_cams``,
            ``series_metadonnees_id`` (série calculée pré-insérée).

    Returns:
        :class:`ResultatEcartDniCams` - ``nb_insere`` (1 218 attendu).
    """
    nb_insere = 0

    for ctx in contextes_villes:
        nasa = _lire_mensuel(session, ctx["code_serie_nasa"])
        cams = _lire_mensuel(session, ctx["code_serie_cams"])

        lignes: list[dict[str, object]] = []
        for annee, mois in sorted(set(nasa) & set(cams)):
            ecart_pct = _calcul_ecart_relatif(nasa[(annee, mois)], cams[(annee, mois)])
            lignes.append(
                {
                    "grandeur_code": GRANDEUR_ECART_DNI_CAMS,
                    "localite_id": ctx["localite_id"],
                    "series_metadonnees_id": ctx["series_metadonnees_id"],
                    "periode_type": "mensuel",
                    "annee_debut": annee,
                    "annee_fin": annee,
                    "mois": mois,
                    "version_formule": VERSION_FORMULE,
                    "valeur": ecart_pct,
                    "niveau_confiance_derive": NIVEAU_CONFIANCE_DERIVE,
                }
            )
        _bulk_insert_grandeurs_metier(session, lignes)
        nb_insere += len(lignes)

    session.flush()
    return {"nb_insere": nb_insere}
