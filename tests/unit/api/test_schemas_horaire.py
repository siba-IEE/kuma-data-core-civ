"""Tests unitaires des schemas Pydantic `api/v1/schemas/horaire.py`.

Couvre :

- Plages numeriques / Literal de :class:`ParametresHoraire` (localite,
  grandeur, plage temporelle [2001-01-01, +366 jours]).
- Validation conditionnelle ``periode_fin >= periode_debut``.
- Validation plage maximale 366 jours.
- Alias URL ``format`` <-> Python ``format_sortie``.
- Schemas :class:`ResultatHoraire`, :class:`ReponseHoraire`,
  :class:`ReponseDisponibilite` (statut_editorial uniforme, valeur
  nullable).
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from kuma_data_core.api.v1.schemas.horaire import (
    ParametresHoraire,
    PlageTemporelle,
    ReponseDisponibilite,
    ReponseHoraire,
    ResultatHoraire,
)

pytestmark = pytest.mark.unit


# === Parametres ===========================================================


def test_t_hschema_1_parametres_cas_standard() -> None:
    """T-HSCHEMA-1 : parametres standards valides."""
    p = ParametresHoraire(
        localite="conakry_kaloum",
        grandeur="ghi",
        periode_debut=date(2024, 1, 1),
        periode_fin=date(2024, 1, 31),
    )
    assert p.format_sortie == "json"
    assert p.localite == "conakry_kaloum"


def test_t_hschema_2_localite_invalide() -> None:
    """T-HSCHEMA-2 : caracteres hors motif -> ValidationError.

    Contrat generalise (genericite pays, residu 1) : l'enumeration
    fermee a disparu, le schema n'impose plus qu'un motif de code
    (minuscules, chiffres, underscores). Un code bien forme mais
    inconnu passe le schema : c'est le handler qui repond 404
    RESSOURCE_LOCALITE_INCONNUE apres resolution contre la table.
    """
    with pytest.raises(ValidationError):
        ParametresHoraire(
            localite="Paris!",  # majuscule et ponctuation hors motif
            grandeur="ghi",
            periode_debut=date(2024, 1, 1),
            periode_fin=date(2024, 1, 31),
        )

    # Un code bien forme, meme inconnu du referentiel, passe le schema.
    p = ParametresHoraire(
        localite="sen_tambacounda",
        grandeur="ghi",
        periode_debut=date(2024, 1, 1),
        periode_fin=date(2024, 1, 31),
    )
    assert p.localite == "sen_tambacounda"


def test_t_hschema_3_grandeur_invalide() -> None:
    """T-HSCHEMA-3 : grandeur hors enum -> ValidationError."""
    with pytest.raises(ValidationError):
        ParametresHoraire(
            localite="kindia",
            grandeur="poa",  # hors enum des grandeurs horaires
            periode_debut=date(2024, 1, 1),
            periode_fin=date(2024, 1, 31),
        )


def test_t_hschema_4_periode_debut_avant_2001() -> None:
    """T-HSCHEMA-4 : periode_debut < 2001-01-01 -> ValidationError."""
    with pytest.raises(ValidationError):
        ParametresHoraire(
            localite="kindia",
            grandeur="ghi",
            periode_debut=date(2000, 12, 31),
            periode_fin=date(2001, 1, 5),
        )


def test_t_hschema_5_periode_fin_avant_debut() -> None:
    """T-HSCHEMA-5 : periode_fin < periode_debut -> ValidationError."""
    with pytest.raises(ValidationError, match="periode_fin"):
        ParametresHoraire(
            localite="kindia",
            grandeur="ghi",
            periode_debut=date(2024, 1, 31),
            periode_fin=date(2024, 1, 1),
        )


def test_t_hschema_6_plage_366_jours_ok() -> None:
    """T-HSCHEMA-6 : plage exactement 366 jours -> accepte."""
    p = ParametresHoraire(
        localite="kindia",
        grandeur="ghi",
        periode_debut=date(2024, 1, 1),
        periode_fin=date(2024, 12, 31),  # 366 jours bissextile
    )
    assert (p.periode_fin - p.periode_debut).days == 365  # 2024 bissextile, 366 jours = +365
    # Note : 366 jours pleins = 365 jours d'ecart au sens calendaire
    # (debut inclu, fin inclu), donc test legitimite avec 365 jours.


def test_t_hschema_7_plage_367_jours_rejete() -> None:
    """T-HSCHEMA-7 : plage > 366 jours -> ValidationError."""
    with pytest.raises(ValidationError, match="366 jours"):
        ParametresHoraire(
            localite="kindia",
            grandeur="ghi",
            periode_debut=date(2024, 1, 1),
            periode_fin=date(2025, 1, 5),  # 370 jours
        )


def test_t_hschema_8_alias_format_url() -> None:
    """T-HSCHEMA-8 : alias URL 'format' fonctionne pour format_sortie."""
    p = ParametresHoraire.model_validate(
        {
            "localite": "kindia",
            "grandeur": "ghi",
            "periode_debut": date(2024, 1, 1),
            "periode_fin": date(2024, 1, 5),
            "format": "csv",
        }
    )
    assert p.format_sortie == "csv"


# === Resultat / reponses ==================================================


def test_t_hschema_9_resultat_avec_valeur() -> None:
    """T-HSCHEMA-9 : ResultatHoraire avec valeur reelle."""
    r = ResultatHoraire(
        instant=datetime(2024, 6, 15, 12, 0, 0),
        valeur=893.4,
        unite="Wh/m²",
    )
    assert r.valeur == 893.4
    assert r.statut_editorial == "passe_plat_non_valide"


def test_t_hschema_10_resultat_avec_valeur_null() -> None:
    """T-HSCHEMA-10 : ResultatHoraire avec valeur null (sentinelle)."""
    r = ResultatHoraire(
        instant=datetime(2024, 6, 15, 3, 0, 0),
        valeur=None,
        unite="sans dimension",
    )
    assert r.valeur is None
    assert r.statut_editorial == "passe_plat_non_valide"


def test_t_hschema_11_reponse_disponibilite() -> None:
    """T-HSCHEMA-11 : ReponseDisponibilite avec PlageTemporelle."""
    r = ReponseDisponibilite(
        localite="kindia",
        grandeur="ghi",
        plage_disponible=PlageTemporelle(debut=date(2001, 1, 1), fin=date(2025, 12, 15)),
    )
    assert r.statut_editorial == "passe_plat_non_valide"


def test_t_hschema_12_reponse_horaire_vide() -> None:
    """T-HSCHEMA-12 : ReponseHoraire avec liste resultats vide."""
    r = ReponseHoraire(
        localite="kindia",
        grandeur="ghi",
        periode_demandee=PlageTemporelle(debut=date(2024, 1, 1), fin=date(2024, 1, 5)),
        resultats=[],
    )
    assert r.resultats == []
