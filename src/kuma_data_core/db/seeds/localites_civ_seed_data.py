"""Données de seed pour la table ``localites`` (instance Côte d'Ivoire).

Premier lot « localités seules » du moteur dédié Côte d'Ivoire : la racine
continentale, le pays, et les **14 districts** (12 districts + 2 districts
autonomes : Abidjan et Yamoussoukro).

Périmètre et sourçage
---------------------
Ce lot pose la **nomenclature administrative de premier niveau** à partir
d'une source **authoritative et vérifiable** : la norme **ISO 3166-2:CI**
(codes et libellés français officiels, exposés via ``pycountry``). Le champ
``code_administratif_national`` reste ``NULL`` : les sous-codes ISO 3166-2
de la Côte d'Ivoire sont à 2 lettres (``AB``, ``BS`` …) et ne satisfont pas
la contrainte ``^[A-Z]{3}$`` de la colonne (convention de code national à
3 lettres, cf. le décret guinéen sur l'instance Guinée) ; le sous-code ISO
est porté dans ``notes``.

Densification sourcée (passe 2)
-------------------------------
Les 14 districts sont désormais **densifiés en passe sourcée** (accès réseau)
selon la doctrine « aucune coordonnée inventée » :

* **Coordonnées** (``latitude`` / ``longitude``) : point représentatif de
  l'entité *district* correspondante sur **Wikidata** (propriété ``P625``).
  Le QID de l'entité district est cité dans ``notes`` pour la traçabilité.
  Les deux districts autonomes utilisent l'entité *district autonome*
  (Q19830972 Abidjan, Q19830973 Yamoussoukro), distincte de l'entité ville.
  **Règle de sélection déterministe** quand ``P625`` porte plusieurs
  valeurs : on retient le statement de rang ``preferred`` s'il existe,
  sinon le premier statement dans l'ordre document Wikidata parmi les rangs
  ``normal``. Trois entités sont concernées : ``CI-SV`` (Savanes) tranchée
  par le rang ``preferred`` ; ``CI-VB`` (Vallée du Bandama) et ``CI-DN``
  (Denguélé) par l'ordre document (deux statements ``normal`` équivalents).
* **Population** (``population_estimee`` / ``annee_population`` = 2021) :
  **RGPH 2021** (5ᵉ Recensement Général de la Population et de l'Habitat,
  INS Côte d'Ivoire). Le total par district est l'agrégat des comptages
  régionaux officiels publiés par l'INS
  (https://www.ins.ci/RGPH2021/RGPH2021-RESULTATS%20GLOBAUX_VF.pdf) ;
  contre-vérifié : Abidjan, Yamoussoukro et Zanzan concordent exactement
  avec les valeurs datées 2021 de Wikidata, le total national reconstitué
  vaut ~29,39 millions (chiffre officiel RGPH 2021 : 29 389 150). Étant un
  agrégat reconstruit (le PDF INS n'étant pas récupérable en ligne), chaque
  total porte une incertitude de l'ordre de ±quelques unités face au chiffre
  district primaire.
* **Chef-lieu** de district : capitale administrative de l'entité district
  sur Wikidata (propriété ``P36``, rang ``normal`` ; les 14 valeurs ont été
  résolues et concordent avec le décret 2011-263), portée dans ``notes``.

L'``altitude_metres`` reste ``NULL`` : une région administrative n'a pas
d'altitude ponctuelle univoque ; aucune valeur n'est inventée.

La racine continentale et le pays ``civ`` conservent leur sourçage initial
(le centroïde et la population nationale du pays relèvent d'une densification
ultérieure, hors périmètre de cette passe « districts »).

Les niveaux inférieurs (31 régions au niveau ``prefecture``, 108
départements au niveau ``commune`` ou ``site`` selon le mapping retenu)
relèvent d'une passe sourcée ultérieure et ne figurent pas dans ce lot.
"""

from __future__ import annotations

from typing import Any

# Source primaire de la population (réemployée dans chaque note de district).
_SOURCE_RGPH: str = "RGPH 2021 (INS Côte d'Ivoire), agrégat des régions"


def _district(
    code: str,
    nom: str,
    iso_3166_2: str,
    latitude: float,
    longitude: float,
    population_2021: int,
    chef_lieu: str,
    wikidata_qid: str,
    *,
    autonome: bool = False,
) -> dict[str, Any]:
    """Construit une entrée ``region_administrative`` densifiée pour un district CIV.

    Coordonnées : point représentatif Wikidata (``P625``) de l'entité district.
    Population : total RGPH 2021 (INS). Chef-lieu et QID portés dans ``notes``.
    """
    qualif = "District autonome" if autonome else "District"
    notes = (
        f"{qualif} de Côte d'Ivoire (ISO 3166-2 : {iso_3166_2}). "
        f"Chef-lieu : {chef_lieu}. "
        f"Population {population_2021} hab. — {_SOURCE_RGPH}. "
        f"Coordonnées : point représentatif Wikidata {wikidata_qid} (P625). "
        f"Libellé et code issus de la norme ISO 3166-2:CI."
    )
    return {
        "code": code,
        "nom": nom,
        "type_localite": "region_administrative",
        "parent_code": "civ",
        "pays_iso3": "CIV",
        "latitude": latitude,
        "longitude": longitude,
        "altitude_metres": None,
        "population_estimee": population_2021,
        "annee_population": 2021,
        "fuseau_horaire": "Africa/Abidjan",
        "notes": notes,
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
            "Centroïde et population nationale (RGPH 2021 : 29 389 150 hab.) à "
            "densifier en passe ultérieure. Aucune coordonnée n'est inventée hors-ligne."
        ),
    },
    # ===== Districts (14 : 12 districts + 2 districts autonomes), ISO 3166-2:CI =====
    # Coordonnées : Wikidata P625 (QID cité) ; population : RGPH 2021 (INS).
    _district(
        "civ_abidjan",
        "Abidjan",
        "CI-AB",
        5.33333333,
        -4.01666667,
        6_321_017,
        "Abidjan",
        "Q19830972",
        autonome=True,
    ),
    _district(
        "civ_bas_sassandra",
        "Bas-Sassandra",
        "CI-BS",
        4.751389,
        -6.638611,
        2_687_176,
        "San-Pédro",
        "Q20980352",
    ),
    _district(
        "civ_comoe", "Comoé", "CI-CM", 6.73333333, -3.48333333, 1_501_336, "Abengourou", "Q16629374"
    ),
    _district(
        "civ_denguele", "Denguélé", "CI-DN", 9.5, -7.41699982, 436_015, "Odienné", "Q20980374"
    ),
    _district(
        "civ_goh_djiboua",
        "Gôh-Djiboua",
        "CI-GD",
        6.13333333,
        -5.93333333,
        2_088_440,
        "Gagnoa",
        "Q21003640",
    ),
    _district("civ_lacs", "Lacs", "CI-LC", 6.65, -4.7, 1_488_531, "Dimbokro", "Q20980363"),
    _district(
        "civ_lagunes", "Lagunes", "CI-LG", 5.93333333, -4.21666667, 2_042_623, "Dabou", "Q20980365"
    ),
    _district("civ_montagnes", "Montagnes", "CI-MG", 7.4, -7.55, 3_027_023, "Man", "Q20980366"),
    _district(
        "civ_sassandra_marahoue",
        "Sassandra-Marahoué",
        "CI-SM",
        6.88333333,
        -6.45,
        2_720_877,
        "Daloa",
        "Q20365127",
    ),
    _district(
        "civ_savanes",
        "Savanes",
        "CI-SV",
        9.41666667,
        -5.61666667,
        2_159_435,
        "Korhogo",
        "Q21002161",
    ),
    _district(
        "civ_vallee_du_bandama",
        "Vallée du Bandama",
        "CI-VB",
        8.13333333,
        -5.1,
        1_964_929,
        "Bouaké",
        "Q21002356",
    ),
    _district("civ_woroba", "Woroba", "CI-WR", 8.48333333, -6.6, 1_184_813, "Séguéla", "Q20980371"),
    _district(
        "civ_yamoussoukro",
        "Yamoussoukro",
        "CI-YM",
        6.81667,
        -5.28333,
        422_072,
        "Yamoussoukro",
        "Q19830973",
        autonome=True,
    ),
    _district(
        "civ_zanzan", "Zanzan", "CI-ZZ", 8.61666667, -3.15, 1_344_865, "Bondoukou", "Q21003689"
    ),
]


assert len(LOCALITES_SEED) == 16, f"Attendu 16 localités (1+1+14), obtenu {len(LOCALITES_SEED)}"

_codes_seen: set[str] = set()
for _entry in LOCALITES_SEED:
    _code = _entry["code"]
    assert _code not in _codes_seen, f"Code dupliqué dans LOCALITES_SEED : {_code!r}"
    _codes_seen.add(_code)
del _codes_seen, _entry, _code
