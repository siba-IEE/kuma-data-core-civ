"""Données de seed pour la table ``localites`` (instance Côte d'Ivoire).

Premier lot « localités seules » du moteur dédié Côte d'Ivoire : la racine
continentale, le pays, et les **14 districts** (12 districts + 2 districts
autonomes : Abidjan et Yamoussoukro).

Périmètre et sourçage
---------------------
Ce lot pose la **nomenclature administrative de premier niveau** à partir
d'une source **authoritative et vérifiable hors-ligne** : la norme
**ISO 3166-2:CI** (codes et libellés français officiels, exposés via
``pycountry``). Le champ ``code_administratif_national`` reste ``NULL`` :
les sous-codes ISO 3166-2 de la Côte d'Ivoire sont à 2 lettres (``AB``,
``BS`` …) et ne satisfont pas la contrainte ``^[A-Z]{3}$`` de la colonne
(convention de code national à 3 lettres, cf. le décret guinéen sur
l'instance Guinée) ; le sous-code ISO est porté dans ``notes``.

Densification différée
----------------------
Les **coordonnées** (latitude / longitude), la **population** et le
**sourçage fin** (Wikidata, recensement RGPH-CI, chefs-lieux) sont laissés
à ``NULL`` et seront apportés dans une passe ultérieure nécessitant un
accès réseau aux sources ouvertes (Wikidata, HDX/COD-AB, INS Côte
d'Ivoire). Voir ``docs/contribution/genericite-pays.md``. Le schéma
autorise ces champs nullables ; aucune valeur n'est inventée ici.

Les niveaux inférieurs (31 régions au niveau ``prefecture``, 108
départements au niveau ``commune`` ou ``site`` selon le mapping retenu)
relèvent de la même passe sourcée et ne figurent pas dans ce lot.
"""

from __future__ import annotations

from typing import Any

# Note ré-employée pour les 14 districts : rappelle le périmètre du lot.
_NOTE_DISTRICT_DENSIFICATION: str = (
    "Coordonnées, population et chef-lieu à densifier en passe sourcée "
    "(accès réseau requis : Wikidata, HDX/COD-AB, INS Côte d'Ivoire). "
    "Libellé et code issus de la norme ISO 3166-2:CI."
)


def _district(code: str, nom: str, iso_3166_2: str, *, autonome: bool = False) -> dict[str, Any]:
    """Construit une entrée ``region_administrative`` pour un district CIV."""
    qualif = "District autonome" if autonome else "District"
    return {
        "code": code,
        "nom": nom,
        "type_localite": "region_administrative",
        "parent_code": "civ",
        "pays_iso3": "CIV",
        "latitude": None,
        "longitude": None,
        "altitude_metres": None,
        "population_estimee": None,
        "annee_population": None,
        "fuseau_horaire": "Africa/Abidjan",
        "notes": f"{qualif} de Côte d'Ivoire (ISO 3166-2 : {iso_3166_2}). {_NOTE_DISTRICT_DENSIFICATION}",
    }


LOCALITES_SEED: list[dict[str, Any]] = [
    # ===== Continent (1) =====
    {
        "code": "afrique",
        "nom": "Afrique",
        "type_localite": "continent",
        "parent_code": None,
        "pays_iso3": None,
        "latitude": None,
        "longitude": None,
        "altitude_metres": None,
        "population_estimee": 1_515_140_849,
        "annee_population": 2024,
        "fuseau_horaire": None,
        "notes": (
            "Population UN World Population Prospects 2024 (medium-fertility variant), "
            "date de référence 2024-07-01. Coordonnées centroid non renseignées : entité "
            "structurelle racine. Wikidata Q15. Source : https://population.un.org/wpp/."
        ),
    },
    # ===== Pays (1) =====
    {
        "code": "civ",
        "nom": "Côte d'Ivoire",
        "type_localite": "pays",
        "parent_code": "afrique",
        "pays_iso3": "CIV",
        "latitude": None,
        "longitude": None,
        "altitude_metres": None,
        "population_estimee": None,
        "annee_population": None,
        "fuseau_horaire": "Africa/Abidjan",
        "notes": (
            "Code ISO 3166-1 alpha-3 : CIV. Capitale politique : Yamoussoukro ; "
            "capitale économique : Abidjan. Fuseau UTC+00:00 (Africa/Abidjan). "
            "Premier lot « localités seules » : centroid, population (RGPH-CI) et "
            "sourçage Wikidata à densifier en passe sourcée (accès réseau requis). "
            "Aucune coordonnée n'est inventée hors-ligne."
        ),
    },
    # ===== Districts (14 : 12 districts + 2 districts autonomes), ISO 3166-2:CI =====
    _district("civ_abidjan", "Abidjan", "CI-AB", autonome=True),
    _district("civ_bas_sassandra", "Bas-Sassandra", "CI-BS"),
    _district("civ_comoe", "Comoé", "CI-CM"),
    _district("civ_denguele", "Denguélé", "CI-DN"),
    _district("civ_goh_djiboua", "Gôh-Djiboua", "CI-GD"),
    _district("civ_lacs", "Lacs", "CI-LC"),
    _district("civ_lagunes", "Lagunes", "CI-LG"),
    _district("civ_montagnes", "Montagnes", "CI-MG"),
    _district("civ_sassandra_marahoue", "Sassandra-Marahoué", "CI-SM"),
    _district("civ_savanes", "Savanes", "CI-SV"),
    _district("civ_vallee_du_bandama", "Vallée du Bandama", "CI-VB"),
    _district("civ_woroba", "Woroba", "CI-WR"),
    _district("civ_yamoussoukro", "Yamoussoukro", "CI-YM", autonome=True),
    _district("civ_zanzan", "Zanzan", "CI-ZZ"),
]


assert len(LOCALITES_SEED) == 16, f"Attendu 16 localités (1+1+14), obtenu {len(LOCALITES_SEED)}"

_codes_seen: set[str] = set()
for _entry in LOCALITES_SEED:
    _code = _entry["code"]
    assert _code not in _codes_seen, f"Code dupliqué dans LOCALITES_SEED : {_code!r}"
    _codes_seen.add(_code)
del _codes_seen, _entry, _code
