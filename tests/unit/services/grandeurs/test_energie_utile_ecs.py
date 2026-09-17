"""Tests unitaires de ``services.grandeurs.energie_utile_ecs``.

Couvre le modele Hottel-Whillier-Bliss bord-capteur sur la localite
pilote Conakry-Kaloum. Fonctions pures sans mock DB.

Convention fixtures : T2M en plage tropicale realiste (24-32 °C),
irradiance en plage realiste (4-7 kWh/m²/jour), parametres capteur
typiques Solar Keymark plan vitre (eta0 0.78, a1 3.5, a2 0.01) et
tube sous vide (eta0 0.65, a1 1.5, a2 0.005).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from kuma_data_core.api.v1.schemas.grandeurs import ParametresEnergieUtileECS
from kuma_data_core.services.grandeurs.energie_utile_ecs import (
    NIVEAU_CONFIANCE_DERIVE_F2_V1,
    UNITE_ENERGIE_UTILE,
    MesureHeureECS,
    MesureJourECS,
    calculer_energie_utile_ecs,
    calculer_energie_utile_ecs_horaire,
)

pytestmark = pytest.mark.unit


def _parametres_plan_vitre() -> ParametresEnergieUtileECS:
    """Parametres typiques capteur plan vitre Solar Keymark (T_in 45 °C ECS)."""
    return ParametresEnergieUtileECS(
        code_serie_source="gin_conakry_ghi_nasa_power_2021_2025",
        periode_debut=date(2024, 6, 15),
        periode_fin=date(2024, 6, 15),
        rendement_optique_eta0=0.78,
        pertes_lineaires_a1=3.5,
        pertes_quadratiques_a2=0.01,
        temperature_fluide_entree_degc=45.0,
    )


def _parametres_tube_sous_vide() -> ParametresEnergieUtileECS:
    """Parametres typiques capteur tubes sous vide (meilleure isolation)."""
    return ParametresEnergieUtileECS(
        code_serie_source="x",
        periode_debut=date(2024, 6, 15),
        periode_fin=date(2024, 6, 15),
        rendement_optique_eta0=0.65,
        pertes_lineaires_a1=1.5,
        pertes_quadratiques_a2=0.005,
        temperature_fluide_entree_degc=45.0,
    )


def test_t_ecs_1_cas_standard_plan_vitre() -> None:
    """T-ECS-1 : cas standard plan vitre Conakry juin, energie positive coherente.

    G_jour=5.5 kWh/m²/jour, T_amb=28°C, T_in=45°C.
    Rendement attendu : 0.50-0.60 (HWB en climat tropical chaud).
    Energie utile : 2.5-3.5 kWh/m²/jour.
    """
    mesures: list[MesureJourECS] = [
        {
            "instant_mesure": date(2024, 6, 15),
            "t_amb_degc": 28.0,
            "irradiance_kwh_par_m2_jour": 5.5,
        }
    ]
    resultats = calculer_energie_utile_ecs(mesures=mesures, parametres=_parametres_plan_vitre())
    assert len(resultats) == 1
    r = resultats[0]
    assert r.granularite == "journalier"
    assert r.instant == date(2024, 6, 15)
    assert r.unite == UNITE_ENERGIE_UTILE
    assert r.niveau_confiance == NIVEAU_CONFIANCE_DERIVE_F2_V1
    assert 2.0 < r.valeur < 4.0


def test_t_ecs_2_tube_sous_vide_meilleure_isolation() -> None:
    """T-ECS-2 : tubes sous vide produisent plus en climat chaud que plan vitre.

    Capteur a pertes thermiques plus faibles (a1 = 1.5 vs 3.5) -> rendement
    superieur a meme conditions T_amb / T_in.
    """
    mesures: list[MesureJourECS] = [
        {
            "instant_mesure": date(2024, 6, 15),
            "t_amb_degc": 28.0,
            "irradiance_kwh_par_m2_jour": 5.5,
        }
    ]
    r_plan = calculer_energie_utile_ecs(mesures, _parametres_plan_vitre())
    r_tube = calculer_energie_utile_ecs(mesures, _parametres_tube_sous_vide())
    # Tubes sous vide ont eta0 plus bas mais a1 nettement plus bas.
    # Avec dT modere (45-28=17K), l'effet a1 reduit domine et le rendement
    # tubes sous vide depasse plan vitre en valeur absolue.
    assert r_tube[0].valeur > r_plan[0].valeur


def test_t_ecs_3_t_amb_egale_t_in_rendement_optique_pur() -> None:
    """T-ECS-3 : T_amb = T_in -> dT=0 -> rendement = eta0 (pas de pertes).

    Cas limite physique : pas de difference de temperature entre capteur
    et ambient -> aucune perte thermique. Energie utile = eta0 x G_jour.
    """
    mesures: list[MesureJourECS] = [
        {
            "instant_mesure": date(2024, 6, 15),
            "t_amb_degc": 45.0,  # egal a T_in
            "irradiance_kwh_par_m2_jour": 5.5,
        }
    ]
    r = calculer_energie_utile_ecs(mesures, _parametres_plan_vitre())
    # Energie attendue = eta0 x irradiance = 0.78 x 5.5 = 4.29 kWh/m²
    assert abs(r[0].valeur - 0.78 * 5.5) / (0.78 * 5.5) < 0.01


def test_t_ecs_4_irradiance_nulle_energie_nulle() -> None:
    """T-ECS-4 : irradiance = 0 -> energie utile = 0 (capteur inactif)."""
    mesures: list[MesureJourECS] = [
        {
            "instant_mesure": date(2024, 6, 15),
            "t_amb_degc": 28.0,
            "irradiance_kwh_par_m2_jour": 0.0,
        }
    ]
    r = calculer_energie_utile_ecs(mesures, _parametres_plan_vitre())
    assert r[0].valeur == 0.0


def test_t_ecs_5_rendement_negatif_garde_fou() -> None:
    """T-ECS-5 : T_in tres elevee / G faible -> rendement HWB < 0 -> garde-fou 0.

    Avec T_in=85°C, T_amb=20°C (dT=65K) et G_jour=1 kWh/m²/jour (G_w=41.6
    W/m²), le rendement HWB devient negatif -> garde-fou retourne 0.
    """
    mesures: list[MesureJourECS] = [
        {
            "instant_mesure": date(2024, 6, 15),
            "t_amb_degc": 20.0,
            "irradiance_kwh_par_m2_jour": 1.0,
        }
    ]
    params_chaud = ParametresEnergieUtileECS(
        code_serie_source="x",
        periode_debut=date(2024, 6, 15),
        periode_fin=date(2024, 6, 15),
        rendement_optique_eta0=0.78,
        pertes_lineaires_a1=3.5,
        pertes_quadratiques_a2=0.01,
        temperature_fluide_entree_degc=85.0,
    )
    r = calculer_energie_utile_ecs(mesures, params_chaud)
    # Garde-fou : pas d'energie negative.
    assert r[0].valeur == 0.0


def test_t_ecs_6_liste_vide() -> None:
    """T-ECS-6 : mesures vide -> liste resultats vide."""
    r = calculer_energie_utile_ecs(mesures=[], parametres=_parametres_plan_vitre())
    assert r == []


def test_t_ecs_7_idempotence() -> None:
    """T-ECS-7 : deux appels avec memes parametres -> meme reponse."""
    mesures: list[MesureJourECS] = [
        {
            "instant_mesure": date(2024, 6, 15),
            "t_amb_degc": 28.0,
            "irradiance_kwh_par_m2_jour": 5.5,
        }
    ]
    params = _parametres_plan_vitre()
    r1 = calculer_energie_utile_ecs(mesures, params)
    r2 = calculer_energie_utile_ecs(mesures, params)
    assert r1[0].valeur == r2[0].valeur


def test_t_ecs_8_serie_pluri_jours() -> None:
    """T-ECS-8 : serie 5 jours -> 5 resultats, ordre preserve, niveau 'B'."""
    mesures: list[MesureJourECS] = [
        {
            "instant_mesure": date(2024, 1, d),
            "t_amb_degc": 26.0,
            "irradiance_kwh_par_m2_jour": 5.0,
        }
        for d in (1, 2, 3, 4, 5)
    ]
    r = calculer_energie_utile_ecs(mesures, _parametres_plan_vitre())
    assert len(r) == 5
    assert [m.instant for m in r] == [date(2024, 1, d) for d in (1, 2, 3, 4, 5)]
    assert all(m.niveau_confiance == NIVEAU_CONFIANCE_DERIVE_F2_V1 for m in r)


# === Methode integration horaire (rendement HWB non-lineaire en G) ===


def _mesures_horaires_ecs(
    jour: date, profil_ghi_w: list[float], t_amb: float = 28.0
) -> list[MesureHeureECS]:
    """24 mesures horaires (GHI W/m² par heure, T_amb constante)."""
    return [
        MesureHeureECS(
            instant_mesure=datetime(jour.year, jour.month, jour.day, h, tzinfo=UTC),
            t_amb_degc=t_amb,
            irradiance_w_par_m2=profil_ghi_w[h],
        )
        for h in range(24)
    ]


def test_t_ecs_h1_vide() -> None:
    """Mesures horaires vides -> liste vide."""
    assert calculer_energie_utile_ecs_horaire([], _parametres_plan_vitre()) == []


def test_t_ecs_h2_plat_egal_journalier() -> None:
    """Profil plat -> horaire == journalier (G_24h == G horaire constant -> meme eta).

    24 h a 250 W/m² (= 6 kWh/m²/jour) : la methode journaliere utilise
    G_24h = 6000/24 = 250 W/m², soit le meme rendement HWB que chaque heure.
    """
    jour = date(2024, 6, 15)
    total_h = sum(
        r.valeur
        for r in calculer_energie_utile_ecs_horaire(
            _mesures_horaires_ecs(jour, [250.0] * 24), _parametres_plan_vitre()
        )
    )
    mesure_jour: MesureJourECS = {
        "instant_mesure": jour,
        "t_amb_degc": 28.0,
        "irradiance_kwh_par_m2_jour": 6.0,
    }
    total_j = calculer_energie_utile_ecs([mesure_jour], _parametres_plan_vitre())[0].valeur
    assert abs(total_h - total_j) < 1e-9


def test_t_ecs_h3_pique_diffère_journalier() -> None:
    """JENSEN : rendement HWB non-lineaire en G -> horaire != journalier (pique).

    A fort G (midi), les pertes ``a1*dT/G`` sont plus faibles -> meilleur
    rendement instantane. La methode journaliere, calculee sur la moyenne 24 h
    (G faible), **sous-estime** ce rendement -> horaire > journalier.
    """
    jour = date(2024, 6, 15)
    profil = [1000.0 if 9 <= h < 15 else 0.0 for h in range(24)]  # 6 h a 1000 = 6 kWh/m²/jour
    total_h = sum(
        r.valeur
        for r in calculer_energie_utile_ecs_horaire(
            _mesures_horaires_ecs(jour, profil), _parametres_plan_vitre()
        )
    )
    mesure_jour: MesureJourECS = {
        "instant_mesure": jour,
        "t_amb_degc": 28.0,
        "irradiance_kwh_par_m2_jour": 6.0,
    }
    total_j = calculer_energie_utile_ecs([mesure_jour], _parametres_plan_vitre())[0].valeur
    assert total_h > total_j


def test_t_ecs_h4_structure_multi_jours() -> None:
    """Heures sur 2 jours -> 2 ResultatJournalier (structure, unite, niveau)."""
    mesures = _mesures_horaires_ecs(date(2024, 6, 15), [400.0] * 24) + _mesures_horaires_ecs(
        date(2024, 6, 16), [400.0] * 24
    )
    r = calculer_energie_utile_ecs_horaire(mesures, _parametres_plan_vitre())
    assert len(r) == 2
    assert r[0].instant == date(2024, 6, 15)
    assert r[1].instant == date(2024, 6, 16)
    assert all(x.unite == UNITE_ENERGIE_UTILE for x in r)
    assert all(x.niveau_confiance == NIVEAU_CONFIANCE_DERIVE_F2_V1 for x in r)
    assert all(x.valeur > 0.0 for x in r)
