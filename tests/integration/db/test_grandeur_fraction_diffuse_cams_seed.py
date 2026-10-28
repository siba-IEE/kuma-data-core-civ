"""Tests d'intégration de la fraction diffuse CAMS (migration 0040, ADR-0025).

Deuxième source de ``fraction_diffuse`` : DHI/GHI **CAMS Radiation** aux **142
localités** (3 pilotes + 139 localités des lots nationaux), mensuelle et annuelle
2005-2025, à côté de la fraction diffuse NASA POWER (ADR-0014, ADR-0017).
Vérifie le contrat (séries ``calcul_derive`` de ``kuma_calculs``), la complétude
(252 mois et 21 ans par localité), le domaine physique [0, 1], la **coexistence**
avec la série NASA (deux valeurs par localité et période commune, NASA intacte)
et la **fidélité** : chaque valeur gravée est recalculée indépendamment depuis
les sources brutes CAMS (seeds pilotes, CSV des lots et de l'extension 2021+) —
``Σ DHI / Σ GHI`` sur les jours de la période, reconstruit depuis les moyennes
journalières mensuelles.
"""

from __future__ import annotations

import calendar

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.db.seeds import series_cams_dhi_mensuel_civ as cams_dhi
from kuma_data_core.db.seeds import series_cams_ghi_mensuel_civ as cams_ghi
from tests.integration.db.mesures_brutes import mesures_mensuelles

pytestmark = pytest.mark.integration

GRANDEUR_CODE = "fraction_diffuse"
PREFIXE = "fraction_diffuse_cams_"
_LOCALITES = set(mesures_mensuelles(cams_ghi))  # 3 pilotes + 139 localités des lots
ANNEES = range(2005, 2026)
NB_MENSUEL = 12 * len(ANNEES) * len(_LOCALITES)  # 252 mois x 142 localités = 35 784
NB_ANNUEL = len(ANNEES) * len(_LOCALITES)  # 21 ans x 142 localités = 2 982
# La base somme en numeric, le test en flottants : écart de l'ordre de 1e-16.
REL = 1e-12


def _attendu() -> tuple[dict[tuple[str, int, int], float], dict[tuple[str, int], float]]:
    """Recalcule mensuel (moy DHI / moy GHI) et annuel (pondéré par les jours)."""
    dhi, ghi = mesures_mensuelles(cams_dhi), mesures_mensuelles(cams_ghi)
    assert set(dhi) == set(ghi)
    mensuel: dict[tuple[str, int, int], float] = {}
    annuel: dict[tuple[str, int], float] = {}
    for loc, dhi_loc in dhi.items():
        assert set(dhi_loc) == set(ghi[loc])  # mêmes mois 2005-2025 dans les deux séries
        sommes: dict[int, list[float]] = {}
        for (annee, mois), v_dhi in dhi_loc.items():
            v_ghi = ghi[loc][(annee, mois)]
            mensuel[(loc, annee, mois)] = v_dhi / v_ghi
            n = calendar.monthrange(annee, mois)[1]
            s = sommes.setdefault(annee, [0.0, 0.0, 0.0])
            s[0] += v_dhi * n
            s[1] += v_ghi * n
            s[2] += 1
        for annee, (s_dhi, s_ghi, nb_mois) in sommes.items():
            assert nb_mois == 12
            annuel[(loc, annee)] = s_dhi / s_ghi
    return mensuel, annuel


def test_series_calculees(db_session: Session) -> None:
    """142 séries calcul_derive, source kuma_calculs, période 2005-2025."""
    rows = db_session.execute(
        text(
            """
            SELECT s.code, loc.code AS localite, s.methode_collecte, s.granularite,
                   src.code AS source, s.periode_debut, s.periode_fin, s.libelle
            FROM series_metadonnees s
            JOIN sources src ON src.id = s.source_id
            JOIN localites loc ON loc.id = s.localite_id
            WHERE s.grandeur_code = :c AND starts_with(s.code, :p)
            """
        ),
        {"c": GRANDEUR_CODE, "p": PREFIXE},
    ).all()
    assert len(rows) == len(_LOCALITES) == 142
    for r in rows:
        assert r.localite in _LOCALITES and r.code == f"{PREFIXE}{r.localite}"
        assert r.source == "kuma_calculs" and r.methode_collecte == "calcul_derive"
        assert r.granularite is None
        assert str(r.periode_debut) == "2005-01-01" and str(r.periode_fin) == "2025-12-31"
        assert r.libelle.startswith("Fraction diffuse CAMS Radiation — ")


def test_completude_domaine_confiance(db_session: Session) -> None:
    """35 784 mensuelles + 2 982 annuelles, valeurs dans [0, 1], confiance B, statut brut."""
    rows = db_session.execute(
        text(
            """
            SELECT gm.periode_type, gm.mois, gm.valeur, gm.niveau_confiance_derive, gm.statut,
                   gm.version_formule, gm.annee_debut, gm.annee_fin
            FROM grandeurs_metier gm JOIN series_metadonnees s ON s.id = gm.series_metadonnees_id
            WHERE gm.grandeur_code = :c AND starts_with(s.code, :p) AND gm.valide_au IS NULL
            """
        ),
        {"c": GRANDEUR_CODE, "p": PREFIXE},
    ).all()
    assert sum(r.periode_type == "mensuel" for r in rows) == NB_MENSUEL
    assert sum(r.periode_type == "annuel" for r in rows) == NB_ANNUEL
    for r in rows:
        assert 0.0 <= r.valeur <= 1.0
        assert r.niveau_confiance_derive == "B" and r.statut == "brut"
        assert r.version_formule == 1 and r.annee_debut == r.annee_fin
        assert (r.mois is None) == (r.periode_type == "annuel")
    assert {r.annee_debut for r in rows} == set(ANNEES)


def test_valeurs_fideles_au_calcul(db_session: Session) -> None:
    """Chaque valeur gravée = recalcul indépendant depuis les seeds CAMS DHI et GHI."""
    mensuel, annuel = _attendu()
    assert len(mensuel) == NB_MENSUEL and len(annuel) == NB_ANNUEL
    rows = db_session.execute(
        text(
            """
            SELECT loc.code AS localite, gm.periode_type, gm.annee_debut AS annee,
                   gm.mois, gm.valeur
            FROM grandeurs_metier gm JOIN localites loc ON loc.id = gm.localite_id
            JOIN series_metadonnees s ON s.id = gm.series_metadonnees_id
            WHERE gm.grandeur_code = :c AND starts_with(s.code, :p) AND gm.valide_au IS NULL
            """
        ),
        {"c": GRANDEUR_CODE, "p": PREFIXE},
    ).all()
    assert len(rows) == NB_MENSUEL + NB_ANNUEL
    for r in rows:
        if r.periode_type == "mensuel":
            attendu = mensuel[(r.localite, r.annee, r.mois)]
        else:
            attendu = annuel[(r.localite, r.annee)]
        assert r.valeur == pytest.approx(attendu, rel=REL), (r.localite, r.annee, r.mois)


def test_coexistence_avec_nasa(db_session: Session) -> None:
    """Deux sources par (localité, période) sur 2005-2025 ; NASA 2001-2004 seule.

    L'identité de ``grandeurs_metier`` inclut la série : la fraction diffuse NASA
    (325 lignes par localité, 2001-2025) reste intacte à côté de la série CAMS.
    """
    rows = db_session.execute(
        text(
            """
            SELECT COUNT(*) FILTER (WHERE n = 2) AS doubles,
                   COUNT(*) FILTER (WHERE n = 1 AND annee_debut < 2005) AS nasa_seule,
                   COUNT(*) FILTER (WHERE n = 1 AND annee_debut >= 2005 OR n > 2) AS anomalies,
                   SUM(nasa) AS lignes_nasa
            FROM (
                SELECT gm.localite_id, gm.periode_type, gm.annee_debut,
                       COALESCE(gm.mois, 0) AS mois, COUNT(*) AS n,
                       COUNT(*) FILTER (
                           WHERE starts_with(s.code, 'fraction_diffuse_nasa_power_')
                       ) AS nasa
                FROM grandeurs_metier gm
                JOIN series_metadonnees s ON s.id = gm.series_metadonnees_id
                WHERE gm.grandeur_code = :c AND gm.valide_au IS NULL
                GROUP BY 1, 2, 3, 4
            ) t
            """
        ),
        {"c": GRANDEUR_CODE},
    ).one()
    assert rows.doubles == NB_MENSUEL + NB_ANNUEL
    assert rows.nasa_seule == 142 * 4 * 13  # 2001-2004 : 12 mois + 1 année, NASA seule
    assert rows.anomalies == 0
    assert rows.lignes_nasa == 142 * 325
