"""Tests unitaires des helpers purs de ``api/v1/grandeurs.py``.

Couvre, sans base de données :

- garde de granularité des routes F2 (``methode``) et F1 (série journalière) ;
- textes ``limite`` de ``ghi_exceedance`` (jumeaux de pixel détectés, sans
  référence d'instance) et d'``incertitude_inter_source`` ;
- dégénérescence détectée à la lecture (fiche, confiance B) ;
- sélection des paires d'écart de l'atlas (première paire portant des écarts
  par grandeur, convention « A vs B » = ``(A - B) / B``).
"""

from __future__ import annotations

from datetime import date

import pytest

from kuma_data_core.api.codes_erreur import CodeErreur
from kuma_data_core.api.erreurs import ExceptionKuma
from kuma_data_core.api.v1 import grandeurs as module
from kuma_data_core.api.v1.grandeurs import (
    _PAIRES_ECART_ATLAS,
    SerieSourceResolue,
    _construire_limite_ghi_exceedance,
    _construire_limite_incertitude_inter_source,
    _degenerescence_detectee,
    _exiger_granularite_methode,
    _exiger_serie_journaliere,
    _lire_ecarts_atlas,
    _mediane_abs,
)

pytestmark = pytest.mark.unit


def _serie(granularite: str | None) -> SerieSourceResolue:
    return SerieSourceResolue(
        serie_id=1,
        localite_id=2,
        source_id=1,
        grandeur_code="ghi",
        localite_code="loc_test",
        periode_debut=date(1991, 1, 1),
        source_code="nasa_power",
        granularite=granularite,
        periode_fin=date(2025, 12, 31),
    )


# === Garde de granularité ==================================================


def test_methode_journaliere_accepte_serie_journaliere() -> None:
    _exiger_granularite_methode(_serie("journalier"), "moyenne_journaliere", "s")


@pytest.mark.parametrize("granularite", ["mensuel", "horaire", None])
def test_methode_journaliere_refuse_autre_granularite(granularite: str | None) -> None:
    """Une série non journalière était lue dans la mauvaise table (liste vide, 200)."""
    with pytest.raises(ExceptionKuma) as exc:
        _exiger_granularite_methode(_serie(granularite), "moyenne_journaliere", "serie_x")
    assert exc.value.statut_http == 400
    assert exc.value.code == CodeErreur.VALIDATION_VALEUR_INVALIDE
    assert "serie_x" in exc.value.message and "'journalier'" in exc.value.message


def test_integration_horaire_exige_serie_horaire() -> None:
    _exiger_granularite_methode(_serie("horaire"), "integration_horaire", "s")
    with pytest.raises(ExceptionKuma) as exc:
        _exiger_granularite_methode(_serie("journalier"), "integration_horaire", "s")
    assert exc.value.code == CodeErreur.VALIDATION_VALEUR_INVALIDE
    assert "'horaire'" in exc.value.message


def test_pr_fourni_admet_le_mensuel_en_methode_journaliere() -> None:
    admises = ("journalier", "mensuel")
    for granularite in admises:
        _exiger_granularite_methode(
            _serie(granularite), "moyenne_journaliere", "s", granularites_journalieres=admises
        )
    with pytest.raises(ExceptionKuma):
        _exiger_granularite_methode(
            _serie("horaire"), "moyenne_journaliere", "s", granularites_journalieres=admises
        )


def test_routes_f1_exigent_une_serie_journaliere() -> None:
    _exiger_serie_journaliere(_serie("journalier"), "s", "pr_realiste")
    with pytest.raises(ExceptionKuma) as exc:
        _exiger_serie_journaliere(_serie("mensuel"), "serie_m", "pr_realiste")
    assert exc.value.statut_http == 400
    assert exc.value.code == CodeErreur.INCOMPATIBILITE_SOURCE_GRANDEUR
    assert "'pr_realiste'" in exc.value.message and "serie_m" in exc.value.message


# === ghi_exceedance : limite ===============================================


def test_limite_exceedance_sans_jumeau() -> None:
    limite = _construire_limite_ghi_exceedance(30, [])
    assert "30 ans" in limite and "1991-2020" in limite
    assert "Jumeaux" not in limite


def test_limite_exceedance_cite_les_jumeaux() -> None:
    limite = _construire_limite_ghi_exceedance(30, ["loc_b", "loc_c"])
    assert "2 autre(s) localite(s) (loc_b, loc_c)" in limite
    assert "P50 / P90 le sont donc aussi" in limite


def test_limite_exceedance_sans_reference_d_instance() -> None:
    limite = _construire_limite_ghi_exceedance(30, ["loc_b"]).lower()
    for terme in ("gin_", "kindia", "mamou", "guin", "pilote", "d-29"):
        assert terme not in limite


# === incertitude_inter_source ==============================================


def test_mediane_abs() -> None:
    assert _mediane_abs([-3.0, 1.0, 2.0]) == 2.0
    assert _mediane_abs([-4.0, 1.0, 2.0, -3.0]) == 2.5


def test_degenerescence_detectee_jumeaux() -> None:
    fiche, niveaux = _degenerescence_detectee("a", {"a": ["b", "c"], "b": ["a", "c"]})
    assert fiche is not None
    assert fiche.n_jumeaux == 2
    assert "(b, c)" in fiche.note
    assert niveaux == [("B", None)]


def test_degenerescence_detectee_point_resolu() -> None:
    fiche, _ = _degenerescence_detectee("a", {"a": []})
    assert fiche is not None
    assert fiche.n_jumeaux == 0
    assert "Point resolu" in fiche.note


def test_degenerescence_non_detectable_sans_serie() -> None:
    assert _degenerescence_detectee("inconnue", {"a": []}) == (None, [])


def test_paires_atlas_couvrent_ghi_et_dni_au_format_a_vs_b() -> None:
    assert {p.grandeur for p in _PAIRES_ECART_ATLAS} == {"ghi", "dni"}
    for paire in _PAIRES_ECART_ATLAS:
        assert len(paire.paire.split(" vs ")) == 2


def test_lire_ecarts_atlas_premiere_paire_par_grandeur(monkeypatch: pytest.MonkeyPatch) -> None:
    """Par grandeur, la première paire portant des écarts est retenue, et une seule."""
    donnees = {
        "ecart_relatif_ghi_sarah3_nasa": [10.0, -2.0, 6.0],
        "ecart_relatif_referentiel": [-9.0],
        "ecart_relatif_dni_cams": [-20.0, -30.0],
    }

    def faux_lecteur(
        _session: object, _code: str, grandeur_ecart: str
    ) -> tuple[list[float], list[tuple[str, str | None]]]:
        valeurs = donnees.get(grandeur_ecart, [])
        return valeurs, [("B", None)] * len(valeurs)

    monkeypatch.setattr(module, "_lire_ecart_paire_recent", faux_lecteur)
    ecarts, niveaux = _lire_ecarts_atlas(None, "loc")  # type: ignore[arg-type]

    assert [(e.grandeur, e.paire) for e in ecarts] == [
        ("ghi", "PVGIS-SARAH3 vs NASA POWER"),
        ("dni", "NASA POWER vs CAMS"),
    ]
    ghi, dni = ecarts
    assert ghi.ecart_abs_pct == 6.0 and ghi.n_mois == 3
    assert ghi.ecart_signe_pct == pytest.approx(14.0 / 3, abs=1e-4)
    assert dni.ecart_abs_pct == 25.0 and dni.ecart_signe_pct == -25.0
    assert len(niveaux) == 5


def test_limite_incertitude_cite_les_paires_exposees(monkeypatch: pytest.MonkeyPatch) -> None:
    def faux_lecteur(
        _session: object, _code: str, grandeur_ecart: str
    ) -> tuple[list[float], list[tuple[str, str | None]]]:
        if grandeur_ecart == "ecart_relatif_dni_cams_nasa":
            return [1.0], [("B", None)]
        return [], []

    monkeypatch.setattr(module, "_lire_ecart_paire_recent", faux_lecteur)
    ecarts, _ = _lire_ecarts_atlas(None, "loc")  # type: ignore[arg-type]
    limite = _construire_limite_incertitude_inter_source(ecarts)
    assert "DNI : CAMS vs NASA POWER" in limite
    assert "GHI" not in limite
    assert "(A - B) / B" in limite
