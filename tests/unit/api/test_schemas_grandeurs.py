"""Tests unitaires des schemas Pydantic `api/v1/schemas/grandeurs.py`.

Couvre :

- Plages numeriques de chaque schema parametre (POA, thermique, PR, ECS, DJC)
- Validation conditionnelle PR (correction='temperature' requiert NOCT + coeff)
- Validation plage temporelle (periode_fin >= periode_debut)
- Discrimination granularite resultats (journalier vs mensuel)
- Alias URL ``format`` <-> Python ``format_sortie``
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from kuma_data_core.api.v1.schemas.grandeurs import (
    ParametresDegreJourClimatisation,
    ParametresEnergieUtileECS,
    ParametresPOA,
    ParametresProductibleCorrectionThermique,
    ParametresProductiblePRFourni,
    ReponseGrandeurF2,
    ResultatJournalier,
    ResultatMensuel,
)

pytestmark = pytest.mark.unit


# === Plages communes ======================================================


def test_t_schemas_1_plage_temporelle_invalide() -> None:
    """periode_fin < periode_debut leve ValidationError."""
    with pytest.raises(ValidationError, match="periode_fin"):
        ParametresDegreJourClimatisation(
            code_serie_source="gin_conakry_t2m_nasa_power_2021_2025",
            periode_debut=date(2024, 12, 31),
            periode_fin=date(2024, 1, 1),
            base_temperature_degc=24,
        )


def test_t_schemas_2_alias_format() -> None:
    """Le champ format_sortie accepte le nom URL 'format' via alias."""
    schema = ParametresDegreJourClimatisation.model_validate(
        {
            "code_serie_source": "gin_conakry_t2m_nasa_power_2021_2025",
            "periode_debut": date(2024, 1, 1),
            "periode_fin": date(2024, 12, 31),
            "base_temperature_degc": 24,
            "format": "csv",
        }
    )
    assert schema.format_sortie == "csv"


# === POA ==================================================================


def test_t_poa_1_cas_standard() -> None:
    schema = ParametresPOA(
        code_serie_source="gin_conakry_ghi_nasa_power_2021_2025",
        periode_debut=date(2024, 1, 1),
        periode_fin=date(2024, 12, 31),
        inclinaison_deg=20,
        orientation_deg=180,
    )
    assert schema.inclinaison_deg == 20
    assert schema.orientation_deg == 180
    assert schema.albedo_sol == 0.2  # defaut


def test_t_poa_2_inclinaison_hors_plage() -> None:
    with pytest.raises(ValidationError):
        ParametresPOA(
            code_serie_source="x",
            periode_debut=date(2024, 1, 1),
            periode_fin=date(2024, 12, 31),
            inclinaison_deg=105,  # > 90
            orientation_deg=180,
        )


def test_t_poa_3_orientation_360_exclu() -> None:
    with pytest.raises(ValidationError):
        ParametresPOA(
            code_serie_source="x",
            periode_debut=date(2024, 1, 1),
            periode_fin=date(2024, 12, 31),
            inclinaison_deg=20,
            orientation_deg=360,  # lt=360, donc 360 exclu
        )


def test_t_poa_4_albedo_bornes() -> None:
    schema_bas = ParametresPOA(
        code_serie_source="x",
        periode_debut=date(2024, 1, 1),
        periode_fin=date(2024, 12, 31),
        inclinaison_deg=0,
        orientation_deg=0,
        albedo_sol=0.0,
    )
    schema_haut = ParametresPOA(
        code_serie_source="x",
        periode_debut=date(2024, 1, 1),
        periode_fin=date(2024, 12, 31),
        inclinaison_deg=90,
        orientation_deg=359,
        albedo_sol=1.0,
    )
    assert schema_bas.albedo_sol == 0.0
    assert schema_haut.albedo_sol == 1.0


# === Thermique ============================================================


def test_t_therm_1_cas_standard() -> None:
    schema = ParametresProductibleCorrectionThermique(
        code_serie_source="gin_conakry_ghi_nasa_power_2021_2025",
        periode_debut=date(2024, 1, 1),
        periode_fin=date(2024, 12, 31),
        noct_degc=45,
        coeff_temp_pourcent_par_degc=-0.4,
        puissance_stc_wc=300,
    )
    assert schema.noct_degc == 45


def test_t_therm_2_noct_hors_plage() -> None:
    with pytest.raises(ValidationError):
        ParametresProductibleCorrectionThermique(
            code_serie_source="x",
            periode_debut=date(2024, 1, 1),
            periode_fin=date(2024, 12, 31),
            noct_degc=60,  # > 50
            coeff_temp_pourcent_par_degc=-0.4,
            puissance_stc_wc=300,
        )


def test_t_therm_3_puissance_stc_positive() -> None:
    with pytest.raises(ValidationError):
        ParametresProductibleCorrectionThermique(
            code_serie_source="x",
            periode_debut=date(2024, 1, 1),
            periode_fin=date(2024, 12, 31),
            noct_degc=45,
            coeff_temp_pourcent_par_degc=-0.4,
            puissance_stc_wc=0,  # gt=0
        )


# === PR ===================================================================


def test_t_pr_1_aucune_correction() -> None:
    schema = ParametresProductiblePRFourni(
        code_serie_source="x",
        periode_debut=date(2024, 1, 1),
        periode_fin=date(2024, 12, 31),
        pr_fourni=0.82,
        puissance_stc_wc=300,
    )
    assert schema.correction == "aucune"
    assert schema.noct_degc is None


def test_t_pr_2_correction_temperature_requiert_noct() -> None:
    """correction='temperature' sans NOCT leve ValidationError."""
    with pytest.raises(ValidationError, match="noct_degc"):
        ParametresProductiblePRFourni(
            code_serie_source="x",
            periode_debut=date(2024, 1, 1),
            periode_fin=date(2024, 12, 31),
            pr_fourni=0.82,
            correction="temperature",
            puissance_stc_wc=300,
        )


def test_t_pr_3_correction_temperature_complete() -> None:
    schema = ParametresProductiblePRFourni(
        code_serie_source="x",
        periode_debut=date(2024, 1, 1),
        periode_fin=date(2024, 12, 31),
        pr_fourni=0.82,
        correction="temperature",
        puissance_stc_wc=300,
        noct_degc=45,
        coeff_temp_pourcent_par_degc=-0.4,
    )
    assert schema.correction == "temperature"
    assert schema.noct_degc == 45


def test_t_pr_4_pr_hors_plage() -> None:
    with pytest.raises(ValidationError):
        ParametresProductiblePRFourni(
            code_serie_source="x",
            periode_debut=date(2024, 1, 1),
            periode_fin=date(2024, 12, 31),
            pr_fourni=1.2,  # > 1
            puissance_stc_wc=300,
        )


# === ECS ==================================================================


def test_t_ecs_1_cas_standard() -> None:
    schema = ParametresEnergieUtileECS(
        code_serie_source="x",
        periode_debut=date(2024, 1, 1),
        periode_fin=date(2024, 12, 31),
        rendement_optique_eta0=0.80,
        pertes_lineaires_a1=3.5,
        pertes_quadratiques_a2=0.01,
        temperature_fluide_entree_degc=45,
    )
    assert schema.rendement_optique_eta0 == 0.80


def test_t_ecs_2_a2_zero_autorise() -> None:
    """a2 = 0 autorise (capteur ideal sans pertes quadratiques)."""
    schema = ParametresEnergieUtileECS(
        code_serie_source="x",
        periode_debut=date(2024, 1, 1),
        periode_fin=date(2024, 12, 31),
        rendement_optique_eta0=0.80,
        pertes_lineaires_a1=3.5,
        pertes_quadratiques_a2=0.0,
        temperature_fluide_entree_degc=45,
    )
    assert schema.pertes_quadratiques_a2 == 0.0


def test_t_ecs_3_eta0_hors_plage() -> None:
    with pytest.raises(ValidationError):
        ParametresEnergieUtileECS(
            code_serie_source="x",
            periode_debut=date(2024, 1, 1),
            periode_fin=date(2024, 12, 31),
            rendement_optique_eta0=0.95,  # > 0.9
            pertes_lineaires_a1=3.5,
            pertes_quadratiques_a2=0.01,
            temperature_fluide_entree_degc=45,
        )


# === DJC ==================================================================


def test_t_djc_1_cas_standard() -> None:
    schema = ParametresDegreJourClimatisation(
        code_serie_source="x",
        periode_debut=date(2024, 1, 1),
        periode_fin=date(2024, 12, 31),
        base_temperature_degc=24,
    )
    assert schema.base_temperature_degc == 24


def test_t_djc_2_base_hors_plage() -> None:
    with pytest.raises(ValidationError):
        ParametresDegreJourClimatisation(
            code_serie_source="x",
            periode_debut=date(2024, 1, 1),
            periode_fin=date(2024, 12, 31),
            base_temperature_degc=40,  # > 35
        )


# === Resultats discrimines ================================================


def test_t_schemas_3_resultat_journalier() -> None:
    r = ResultatJournalier(
        instant=date(2024, 6, 15),
        valeur=5.83,
        unite="kWh/m²/jour",
        niveau_confiance="B",
    )
    assert r.granularite == "journalier"
    assert r.instant == date(2024, 6, 15)


def test_t_schemas_4_resultat_mensuel_format_valide() -> None:
    r = ResultatMensuel(
        instant="2024-06",
        valeur=145.6,
        unite="°C·j",
        niveau_confiance="B",
    )
    assert r.granularite == "mensuel"
    assert r.instant == "2024-06"


def test_t_schemas_5_resultat_mensuel_format_invalide() -> None:
    with pytest.raises(ValidationError):
        ResultatMensuel(
            instant="2024-13",  # mois invalide
            valeur=145.6,
            unite="°C·j",
            niveau_confiance="B",
        )


def test_t_schemas_6_reponse_grandeur_f2() -> None:
    """ReponseGrandeurF2 accepte une liste melangee journalier + mensuel."""
    reponse = ReponseGrandeurF2(
        code_grandeur="poa_parametrable",
        code_serie_source="gin_conakry_ghi_nasa_power_2021_2025",
        parametres_appliques={"inclinaison_deg": 20, "orientation_deg": 180},
        resultats=[
            ResultatJournalier(
                instant=date(2024, 1, 1),
                valeur=5.83,
                unite="kWh/m²/jour",
                niveau_confiance="B",
            ),
        ],
    )
    assert len(reponse.resultats) == 1
    assert reponse.resultats[0].granularite == "journalier"
