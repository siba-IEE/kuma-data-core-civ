"""Tests d'intégration de ``hep`` et ``productible_specifique_theorique`` (migration 0038).

Heures équivalentes pleines et productible spécifique théorique (ADR-0023) aux
**142 localités**, depuis le GHI **mensuel** des 4 sources : NASA POWER
1991-2025, CAMS 2005-2025, SARAH-3 et ERA5 2005-2023. Une série par (grandeur,
source, localité), matérialisée dans ``grandeurs_metier``, mensuelle et annuelle.

Vérifie :

- le **contrat** : grandeurs F1 ``stockee`` en version 1, unités
  ``heure_equivalente_pleine`` et ``kwh_par_kwc_periode`` ; ``productible_mensuel``
  désactivée au référentiel et inutilisée ; séries ``calcul_derive`` de
  ``kuma_calculs`` ; mise en garde du saut ERA5 de 2021 (même phrase que 0033)
  sur les seules séries dérivées d'ERA5 ;
- la **complétude** (12 mois par année de la source, une ligne annuelle par
  année complète) et le **domaine** physique ;
- la **fidélité** : chaque valeur gravée est recalculée indépendamment depuis les
  seeds pilotes et les CSV des lots, en décimal exact (HEP mensuel = GHI x
  jours du mois, annuel = somme des 12 mois, productible = HEP x 0,8), et doit
  lui être égale **au bit près** ;
- la cohérence somme des 12 mois = annuel (fiche ``hep``, § 8.3) ;
- l'**équivalence avec la définition journalière héritée** : aux 34 localités du
  journalier NASA, la fonction de la fiche (``_agreger_hep_journaliers``,
  complétude stricte des jours civils) appliquée au GHI journalier redonne le
  HEP gravé depuis le mensuel, à l'arrondi près.
"""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal
from functools import cache
from types import ModuleType
from typing import Any, NamedTuple

import pytest
from sqlalchemy import Row, text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds import series_cams_ghi_mensuel_civ as cams_ghi
from kuma_data_core.db.seeds import series_nasa_power_ghi_mensuel_civ as np_ghi
from kuma_data_core.db.seeds import series_pvgis_era5_ghi_mensuel_civ as era5_ghi
from kuma_data_core.db.seeds import series_pvgis_sarah3_ghi_mensuel_civ as sarah3_ghi
from kuma_data_core.db.seeds.lots_civ import (
    CONTRATS_NASA_JOURNALIERS,
    CONTRATS_NASA_JOURNALIERS_EXTENSION,
    LOT_EXTENSION,
    LOT_JOURNALIER,
    points_journalier,
)
from kuma_data_core.db.seeds.series_csv import lire_series_journalieres
from kuma_data_core.services.grandeurs.hep import _agreger_hep_journaliers
from tests.integration.db.mesures_brutes import mesures_mensuelles

pytestmark = pytest.mark.integration

HEP = "hep"
PST = "productible_specifique_theorique"
GRANDEURS = (HEP, PST)
PR_THEORIQUE = Decimal("0.8")
HEP_MAX_PAR_JOUR = 12  # h_eq/jour, au-delà du rayonnement extraterrestre
# Écart toléré entre HEP journalier et mensuel, par jour de la période : la moyenne
# des jours NASA redonne le mensuel à 0,00017 kWh/m²/jour près (ADR-0016).
TOLERANCE_PAR_JOUR = 2e-4

# 3 pilotes + 139 localités des lots nationaux (ADR-0017).
_LOCALITES = set(mesures_mensuelles(np_ghi))


class Source(NamedTuple):
    """Une source de GHI mensuel : jeton des codes de série, seed pilote, période."""

    jeton: str
    seed: ModuleType
    debut: int
    fin: int

    @property
    def nb_annees(self) -> int:
        return self.fin - self.debut + 1


_SOURCES = (
    Source("nasa_power", np_ghi, 1991, 2025),
    Source("cams", cams_ghi, 2005, 2025),
    Source("sarah3", sarah3_ghi, 2005, 2023),
    Source("era5", era5_ghi, 2005, 2023),
)
_PAR_JETON = {s.jeton: s for s in _SOURCES}


def _id(source: Source) -> str:
    return source.jeton


def _code(grandeur: str, source: Source, localite: str) -> str:
    return f"{grandeur}_{source.jeton}_{localite}"


def _n_jours(annee: int, mois: int | None) -> int:
    if mois is None:
        return 366 if calendar.isleap(annee) else 365
    return calendar.monthrange(annee, mois)[1]


@cache
def _attendu(jeton: str) -> dict[tuple[str, str, int, int | None], float]:
    """Recalcul indépendant en décimal exact : ``{(grandeur, localité, année, mois): valeur}``.

    Les GHI des seeds ont 4 décimales : ``Decimal(repr(v))`` les relit exactement.
    HEP mensuel = GHI x jours ; annuel = somme des 12 mois (années complètes) ;
    productible = HEP x 0,8. Un seul arrondi, vers le flottant le plus proche.
    """
    source = _PAR_JETON[jeton]
    attendu: dict[tuple[str, str, int, int | None], float] = {}
    for loc, mesures in mesures_mensuelles(source.seed).items():
        par_annee: dict[int, list[Decimal]] = {}
        for (annee, mois), ghi in mesures.items():
            hep = Decimal(repr(ghi)) * _n_jours(annee, mois)
            attendu[(HEP, loc, annee, mois)] = float(hep)
            attendu[(PST, loc, annee, mois)] = float(hep * PR_THEORIQUE)
            par_annee.setdefault(annee, []).append(hep)
        for annee, heps in par_annee.items():
            if len(heps) == 12:  # années complètes seulement
                total = sum(heps, Decimal(0))
                attendu[(HEP, loc, annee, None)] = float(total)
                attendu[(PST, loc, annee, None)] = float(total * PR_THEORIQUE)
    return attendu


def _lignes(db_session: Session, source: Source) -> list[Row[Any]]:
    return list(
        db_session.execute(
            text(
                """
                SELECT gm.grandeur_code, loc.code AS localite, s.code AS serie,
                       gm.periode_type, gm.annee_debut, gm.annee_fin, gm.mois,
                       gm.valeur, gm.version_formule, gm.niveau_confiance_derive,
                       gm.statut, gm.valide_au
                FROM grandeurs_metier gm
                JOIN series_metadonnees s ON s.id = gm.series_metadonnees_id
                JOIN localites loc ON loc.id = gm.localite_id
                WHERE s.code = ANY(:c)
                """
            ),
            {"c": [_code(g, source, loc) for g in GRANDEURS for loc in _LOCALITES]},
        ).all()
    )


def test_grandeurs_referentiel(db_session: Session) -> None:
    """hep (id 1) et productible (id 4) : F1, stockee, v1 ; productible_mensuel inactive."""
    rows = db_session.execute(
        text(
            """
            SELECT g.code, g.id, g.famille, g.strategie_calcul, g.actif,
                   g.version_formule_actuelle, u.code AS unite
            FROM grandeurs_referentiel g JOIN unites u ON u.id = g.unite_id
            WHERE g.code IN ('hep', 'productible_specifique_theorique', 'productible_mensuel')
            """
        )
    ).all()
    etat = {r.code: (r.id, r.famille, r.strategie_calcul, r.actif, r.unite) for r in rows}
    assert etat == {
        HEP: (1, "F1", "stockee", True, "heure_equivalente_pleine"),
        PST: (4, "F1", "stockee", True, "kwh_par_kwc_periode"),
        "productible_mensuel": (6, "F1", "stockee", False, "kwh_par_kwc_mois"),
    }
    assert all(r.version_formule_actuelle == 1 for r in rows)
    # Les lignes mensuelles du productible relèvent de productible_specifique_theorique
    # (ADR-0023) : la grandeur désactivée reste vide.
    for table in ("series_metadonnees", "grandeurs_metier"):
        n = db_session.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE grandeur_code = 'productible_mensuel'")
        ).scalar_one()
        assert n == 0, table


@pytest.mark.parametrize("source", _SOURCES, ids=_id)
@pytest.mark.parametrize("grandeur", GRANDEURS)
def test_series_calculees(db_session: Session, grandeur: str, source: Source) -> None:
    """142 séries calcul_derive de kuma_calculs par (grandeur, source), période de la source."""
    rows = db_session.execute(
        text(
            """
            SELECT s.code, s.libelle, s.note_publique, s.methode_collecte, s.granularite,
                   s.periode_debut, s.periode_fin, src.code AS source, loc.code AS localite
            FROM series_metadonnees s
            JOIN sources src ON src.id = s.source_id
            JOIN localites loc ON loc.id = s.localite_id
            WHERE s.grandeur_code = :g AND s.code LIKE :prefixe
            """
        ),
        {"g": grandeur, "prefixe": f"{grandeur}\\_{source.jeton}\\_%"},
    ).all()
    assert {r.code for r in rows} == {_code(grandeur, source, loc) for loc in _LOCALITES}
    # Mise en garde ERA5 : relue sur la série brute, pour vérifier la même phrase que 0033.
    note_era5 = db_session.execute(
        text("SELECT note_publique FROM series_metadonnees WHERE code = :c"),
        {"c": "era5_ghi_mensuel_civ_dep_abidjan"},
    ).scalar_one()
    caveat = note_era5[note_era5.index(" Mise en garde : saut probable") :]
    for r in rows:
        assert r.code == _code(grandeur, source, r.localite)
        assert r.source == "kuma_calculs" and r.methode_collecte == "calcul_derive"
        assert r.granularite is None
        assert str(r.periode_debut) == f"{source.debut}-01-01"
        assert str(r.periode_fin) == f"{source.fin}-12-31"
        assert r.libelle.endswith(f"({source.debut}-{source.fin})"), r.libelle
        assert "(ADR-0023)" in r.note_publique
        if source.jeton == "era5":
            assert r.note_publique.endswith(caveat), r.code
        else:
            assert "PVGIS-ERA5" not in r.note_publique, r.code


@pytest.mark.parametrize("source", _SOURCES, ids=_id)
def test_completude_domaine_confiance(db_session: Session, source: Source) -> None:
    """12 mois par année de la source et une ligne annuelle par année, domaine physique."""
    rows = _lignes(db_session, source)
    par_serie: dict[str, dict[str, int]] = {}
    for r in rows:
        compte = par_serie.setdefault(r.serie, {"mensuel": 0, "annuel": 0})
        compte[r.periode_type] += 1
    assert len(par_serie) == 2 * len(_LOCALITES) == 2 * 142
    attendu = {"mensuel": 12 * source.nb_annees, "annuel": source.nb_annees}
    assert all(c == attendu for c in par_serie.values())
    for r in rows:
        assert r.niveau_confiance_derive == "B" and r.statut == "brut"
        assert r.version_formule == 1 and r.valide_au is None
        assert r.annee_debut == r.annee_fin
        assert (r.mois is None) == (r.periode_type == "annuel")
        plafond: float = HEP_MAX_PAR_JOUR * _n_jours(r.annee_debut, r.mois)
        if r.grandeur_code == PST:
            plafond *= 0.8
        assert 0.0 < r.valeur <= plafond, (r.serie, r.annee_debut, r.mois)
    assert {r.annee_debut for r in rows} == set(range(source.debut, source.fin + 1))


@pytest.mark.parametrize("source", _SOURCES, ids=_id)
def test_valeurs_fideles_au_calcul(db_session: Session, source: Source) -> None:
    """Chaque valeur gravée = recalcul indépendant depuis les seeds et CSV GHI, au bit près."""
    attendu = _attendu(source.jeton)
    assert len(attendu) == 2 * 142 * 13 * source.nb_annees
    grave = {
        (r.grandeur_code, r.localite, r.annee_debut, r.mois): r.valeur
        for r in _lignes(db_session, source)
    }
    assert grave.keys() == attendu.keys()
    differences = [k for k, v in grave.items() if v != attendu[k]]
    assert not differences, differences[:5]


def test_somme_mensuelle_egale_annuel(db_session: Session) -> None:
    """Fiche hep, § 8.3 : Σ des 12 mois = annuel (rel 1e-12), pour toutes les séries."""
    row = db_session.execute(
        text(
            """
            SELECT COUNT(*) AS annees,
                   COUNT(*) FILTER (WHERE nb_mois <> 12 OR annuel IS NULL) AS incompletes,
                   MAX(abs(somme - annuel) / annuel) AS ecart_relatif_max
            FROM (
                SELECT COUNT(*) FILTER (WHERE gm.periode_type = 'mensuel') AS nb_mois,
                       SUM(gm.valeur) FILTER (WHERE gm.periode_type = 'mensuel') AS somme,
                       MAX(gm.valeur) FILTER (WHERE gm.periode_type = 'annuel') AS annuel
                FROM grandeurs_metier gm
                WHERE gm.grandeur_code IN ('hep', 'productible_specifique_theorique')
                GROUP BY gm.series_metadonnees_id, gm.annee_debut
            ) t
            """
        )
    ).one()
    assert row.annees == 2 * 142 * sum(s.nb_annees for s in _SOURCES)
    assert row.incompletes == 0
    assert row.ecart_relatif_max < 1e-12


def test_equivalence_avec_le_journalier_herite(db_session: Session) -> None:
    """HEP journalier hérité (fiche, complétude stricte) = HEP gravé depuis le mensuel.

    34 localités du journalier NASA, 1991-2025 : la fonction de la fiche, appliquée
    au GHI journalier des CSV, et le HEP NASA gravé depuis le mensuel ne diffèrent
    que de l'arrondi des seeds (moins de 2·10⁻⁴ h_eq par jour de la période).
    """
    localites = [code for code, _, _, _ in points_journalier()]
    assert len(localites) == 34
    journalier: dict[str, list[tuple[date, float]]] = {loc: [] for loc in localites}
    contrats = (
        (CONTRATS_NASA_JOURNALIERS["ghi"], LOT_JOURNALIER),
        (CONTRATS_NASA_JOURNALIERS_EXTENSION["ghi"], LOT_EXTENSION),
    )
    for contrat, lot in contrats:
        for s in lire_series_journalieres(contrat, lot):
            journalier[s["localite_code"]] += s["mesures"]

    herite: dict[tuple[str, int, int | None], float] = {}
    for loc, mesures in journalier.items():
        agregation = _agreger_hep_journaliers(mesures)
        assert not agregation["annees_skip_completude"], loc
        assert not agregation["mois_skip_completude"], loc
        for ligne in agregation["lignes_mensuelles"] + agregation["lignes_annuelles"]:
            herite[(loc, ligne["annee_debut"], ligne["mois"])] = ligne["valeur"]
    assert len(herite) == 34 * 35 * 13  # 1991-2025, 12 mois + l'année

    rows = db_session.execute(
        text(
            """
            SELECT loc.code AS localite, gm.annee_debut AS annee, gm.mois, gm.valeur
            FROM grandeurs_metier gm
            JOIN series_metadonnees s ON s.id = gm.series_metadonnees_id
            JOIN localites loc ON loc.id = gm.localite_id
            WHERE s.code = ANY(:c)
            """
        ),
        {"c": [f"hep_nasa_power_{loc}" for loc in localites]},
    ).all()
    grave = {(r.localite, r.annee, r.mois): r.valeur for r in rows}
    assert grave.keys() == herite.keys()
    ecarts_par_jour = {
        cle: abs(herite[cle] - v) / _n_jours(cle[1], cle[2]) for cle, v in grave.items()
    }
    pire = max(ecarts_par_jour, key=ecarts_par_jour.__getitem__)
    assert ecarts_par_jour[pire] < TOLERANCE_PAR_JOUR, (pire, herite[pire], grave[pire])
    ecart_mensuel_max = max(abs(herite[k] - v) for k, v in grave.items() if k[2] is not None)
    ecart_annuel_max = max(abs(herite[k] - v) for k, v in grave.items() if k[2] is None)
    assert ecart_mensuel_max < 0.01 and ecart_annuel_max < 0.05  # h_eq (ADR-0023)
