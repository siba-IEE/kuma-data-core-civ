"""Seeds de séries volumineuses (mensuelles et journalières) en CSV compressé (ADR-0015).

Au-delà des 3 points pilotes, les seeds en modules Python (``series_*_civ.py``)
deviennent trop lourds (dizaines de milliers de tuples). Les lots de couverture
nationale (régions, départements) sont donc stockés en **CSV gzip committés**
sous ``seeds/donnees/``, lus hors-ligne par les migrations : l'invariant « pas de
réseau dans une migration, chaque valeur versionnée » est inchangé.

Un fichier = une (source, grandeur, lot). Colonnes :
``localite_code, latitude, longitude, annee, mois, valeur`` (valeur en
kWh/m²/jour, moyenne journalière du mois, arrondie à 4 décimales).

L'écriture est **déterministe** (lignes triées, horodatage gzip nul) : régénérer
un fichier depuis les mêmes données produit les mêmes octets, ce qui rend la
continuité vérifiable par ``git diff``. La lecture **valide** tout : complétude
(12 mois × années du contrat, par localité), bornes physiques, doublons,
localités connues du référentiel.
"""

from __future__ import annotations

import csv
import gzip
import io
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from kuma_data_core.db.seeds.localites_civ_seed_data import LOCALITES_SEED

DOSSIER_DONNEES: Path = Path(__file__).resolve().parent / "donnees"
COLONNES: tuple[str, ...] = ("localite_code", "latitude", "longitude", "annee", "mois", "valeur")


@dataclass(frozen=True)
class ContratSerie:
    """Contrat d'une famille de séries (une source × une grandeur) pour un lot."""

    source_code: str
    source_id: int
    source_libelle: str  # pour les libellés de série, ex. "NASA POWER"
    prefixe_code: str  # préfixe du code de série, ex. "nasa_power_ghi_mensuel"
    grandeur_code: str
    methode_collecte: str
    annee_debut: int
    annee_fin: int
    borne_max: float  # kWh/m²/jour, garde-fou de sanité
    niveau_confiance: str = "B"
    granularite: str = "mensuel"

    @property
    def periode_debut(self) -> str:
        return f"{self.annee_debut}-01-01"

    @property
    def periode_fin(self) -> str:
        return f"{self.annee_fin}-12-31"

    @property
    def nb_mois(self) -> int:
        return (self.annee_fin - self.annee_debut + 1) * 12

    def nom_fichier(self, lot: str) -> str:
        return f"{self.prefixe_code}_{lot}.csv.gz"

    def code_serie(self, localite_code: str) -> str:
        return f"{self.prefixe_code}_{localite_code}"


def ecrire_series(
    contrat: ContratSerie,
    lot: str,
    series: list[tuple[str, float, float, list[tuple[int, int, float]]]],
) -> Path:
    """Écrit ``(localite_code, lat, lon, mesures)`` en CSV gzip déterministe."""
    lignes: list[tuple[Any, ...]] = []
    for code, lat, lon, mesures in series:
        for annee, mois, valeur in mesures:
            lignes.append((code, lat, lon, annee, mois, round(valeur, 4)))
    lignes.sort(key=lambda r: (r[0], r[3], r[4]))
    tampon = io.StringIO()
    ecrivain = csv.writer(tampon, lineterminator="\n")
    ecrivain.writerow(COLONNES)
    ecrivain.writerows(lignes)
    DOSSIER_DONNEES.mkdir(parents=True, exist_ok=True)
    cible = DOSSIER_DONNEES / contrat.nom_fichier(lot)
    with (
        cible.open("wb") as brut,
        gzip.GzipFile(filename="", mode="wb", fileobj=brut, mtime=0, compresslevel=9) as gz,
    ):
        gz.write(tampon.getvalue().encode("utf-8"))
    lire_series(contrat, lot)  # l'écriture n'est acceptée que si la relecture valide
    return cible


def lire_series(contrat: ContratSerie, lot: str) -> list[dict[str, Any]]:
    """Relit un lot et renvoie des séries au format des seeds Python (``SERIES``).

    Chaque série : ``code``, ``libelle``, ``localite_code``, ``latitude``,
    ``longitude``, ``mesures`` [(annee, mois, valeur)]. Lève ``ValueError`` si le
    fichier viole le contrat.
    """
    chemin = DOSSIER_DONNEES / contrat.nom_fichier(lot)
    with gzip.open(chemin, "rt", encoding="utf-8", newline="") as f:
        lecteur = csv.reader(f)
        entete = tuple(next(lecteur))
        if entete != COLONNES:
            raise ValueError(f"{chemin.name} : en-tête {entete!r}, {COLONNES!r} attendu.")
        par_loc: dict[str, dict[str, Any]] = {}
        for code, lat, lon, annee_s, mois_s, valeur_s in lecteur:
            annee, mois, valeur = int(annee_s), int(mois_s), float(valeur_s)
            if not (contrat.annee_debut <= annee <= contrat.annee_fin and 1 <= mois <= 12):
                raise ValueError(f"{chemin.name} : période hors contrat {code} {annee}-{mois}.")
            if not (0.0 <= valeur <= contrat.borne_max):
                raise ValueError(f"{chemin.name} : valeur hors bornes {code} {annee}-{mois}.")
            serie = par_loc.setdefault(
                code,
                {"latitude": float(lat), "longitude": float(lon), "mesures": {}},
            )
            if (annee, mois) in serie["mesures"]:
                raise ValueError(f"{chemin.name} : doublon {code} {annee}-{mois}.")
            serie["mesures"][(annee, mois)] = valeur

    noms = {e["code"]: e["nom"] for e in LOCALITES_SEED}
    sortie: list[dict[str, Any]] = []
    for code in sorted(par_loc):
        if code not in noms:
            raise ValueError(f"{chemin.name} : localité inconnue {code!r}.")
        mesures = sorted((a, m, v) for (a, m), v in par_loc[code]["mesures"].items())
        if len(mesures) != contrat.nb_mois:
            raise ValueError(
                f"{chemin.name} : {code} a {len(mesures)} mois, {contrat.nb_mois} attendus."
            )
        sortie.append(
            {
                "code": contrat.code_serie(code),
                "libelle": (
                    f"{contrat.grandeur_code.upper()} mensuel {contrat.source_libelle} — "
                    f"{noms[code]} ({contrat.annee_debut}-{contrat.annee_fin})"
                ),
                "localite_code": code,
                "latitude": par_loc[code]["latitude"],
                "longitude": par_loc[code]["longitude"],
                "mesures": mesures,
            }
        )
    return sortie


# --- Séries journalières (lot 3, table ``mesures_ressource``) ---------------------

COLONNES_JOURNALIERES: tuple[str, ...] = (
    "localite_code",
    "latitude",
    "longitude",
    "date",
    "valeur",
)


def nb_jours(contrat: ContratSerie) -> int:
    """Nombre de jours civils de la période du contrat (complétude journalière)."""
    return (date(contrat.annee_fin, 12, 31) - date(contrat.annee_debut, 1, 1)).days + 1


def ecrire_series_journalieres(
    contrat: ContratSerie,
    lot: str,
    series: list[tuple[str, float, float, list[tuple[date, float]]]],
) -> Path:
    """Écrit ``(localite_code, lat, lon, [(date, valeur)])`` en CSV gzip déterministe."""
    lignes = sorted(
        (code, lat, lon, jour.isoformat(), round(valeur, 4))
        for code, lat, lon, mesures in series
        for jour, valeur in mesures
    )
    tampon = io.StringIO()
    ecrivain = csv.writer(tampon, lineterminator="\n")
    ecrivain.writerow(COLONNES_JOURNALIERES)
    ecrivain.writerows(lignes)
    DOSSIER_DONNEES.mkdir(parents=True, exist_ok=True)
    cible = DOSSIER_DONNEES / contrat.nom_fichier(lot)
    with (
        cible.open("wb") as brut,
        gzip.GzipFile(filename="", mode="wb", fileobj=brut, mtime=0, compresslevel=9) as gz,
    ):
        gz.write(tampon.getvalue().encode("utf-8"))
    lire_series_journalieres(contrat, lot)  # acceptée seulement si la relecture valide
    return cible


def lire_series_journalieres(contrat: ContratSerie, lot: str) -> list[dict[str, Any]]:
    """Relit un lot journalier : séries avec ``mesures`` [(date, valeur)] triées.

    Valide en-tête, période, bornes, doublons, complétude (tous les jours civils
    du contrat, par localité) et localités du référentiel ; ``ValueError`` sinon.
    """
    chemin = DOSSIER_DONNEES / contrat.nom_fichier(lot)
    debut, fin = date(contrat.annee_debut, 1, 1), date(contrat.annee_fin, 12, 31)
    with gzip.open(chemin, "rt", encoding="utf-8", newline="") as f:
        lecteur = csv.reader(f)
        entete = tuple(next(lecteur))
        if entete != COLONNES_JOURNALIERES:
            raise ValueError(f"{chemin.name} : en-tête {entete!r} inattendu.")
        par_loc: dict[str, dict[str, Any]] = {}
        for code, lat, lon, jour_s, valeur_s in lecteur:
            jour, valeur = date.fromisoformat(jour_s), float(valeur_s)
            if not debut <= jour <= fin:
                raise ValueError(f"{chemin.name} : période hors contrat {code} {jour}.")
            if not (0.0 <= valeur <= contrat.borne_max):
                raise ValueError(f"{chemin.name} : valeur hors bornes {code} {jour}.")
            serie = par_loc.setdefault(
                code, {"latitude": float(lat), "longitude": float(lon), "mesures": {}}
            )
            if jour in serie["mesures"]:
                raise ValueError(f"{chemin.name} : doublon {code} {jour}.")
            serie["mesures"][jour] = valeur

    noms = {e["code"]: e["nom"] for e in LOCALITES_SEED}
    attendu = nb_jours(contrat)
    sortie: list[dict[str, Any]] = []
    for code in sorted(par_loc):
        if code not in noms:
            raise ValueError(f"{chemin.name} : localité inconnue {code!r}.")
        mesures = sorted(par_loc[code]["mesures"].items())
        if len(mesures) != attendu:
            raise ValueError(f"{chemin.name} : {code} a {len(mesures)} jours, {attendu} attendus.")
        sortie.append(
            {
                "code": contrat.code_serie(code),
                "libelle": (
                    f"{contrat.grandeur_code.upper()} journalier {contrat.source_libelle} — "
                    f"{noms[code]} ({contrat.annee_debut}-{contrat.annee_fin})"
                ),
                "localite_code": code,
                "latitude": par_loc[code]["latitude"],
                "longitude": par_loc[code]["longitude"],
                "mesures": mesures,
            }
        )
    return sortie
