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

Le pays ``civ`` est lui aussi densifié : centroïde Wikidata Q1008 (``P625``)
et population nationale RGPH 2021 (29 389 150 hab.), chiffre officiel absent
de Wikidata mais recoupé par la somme des 14 districts. La racine
continentale ``afrique`` conserve son sourçage initial (entité structurelle,
sans centroïde).

Régions (niveau ``prefecture``)
-------------------------------
Les **31 régions** actuelles (réforme de 2011) sont ajoutées au niveau
générique ``prefecture`` (cf. ADR-0005 : ``type_localite`` est un axe
technique, l'identité ivoirienne reste dans ``nom`` / ``notes``). Chaque
région est rattachée à son **district parent** (relation Wikidata ``P131``),
avec coordonnées Wikidata (``P625``, règle de rang de l'ADR coordonnées),
chef-lieu, et population **RGPH 2021** (INS) dont la somme par district
reproduit exactement le total du district. Réserves documentées en ``notes`` :

* **N'Zi** et **La Mé** : population non recoupée par Wikidata (mono-sourcée
  RGPH/Wikipédia) ;
* **Hambol** : le point ``P625`` de l'entité région est erroné sur Wikidata
  (co-localisé avec Bouaké) ; on retient la coordonnée du chef-lieu Katiola ;
* **Codes ISO 3166-2** : la révision 2020 a supprimé les codes de niveau
  région ; les 5 anciens codes encore présents (CI-02, CI-12, CI-13, CI-14,
  CI-17) sont portés en ``notes`` avec la mention « périmé », jamais comme
  code courant.

Les 108 départements (niveau ``commune``) relèvent d'une passe ultérieure.
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


# Libellé du district parent, réemployé dans les notes des régions.
_DISTRICT_NOM: dict[str, str] = {
    "civ_bas_sassandra": "Bas-Sassandra",
    "civ_comoe": "Comoé",
    "civ_denguele": "Denguélé",
    "civ_goh_djiboua": "Gôh-Djiboua",
    "civ_lacs": "Lacs",
    "civ_lagunes": "Lagunes",
    "civ_montagnes": "Montagnes",
    "civ_sassandra_marahoue": "Sassandra-Marahoué",
    "civ_savanes": "Savanes",
    "civ_vallee_du_bandama": "Vallée du Bandama",
    "civ_woroba": "Woroba",
    "civ_zanzan": "Zanzan",
}


def _region(
    code: str,
    nom: str,
    parent_code: str,
    wikidata_qid: str,
    latitude: float,
    longitude: float,
    chef_lieu: str,
    population_2021: int,
    iso_perime: str | None,
    coord_chef_lieu: bool,
    mono_source: bool,
) -> dict[str, Any]:
    """Construit une entrée ``prefecture`` (région ivoirienne) rattachée à son district.

    Le niveau générique ``prefecture`` porte la région ivoirienne (cf.
    ADR-0005) ; ``type_localite`` n'est pas le nom du palier réel, l'identité
    est dans ``nom`` / ``notes``. Coordonnées : point Wikidata (``P625``) sauf
    repli documenté (``coord_chef_lieu``). Population : RGPH 2021 (INS).
    """
    mono = (
        " Population non recoupée par Wikidata (mono-sourcée RGPH/Wikipédia)."
        if mono_source
        else ""
    )
    if coord_chef_lieu:
        coord_line = (
            f"Coordonnées : repli sur le chef-lieu {chef_lieu} (Wikidata) — le "
            f"point P625 de l'entité région {wikidata_qid} est erroné (co-localisé "
            f"avec le district)."
        )
    else:
        coord_line = f"Coordonnées : point représentatif Wikidata {wikidata_qid} (P625)."
    iso_line = (
        f" Ancien code ISO 3166-2 (système pré-2020, périmé) : {iso_perime}." if iso_perime else ""
    )
    notes = (
        f"Région de Côte d'Ivoire (niveau générique « prefecture » ; district "
        f"parent : {_DISTRICT_NOM[parent_code]}). Chef-lieu : {chef_lieu}. "
        f"Population {population_2021} hab. — RGPH 2021 (INS Côte d'Ivoire).{mono} "
        f"{coord_line}{iso_line}"
    )
    return {
        "code": code,
        "nom": nom,
        "type_localite": "prefecture",
        "parent_code": parent_code,
        "pays_iso3": "CIV",
        "latitude": float(latitude),
        "longitude": float(longitude),
        "altitude_metres": None,
        "population_estimee": population_2021,
        "annee_population": 2021,
        "fuseau_horaire": "Africa/Abidjan",
        "notes": notes,
    }


# 31 régions actuelles (réforme 2011), rattachées à leur district par Wikidata
# P131 ; population RGPH 2021 (somme exacte = total du district parent).
# Tuple : (code, nom, district_parent, QID, lat, lon, chef-lieu, pop_2021,
#          ancien_code_iso_périmé | None, coord_repli_chef_lieu, pop_mono_sourcée)
_REGIONS_DATA: tuple[tuple[Any, ...], ...] = (
    (
        "civ_gbokle",
        "Gbôklé",
        "civ_bas_sassandra",
        "Q22080829",
        4.95,
        -6.08333333,
        "Sassandra",
        460980,
        None,
        False,
        False,
    ),
    (
        "civ_nawa",
        "Nawa",
        "civ_bas_sassandra",
        "Q22080902",
        5.78333333,
        -6.6,
        "Soubré",
        1165472,
        None,
        False,
        False,
    ),
    (
        "civ_san_pedro",
        "San-Pédro",
        "civ_bas_sassandra",
        "Q22080959",
        4.75,
        -6.63333333,
        "San-Pédro",
        1060724,
        None,
        False,
        False,
    ),
    (
        "civ_indenie_djuablin",
        "Indénié-Djuablin",
        "civ_comoe",
        "Q16643482",
        6.73333333,
        -3.48333333,
        "Abengourou",
        716443,
        None,
        False,
        False,
    ),
    (
        "civ_sud_comoe",
        "Sud-Comoé",
        "civ_comoe",
        "Q842495",
        5.5,
        -3.25,
        "Aboisso",
        784893,
        "CI-13",
        False,
        False,
    ),
    (
        "civ_folon",
        "Folon",
        "civ_denguele",
        "Q3075118",
        10.0,
        -7.83333333,
        "Minignan",
        146209,
        None,
        False,
        False,
    ),
    (
        "civ_kabadougou",
        "Kabadougou",
        "civ_denguele",
        "Q24756897",
        9.5,
        -7.56666667,
        "Odienné",
        289806,
        None,
        False,
        False,
    ),
    (
        "civ_goh",
        "Gôh",
        "civ_goh_djiboua",
        "Q24754296",
        6.13333333,
        -5.93333333,
        "Gagnoa",
        985282,
        None,
        False,
        False,
    ),
    (
        "civ_loh_djiboua",
        "Lôh-Djiboua",
        "civ_goh_djiboua",
        "Q21084295",
        5.83333333,
        -5.36666667,
        "Divo",
        1103158,
        None,
        False,
        False,
    ),
    (
        "civ_belier",
        "Bélier",
        "civ_lacs",
        "Q19677085",
        6.92,
        -5.05,
        "Toumodi",
        415593,
        None,
        False,
        False,
    ),
    (
        "civ_iffou",
        "Iffou",
        "civ_lacs",
        "Q21082947",
        7.25,
        -3.86666667,
        "Daoukro",
        378560,
        None,
        False,
        False,
    ),
    (
        "civ_moronou",
        "Moronou",
        "civ_lacs",
        "Q20743715",
        6.65,
        -4.2,
        "Bongouanou",
        439755,
        None,
        False,
        False,
    ),
    (
        "civ_n_zi",
        "N'Zi",
        "civ_lacs",
        "Q22080918",
        6.65,
        -4.7,
        "Dimbokro",
        254623,
        None,
        False,
        True,
    ),
    (
        "civ_agneby_tiassa",
        "Agnéby-Tiassa",
        "civ_lagunes",
        "Q16525480",
        6.0,
        -4.0,
        "Agboville",
        865951,
        None,
        False,
        False,
    ),
    (
        "civ_grands_ponts",
        "Grands-Ponts",
        "civ_lagunes",
        "Q22080838",
        5.31666667,
        -4.38333333,
        "Dabou",
        450007,
        None,
        False,
        False,
    ),
    (
        "civ_la_me",
        "La Mé",
        "civ_lagunes",
        "Q17638767",
        6.16666667,
        -3.98333333,
        "Adzopé",
        726665,
        None,
        False,
        True,
    ),
    (
        "civ_cavally",
        "Cavally",
        "civ_montagnes",
        "Q20641894",
        6.53333333,
        -7.48333333,
        "Guiglo",
        708241,
        None,
        False,
        False,
    ),
    (
        "civ_guemon",
        "Guémon",
        "civ_montagnes",
        "Q21082912",
        6.41666667,
        -7.5,
        "Duékoué",
        930873,
        None,
        False,
        False,
    ),
    (
        "civ_tonkpi",
        "Tonkpi",
        "civ_montagnes",
        "Q17355578",
        7.4,
        -7.55,
        "Man",
        1387909,
        None,
        False,
        False,
    ),
    (
        "civ_haut_sassandra",
        "Haut-Sassandra",
        "civ_sassandra_marahoue",
        "Q845709",
        7.0,
        -6.5,
        "Daloa",
        1739697,
        "CI-02",
        False,
        False,
    ),
    (
        "civ_marahoue",
        "Marahoué",
        "civ_sassandra_marahoue",
        "Q839083",
        7.16666667,
        -5.83333333,
        "Bouaflé",
        981180,
        "CI-12",
        False,
        False,
    ),
    (
        "civ_bagoue",
        "Bagoué",
        "civ_savanes",
        "Q2879161",
        9.51666667,
        -6.48333333,
        "Boundiali",
        515890,
        None,
        False,
        False,
    ),
    (
        "civ_poro",
        "Poro",
        "civ_savanes",
        "Q22080932",
        9.41666667,
        -5.61666667,
        "Korhogo",
        1040461,
        None,
        False,
        False,
    ),
    (
        "civ_tchologo",
        "Tchologo",
        "civ_savanes",
        "Q17355495",
        9.58333333,
        -5.18333333,
        "Ferkessédougou",
        603084,
        None,
        False,
        False,
    ),
    (
        "civ_gbeke",
        "Gbêkê",
        "civ_vallee_du_bandama",
        "Q22080826",
        7.68333333,
        -5.01666667,
        "Bouaké",
        1352900,
        None,
        False,
        False,
    ),
    (
        "civ_hambol",
        "Hambol",
        "civ_vallee_du_bandama",
        "Q21082919",
        8.13333333,
        -5.1,
        "Katiola",
        612029,
        None,
        True,
        False,
    ),
    (
        "civ_bafing",
        "Bafing",
        "civ_woroba",
        "Q799800",
        8.5,
        -7.5,
        "Touba",
        262850,
        "CI-17",
        False,
        False,
    ),
    (
        "civ_bere",
        "Béré",
        "civ_woroba",
        "Q22080753",
        8.06666667,
        -6.18333333,
        "Mankono",
        492151,
        None,
        False,
        False,
    ),
    (
        "civ_worodougou",
        "Worodougou",
        "civ_woroba",
        "Q846056",
        8.5,
        -6.33333333,
        "Séguéla",
        429812,
        "CI-14",
        False,
        False,
    ),
    (
        "civ_bounkani",
        "Bounkani",
        "civ_zanzan",
        "Q19830823",
        9.26666667,
        -3.0,
        "Bouna",
        427037,
        None,
        False,
        False,
    ),
    (
        "civ_gontougo",
        "Gontougo",
        "civ_zanzan",
        "Q17355494",
        8.03333333,
        -2.78333333,
        "Bondoukou",
        917828,
        None,
        False,
        False,
    ),
)


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
        "latitude": 8.0,
        "longitude": -6.0,
        "altitude_metres": None,
        "population_estimee": 29_389_150,
        "annee_population": 2021,
        "fuseau_horaire": "Africa/Abidjan",
        "notes": (
            "Code ISO 3166-1 alpha-3 : CIV. Capitale politique : Yamoussoukro ; "
            "capitale économique : Abidjan. Fuseau UTC+00:00 (Africa/Abidjan). "
            "Centroïde : point représentatif Wikidata Q1008 (P625, rang normal ; "
            "valeur grossière arrondie au degré). Population nationale RGPH 2021 "
            "(INS Côte d'Ivoire) : 29 389 150 hab. — chiffre officiel absent de "
            "Wikidata (P1082 s'arrête à 2017 puis 2023), recoupé par la somme des "
            "14 districts (29 389 152, écart d'arrondi +2). Altitude non renseignée "
            "(pas d'altitude ponctuelle univoque pour un pays)."
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
    # ===== Régions (31 : niveau générique prefecture), parent = district (ADR-0005) =====
    *(_region(*_r) for _r in _REGIONS_DATA),
]


assert len(LOCALITES_SEED) == 47, (
    f"Attendu 47 localités (1 continent + 1 pays + 14 districts + 31 régions), "
    f"obtenu {len(LOCALITES_SEED)}"
)

_codes_seen: set[str] = set()
for _entry in LOCALITES_SEED:
    _code = _entry["code"]
    assert _code not in _codes_seen, f"Code dupliqué dans LOCALITES_SEED : {_code!r}"
    _codes_seen.add(_code)
del _codes_seen, _entry, _code
