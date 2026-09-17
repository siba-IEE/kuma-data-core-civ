"""Tests unitaires de ``services.grandeurs.poa_bifacial``.

Couvre le POA global bifacial (modele infinite-sheds, pvlib) sur la localite
pilote Conakry-Kaloum. Fonctions pures sans mock DB.

Invariants verifies : ``bifaciality=0`` -> ``poa_global == poa_front`` ;
monotonie en bifacialite et en albedo (la face arriere capte plus quand l'un
ou l'autre augmente).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd  # type: ignore[import-untyped]
import pvlib  # type: ignore[import-untyped]
import pytest
from pvlib.bifacial import infinite_sheds  # type: ignore[import-untyped]

from kuma_data_core.api.v1.schemas.grandeurs import ParametresBifacial
from kuma_data_core.services.grandeurs.poa_bifacial import (
    NIVEAU_CONFIANCE_DERIVE_F2_V1,
    UNITE_POA_BIFACIAL,
    MesureHeureBifacial,
    MesureJourBifacial,
    albedo_du_jour,
    calculer_poa_bifacial,
    calculer_poa_bifacial_horaire,
)

pytestmark = pytest.mark.unit

_LAT, _LON = 9.5092, -13.7122  # Conakry-Kaloum


def _parametres(bifacialite: float = 0.8, albedo_sol: float = 0.2) -> ParametresBifacial:
    """Parametres bifacial typiques (rangees fixes plein sud, 20°)."""
    return ParametresBifacial(
        code_serie_source="gin_conakry_ghi_nasa_power_2021_2025",
        periode_debut=date(2024, 6, 15),
        periode_fin=date(2024, 6, 15),
        inclinaison_deg=20,
        orientation_deg=180,
        gcr=0.4,
        hauteur_m=1.5,
        pitch_m=5.0,
        bifacialite=bifacialite,
        albedo_sol=albedo_sol,
    )


# Profil GHI horaire de jour (W/m²) : cloche grossiere 6 h -> 18 h.
_PROFIL_GHI = [0.0] * 6 + [150, 350, 550, 750, 900, 980, 980, 900, 750, 550, 350, 150] + [0.0] * 6


def _mesures_horaires(jour: date, albedo: float = 0.2) -> list[MesureHeureBifacial]:
    """24 mesures horaires (GHI cloche, DNI/DHI split 0.8/0.2, albedo constant)."""
    return [
        MesureHeureBifacial(
            instant_mesure=datetime(jour.year, jour.month, jour.day, h, tzinfo=UTC),
            ghi=_PROFIL_GHI[h],
            dni=_PROFIL_GHI[h] * 0.85,
            dhi=_PROFIL_GHI[h] * 0.15,
            albedo=albedo,
        )
        for h in range(24)
    ]


def test_t_bif_1_vide() -> None:
    """Mesures vides -> listes vides (journalier et horaire)."""
    assert calculer_poa_bifacial([], _LAT, _LON, _parametres()) == []
    assert calculer_poa_bifacial_horaire([], _LAT, _LON, _parametres()) == []


def test_t_bif_2_structure_journalier() -> None:
    """Cas journalier : 1 resultat, structure (granularite, unite, niveau), valeur > 0."""
    mesures: list[MesureJourBifacial] = [
        {"instant_mesure": date(2024, 6, 15), "ghi": 5.5, "dni": 4.0, "dhi": 1.5, "albedo": 0.2}
    ]
    r = calculer_poa_bifacial(mesures, _LAT, _LON, _parametres())
    assert len(r) == 1
    assert r[0].granularite == "journalier"
    assert r[0].instant == date(2024, 6, 15)
    assert r[0].unite == UNITE_POA_BIFACIAL
    assert r[0].niveau_confiance == NIVEAU_CONFIANCE_DERIVE_F2_V1
    assert r[0].valeur > 0.0


def test_t_bif_3_invariance_bifacialite_zero_egal_poa_front() -> None:
    """INVARIANCE : ``bifaciality=0`` -> ``poa_global == poa_front`` (aucun gain arriere).

    Le service (qui sort ``poa_global``) a bifacialite=0 doit egaler le
    ``poa_front`` du modele sur les memes entrees/geometrie.
    """
    jour = date(2024, 6, 15)
    mesures = _mesures_horaires(jour)
    total_service = sum(
        r.valeur
        for r in calculer_poa_bifacial_horaire(mesures, _LAT, _LON, _parametres(bifacialite=0.0))
    )

    index = pd.DatetimeIndex([m["instant_mesure"] for m in mesures])
    solpos = pvlib.solarposition.get_solarposition(index, _LAT, _LON)
    front = infinite_sheds.get_irradiance(
        surface_tilt=20,
        surface_azimuth=180,
        solar_zenith=solpos["apparent_zenith"],
        solar_azimuth=solpos["azimuth"],
        gcr=0.4,
        height=1.5,
        pitch=5.0,
        ghi=pd.Series([m["ghi"] for m in mesures], index=index, dtype=float),
        dhi=pd.Series([m["dhi"] for m in mesures], index=index, dtype=float),
        dni=pd.Series([m["dni"] for m in mesures], index=index, dtype=float),
        albedo=pd.Series([m["albedo"] for m in mesures], index=index, dtype=float),
        bifaciality=0.0,
    )["poa_front"]
    total_front = float((front.clip(lower=0).fillna(0.0).groupby(index.date).sum() / 1000.0).sum())
    assert abs(total_service - total_front) < 1e-9


def test_t_bif_4_monotonie_bifacialite() -> None:
    """Monotonie : bifacialite 0.8 -> poa_global > bifacialite 0 (la face arriere ajoute)."""
    mesures = _mesures_horaires(date(2024, 6, 15))
    total_08 = sum(
        r.valeur
        for r in calculer_poa_bifacial_horaire(mesures, _LAT, _LON, _parametres(bifacialite=0.8))
    )
    total_00 = sum(
        r.valeur
        for r in calculer_poa_bifacial_horaire(mesures, _LAT, _LON, _parametres(bifacialite=0.0))
    )
    assert total_08 > total_00


def test_t_bif_5_monotonie_albedo() -> None:
    """Monotonie : albedo 0.6 -> poa_global > albedo 0.1 (plus de sol reflechi capte)."""
    p = _parametres(bifacialite=0.8)
    total_haut = sum(
        r.valeur
        for r in calculer_poa_bifacial_horaire(
            _mesures_horaires(date(2024, 6, 15), albedo=0.6), _LAT, _LON, p
        )
    )
    total_bas = sum(
        r.valeur
        for r in calculer_poa_bifacial_horaire(
            _mesures_horaires(date(2024, 6, 15), albedo=0.1), _LAT, _LON, p
        )
    )
    assert total_haut > total_bas


def test_t_bif_6_horaire_multi_jours() -> None:
    """Heures sur 2 jours -> 2 ResultatJournalier (structure, unite, niveau, valeur > 0)."""
    mesures = _mesures_horaires(date(2024, 6, 15)) + _mesures_horaires(date(2024, 6, 16))
    r = calculer_poa_bifacial_horaire(mesures, _LAT, _LON, _parametres())
    assert len(r) == 2
    assert r[0].instant == date(2024, 6, 15)
    assert r[1].instant == date(2024, 6, 16)
    assert all(x.unite == UNITE_POA_BIFACIAL for x in r)
    assert all(x.niveau_confiance == NIVEAU_CONFIANCE_DERIVE_F2_V1 for x in r)
    assert all(x.valeur > 0.0 for x in r)


def test_t_bif_7_idempotence() -> None:
    """Deux appels memes parametres -> meme resultat."""
    mesures = _mesures_horaires(date(2024, 6, 15))
    r1 = calculer_poa_bifacial_horaire(mesures, _LAT, _LON, _parametres())
    r2 = calculer_poa_bifacial_horaire(mesures, _LAT, _LON, _parametres())
    assert [x.valeur for x in r1] == [x.valeur for x in r2]


def test_t_bif_8_repli_albedo() -> None:
    """Repli albedo : compagne ``albedo_surface`` presente -> valeur reelle ;
    absente (serie vide ou jour non couvert) -> repli sur ``albedo_sol``.

    Ferme l'angle mort : le repli est inatteignable en integration (toute serie
    GHI avec DNI/DHI a aussi l'albedo), mais la regle pure est ici verrouillee.
    """
    reel = {date(2024, 6, 15): 0.18}
    # Compagne presente pour le jour -> valeur reelle (0.18), pas le repli.
    assert albedo_du_jour(reel, date(2024, 6, 15), 0.2) == 0.18
    # Jour non couvert par la serie -> repli albedo_sol.
    assert albedo_du_jour(reel, date(2024, 6, 16), 0.2) == 0.2
    # Serie compagne totalement absente (dict vide) -> repli albedo_sol.
    assert albedo_du_jour({}, date(2024, 6, 15), 0.2) == 0.2
