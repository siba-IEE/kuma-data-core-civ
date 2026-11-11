#!/usr/bin/env python3
"""Exporteur du RDS Côte d'Ivoire : séries brutes courantes, en CSV lisibles par source.

Lit dans la base les mesures **courantes** (``valide_au IS NULL``, statut non
déprécié) des séries brutes des 142 localités (``points_nationaux``) et écrit,
dans le dépôt ``rds-cote-divoire`` (``--sortie``) :

- ``data/localites.csv`` : code, nom, niveau, région, district, coordonnées,
  population RGPH 2021 ;
- ``data/<source>/mensuel_<début>_<fin>.csv`` : une ligne par (localité, année,
  mois), une colonne par grandeur ;
- ``data/<source>/journalier_<début>_<fin>.csv`` : une ligne par (localité,
  jour), un fichier par décennie (1991-2000, 2001-2010, 2011-2020, 2021-2025),
  borné à la période de la source ;
- ``MANIFEST.csv`` : chemin, source, granularité, période, lignes, localités,
  empreinte SHA-256 de chaque fichier de données.

Colonnes : codes du référentiel des grandeurs (``ghi``, ``t2m``…), unités de
ses grandeurs. Une cellule vide signifie que la source ne sert pas de valeur
(lacune, ou grandeur que la source ne sert pas encore à cette date). Valeurs
telles que gravées, 4 décimales au plus, sans arrondi supplémentaire.

Garde-fous : chaque famille (source, grandeur, granularité) brute de la base
est exportée, ni plus ni moins (``FAMILLES``) ; 142 séries par famille, une par
localité ; jamais deux valeurs pour la même clé. Sortie déterministe : même
base, mêmes octets.

Usage : ``uv run python scripts/exporter_rds.py --sortie ../rds-cote-divoire``
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from kuma_data_core.db.seeds.lots_civ import points_nationaux
from kuma_data_core.db.session import get_engine

DECENNIES: tuple[tuple[int, int], ...] = ((1991, 2000), (2001, 2010), (2011, 2020), (2021, 2025))
SOURCE_CALCUL = "kuma_calculs"


@dataclass(frozen=True)
class Famille:
    """Une source du RDS : dossier, code de source en base, grandeurs et granularités."""

    dossier: str
    source: str
    grandeurs: tuple[str, ...]
    granularites: tuple[str, ...]


FAMILLES: tuple[Famille, ...] = (
    Famille(
        "nasa-power",
        "nasa_power",
        (
            "ghi",
            "dni",
            "dhi",
            "albedo_surface",
            "t2m",
            "rh2m",
            "vent_2m",
            "vent_10m",
            "precipitation",
        ),
        ("mensuel", "journalier"),
    ),
    Famille(
        "era5",
        "ecmwf_era5",
        ("t2m", "rh2m", "vent_10m", "precipitation"),
        ("mensuel", "journalier"),
    ),
    Famille(
        "cams-radiation",
        "cams_radiation",
        (
            "ghi",
            "dni",
            "dhi",
            "ghi_ciel_clair",
            "dni_ciel_clair",
            "dhi_ciel_clair",
            "irradiation_extraterrestre",
            "fiabilite_satellite",
        ),
        ("mensuel", "journalier"),
    ),
    Famille("cams-eac4", "cams_eac4", ("pm2_5", "pm10"), ("mensuel", "journalier")),
    Famille("pvgis-sarah3", "sarah3_monthly", ("ghi", "dni"), ("mensuel",)),
    Famille("pvgis-era5", "era5_pvgis", ("ghi", "dni"), ("mensuel",)),
    Famille("gpm-imerg", "gpm_imerg", ("precipitation",), ("journalier",)),
    Famille("chirps", "chirps", ("precipitation",), ("journalier",)),
    Famille(
        "agera5", "agera5", ("et0", "t2m_min", "t2m_max", "vpd_tmax"), ("mensuel", "journalier")
    ),
)

_SQL_FAMILLES = """
    SELECT x.code AS source, s.grandeur_code, s.granularite, COUNT(*) AS series,
           COUNT(DISTINCT s.localite_id) AS localites,
           MIN(s.periode_debut) AS debut, MAX(s.periode_fin) AS fin
    FROM series_metadonnees s
    JOIN sources x ON x.id = s.source_id
    JOIN localites l ON l.id = s.localite_id
    WHERE x.code <> :calcul AND s.methode_collecte IS DISTINCT FROM 'calcul_derive'
      AND s.granularite IN ('mensuel', 'journalier') AND l.code = ANY(:loc)
    GROUP BY 1, 2, 3
"""


def _valeur(v: float | None) -> str:
    """Valeur écrite telle que gravée (4 décimales au plus), cellule vide si absente."""
    if v is None:
        return ""
    texte = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if texte in ("", "-0") else texte


def _ecrire(chemin: Path, entete: list[str], lignes: Iterable[list[str]]) -> tuple[int, str]:
    """Écrit un CSV (LF, UTF-8) ; renvoie le nombre de lignes de données et le SHA-256."""
    tampon = io.StringIO()
    ecrivain = csv.writer(tampon, lineterminator="\n")
    ecrivain.writerow(entete)
    n = 0
    for ligne in lignes:
        ecrivain.writerow(ligne)
        n += 1
    contenu = tampon.getvalue().encode("utf-8")
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(contenu)
    return n, hashlib.sha256(contenu).hexdigest()


def _verifier_familles(
    conn: sa.Connection, localites: list[str]
) -> dict[tuple[str, str, str], Any]:
    """Familles brutes en base = ``FAMILLES`` ; 142 séries par famille, une par localité."""
    en_base = {
        (r.source, r.grandeur_code, r.granularite): r
        for r in conn.execute(sa.text(_SQL_FAMILLES), {"calcul": SOURCE_CALCUL, "loc": localites})
    }
    attendues = {(f.source, g, gr) for f in FAMILLES for g in f.grandeurs for gr in f.granularites}
    if set(en_base) != attendues:
        raise SystemExit(
            f"Familles en base hors export : {sorted(set(en_base) - attendues)} ; "
            f"absentes de la base : {sorted(attendues - set(en_base))}."
        )
    for cle, r in en_base.items():
        if (r.series, r.localites) != (len(localites), len(localites)):
            raise SystemExit(f"{cle} : {r.series} séries, {r.localites} localités.")
    return en_base


def _pivot(
    conn: sa.Connection,
    famille: Famille,
    granularite: str,
    localites: list[str],
    bornes: tuple[date, date] | None,
) -> Iterator[list[str]]:
    """Lignes (localité, période, une valeur par grandeur), triées, sans doublon."""
    cols = ", ".join(
        f"MAX(m.valeur) FILTER (WHERE s.grandeur_code = '{g}') AS v_{i}, "
        f"COUNT(*) FILTER (WHERE s.grandeur_code = '{g}') AS n_{i}"
        for i, g in enumerate(famille.grandeurs)
    )
    if granularite == "mensuel":
        table, cle, filtre = "mesures_ressource_mensuelles", "m.annee, m.mois", ""
    else:
        table, cle = "mesures_ressource", "m.instant_mesure"
        filtre = "AND m.instant_mesure BETWEEN :debut AND :fin"
    requete = sa.text(
        f"""
        SELECT l.code AS localite, {cle}, {cols}
        FROM {table} m
        JOIN series_metadonnees s ON s.id = m.serie_id
        JOIN sources x ON x.id = s.source_id
        JOIN localites l ON l.id = s.localite_id
        WHERE x.code = :source AND s.granularite = :granularite
          AND s.grandeur_code = ANY(:grandeurs) AND l.code = ANY(:loc)
          AND s.methode_collecte IS DISTINCT FROM 'calcul_derive'
          AND m.valide_au IS NULL AND m.statut <> 'deprecie' {filtre}
        GROUP BY l.code, {cle}
        ORDER BY l.code, {cle}
        """
    )
    params: dict[str, Any] = {
        "source": famille.source,
        "granularite": granularite,
        "grandeurs": list(famille.grandeurs),
        "loc": localites,
    }
    if bornes is not None:
        params["debut"], params["fin"] = bornes
    resultat = conn.execution_options(stream_results=True, yield_per=50_000).execute(
        requete, params
    )
    for r in resultat:
        valeurs = []
        for i in range(len(famille.grandeurs)):
            if getattr(r, f"n_{i}") > 1:
                raise SystemExit(f"{famille.dossier} : doublon {tuple(r)[:3]!r}.")
            valeurs.append(_valeur(getattr(r, f"v_{i}")))
        if granularite == "mensuel":
            yield [r.localite, str(r.annee), str(r.mois), *valeurs]
        else:
            yield [r.localite, r.instant_mesure.isoformat(), *valeurs]


def _localites(conn: sa.Connection, localites: list[str]) -> Iterator[list[str]]:
    rows = conn.execute(
        sa.text(
            """
            SELECT l.code, l.nom, l.type_localite, l.latitude, l.longitude, l.population_estimee,
                   p.type_localite AS type_parent, p.nom AS nom_parent, gp.nom AS nom_grand_parent
            FROM localites l
            JOIN localites p ON p.id = l.parent_id
            LEFT JOIN localites gp ON gp.id = p.parent_id
            WHERE l.code = ANY(:loc)
            ORDER BY l.code
            """
        ),
        {"loc": localites},
    ).all()
    if [r.code for r in rows] != sorted(localites):
        raise SystemExit(f"{len(rows)} localités en base, {len(localites)} attendues.")
    for r in rows:
        if r.type_localite == "prefecture":  # région, sous un district
            niveau, region, district = "region", r.nom, r.nom_parent
        elif r.type_parent == "prefecture":  # département, sous une région
            niveau, region, district = "departement", r.nom_parent, r.nom_grand_parent
        else:  # département rattaché directement à un district autonome
            niveau, region, district = "departement", "", r.nom_parent
        population = "" if r.population_estimee is None else str(r.population_estimee)
        yield [
            r.code,
            r.nom,
            niveau,
            region,
            district,
            _valeur(float(r.latitude)) if r.latitude is not None else "",
            _valeur(float(r.longitude)) if r.longitude is not None else "",
            population,
        ]


def main(sortie: Path) -> None:
    if not (sortie / ".git").is_dir():
        raise SystemExit(f"{sortie} n'est pas un dépôt git (clone de rds-cote-divoire attendu).")
    localites = sorted(code for code, _, _, _ in points_nationaux())
    manifeste: list[list[str]] = []
    with get_engine().connect() as conn:
        familles = _verifier_familles(conn, localites)
        n, _ = _ecrire(
            sortie / "data/localites.csv",
            [
                "code",
                "nom",
                "niveau",
                "region",
                "district",
                "latitude",
                "longitude",
                "population_2021",
            ],
            _localites(conn, localites),
        )
        print(f"data/localites.csv : {n} localités")
        for f in FAMILLES:
            for gr in f.granularites:
                debut = min(familles[(f.source, g, gr)].debut for g in f.grandeurs).year
                fin = max(familles[(f.source, g, gr)].fin for g in f.grandeurs).year
                if gr == "mensuel":
                    tranches: list[tuple[int, int] | None] = [None]
                    entete = ["localite", "annee", "mois", *f.grandeurs]
                else:
                    tranches = [
                        (max(a, debut), min(b, fin))
                        for a, b in DECENNIES
                        if a <= fin and b >= debut
                    ]
                    entete = ["localite", "date", *f.grandeurs]
                for tranche in tranches:
                    a, b = tranche if tranche is not None else (debut, fin)
                    bornes = None if tranche is None else (date(a, 1, 1), date(b, 12, 31))
                    chemin = f"data/{f.dossier}/{gr}_{a}_{b}.csv"
                    lignes, sha = _ecrire(
                        sortie / chemin, entete, _pivot(conn, f, gr, localites, bornes)
                    )
                    manifeste.append(
                        [chemin, f.dossier, gr, f"{a}-{b}", str(lignes), str(len(localites)), sha]
                    )
                    print(f"{chemin} : {lignes} lignes", flush=True)
    _ecrire(
        sortie / "MANIFEST.csv",
        ["chemin", "source", "granularite", "periode", "lignes", "localites", "sha256"],
        sorted(manifeste),
    )
    print(f"MANIFEST.csv : {len(manifeste)} fichiers")


if __name__ == "__main__":
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--sortie", type=Path, required=True, help="clone de rds-cote-divoire")
    main(parseur.parse_args().sortie)
