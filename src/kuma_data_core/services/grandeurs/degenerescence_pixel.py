"""Calcul de la grandeur F1 ``degenerescence_pixel``.

2e couche d'honnêteté de l'atlas (distincte de l'écart inter-source) : pour chaque
(localite, source, parametre), dit si ce point **partage sa cellule source** avec
d'autres préfectures (donnée qui se répète) ou s'il est **réellement résolu**.

Méthode empirique : sur une **grille fixe** (NASA POWER), deux points dans la même
cellule lisent **la valeur de la cellule** -> leurs séries mensuelles sont
**strictement identiques**. On groupe les localités par vecteur de valeurs identique
(égalité exacte) : un groupe de taille > 1 = des **jumeaux-pixel**. C'est ainsi que le
cas Kindia/Mamou a été constaté. Aucune définition de grille n'est inventée.

Nuance par type de source :

- **grille fixe** (NASA radiation CERES 1deg, météo MERRA 0.5deg) : compte de
  jumeaux **mesuré** ;
- **service interpolé au point** (SARAH-3 / CAMS 5 km) : valeurs distinctes par
  construction -> compte **0** naturellement ; le sens est porté par un **caveat de
  résolution** (finesse sub-maille illusoire), pas par le compte.

Sortie : 1 ligne ``grandeurs_metier`` par (localite x source x parametre),
``periode_type='statique'``, ``valeur`` = nombre de jumeaux (0 = point résolu),
``niveau_confiance_derive='B'`` (la confiance **A est réservée aux mesures terrain**,
déjà tenue par le GHI/DNI sol Kankan/Tarambaly ESMAP-WAPP. La dégénérescence est
**exacte**, mais l'échelle A/B/C classe la fiabilité d'une *mesure de substrat*, pas la
certitude d'un fait structurel : B + caveat, jamais A). La série source (climato
mensuelle) porte le FK ``series_metadonnees_id`` (précédent
``indicateur_qualite_donnees``, lui-même B). Le groupe de jumeaux + les caveats vivent
dans ``commentaire_editorial``.

Pattern fonctions pures + orchestrateur I/O, miroir de ``referentiels`` /
``ecart_dni_cams``. Calcul déterministe depuis la base, aucun réseau.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TypedDict

from sqlalchemy import text
from sqlalchemy.orm import Session

# === Constantes module =====================================================

GRANDEUR_DEGENERESCENCE: str = "degenerescence_pixel"
NIVEAU_CONFIANCE_DERIVE: str = "B"
VERSION_FORMULE: int = 1

# Caveat de nature appose sur chaque ligne : dit l'exactitude SANS usurper le
# palier A (reserve terrain). La degenerescence est un fait structurel exact, mais
# A/B/C classe la fiabilite d'une mesure de substrat, pas la certitude d'un fait.
_CAVEAT_CONFIANCE: str = (
    " Indicateur exact (identite structurelle observee, non modelise), tague confiance B : "
    "A est reservee aux mesures terrain et l'echelle A/B/C classe la fiabilite d'une mesure "
    "de substrat, pas la certitude d'un fait structurel."
)


class _ConfigSource(TypedDict):
    """Un (source, parametre) dont on mesure la degenerescence de pixel."""

    source_code: str
    grandeur_code: str
    periode_debut: str  # borne de la serie climato mensuelle a comparer
    grille: str
    resolution: str
    grille_fixe: bool


# Epine radiative posee aux 33 localites. Radiation NASA = CERES SYN1deg 1deg ;
# meteo NASA = MERRA-2 0.5deg (grille deux fois plus fine, donc moins de
# degenerescence) ; SARAH-3 / CAMS = services interpoles 5 km (compte 0 + caveat).
_CERES = ("CERES SYN1deg", "1 deg (110 km)")
_MERRA = ("MERRA-2", "0.5 deg (55 km)")
_INTERP = "5 km"

_CONFIG: tuple[_ConfigSource, ...] = (
    # NASA radiation (CERES 1deg) : ghi sur 1991-2020, les 4 autres sur 2001-2020.
    {
        "source_code": "nasa_power",
        "grandeur_code": "ghi",
        "periode_debut": "1991-01-01",
        "grille": _CERES[0],
        "resolution": _CERES[1],
        "grille_fixe": True,
    },
    {
        "source_code": "nasa_power",
        "grandeur_code": "dni",
        "periode_debut": "2001-01-01",
        "grille": _CERES[0],
        "resolution": _CERES[1],
        "grille_fixe": True,
    },
    {
        "source_code": "nasa_power",
        "grandeur_code": "dhi",
        "periode_debut": "2001-01-01",
        "grille": _CERES[0],
        "resolution": _CERES[1],
        "grille_fixe": True,
    },
    {
        "source_code": "nasa_power",
        "grandeur_code": "kt",
        "periode_debut": "2001-01-01",
        "grille": _CERES[0],
        "resolution": _CERES[1],
        "grille_fixe": True,
    },
    {
        "source_code": "nasa_power",
        "grandeur_code": "albedo_surface",
        "periode_debut": "2001-01-01",
        "grille": _CERES[0],
        "resolution": _CERES[1],
        "grille_fixe": True,
    },
    # NASA meteo (MERRA-2 0.5deg), tout sur 1991-2020.
    {
        "source_code": "nasa_power",
        "grandeur_code": "t2m",
        "periode_debut": "1991-01-01",
        "grille": _MERRA[0],
        "resolution": _MERRA[1],
        "grille_fixe": True,
    },
    {
        "source_code": "nasa_power",
        "grandeur_code": "rh2m",
        "periode_debut": "1991-01-01",
        "grille": _MERRA[0],
        "resolution": _MERRA[1],
        "grille_fixe": True,
    },
    {
        "source_code": "nasa_power",
        "grandeur_code": "vent_2m",
        "periode_debut": "1991-01-01",
        "grille": _MERRA[0],
        "resolution": _MERRA[1],
        "grille_fixe": True,
    },
    {
        "source_code": "nasa_power",
        "grandeur_code": "vent_10m",
        "periode_debut": "1991-01-01",
        "grille": _MERRA[0],
        "resolution": _MERRA[1],
        "grille_fixe": True,
    },
    # Services interpoles 5 km (compte 0 naturel + caveat de resolution).
    {
        "source_code": "sarah3_monthly",
        "grandeur_code": "ghi",
        "periode_debut": "2021-01-01",
        "grille": "PVGIS-SARAH3 (interpole)",
        "resolution": _INTERP,
        "grille_fixe": False,
    },
    {
        "source_code": "cams_radiation",
        "grandeur_code": "dni",
        "periode_debut": "2021-01-01",
        "grille": "CAMS Heliosat-4 (interpole)",
        "resolution": _INTERP,
        "grille_fixe": False,
    },
)


# === Fonction pure =========================================================


def _grouper_par_pixel(vecteurs: dict[int, tuple[float, ...]]) -> dict[int, list[int]]:
    """Pour chaque localite, la liste des AUTRES localites au vecteur identique.

    Egalite **exacte** : sur grille fixe, l'identite est binaire. Toute quasi-egalite
    non exacte = points distincts (releve de l'ecart, pas de la degenerescence).

    Returns:
        ``{localite_id: [jumeaux_localite_id tries]}`` (liste vide = point resolu).
    """
    groupes: dict[tuple[float, ...], list[int]] = defaultdict(list)
    for loc_id, vec in vecteurs.items():
        groupes[vec].append(loc_id)
    jumeaux: dict[int, list[int]] = {}
    for membres in groupes.values():
        for loc_id in membres:
            jumeaux[loc_id] = sorted(m for m in membres if m != loc_id)
    return jumeaux


def _commentaire(cfg: _ConfigSource, grandeur: str, codes_jumeaux: list[str]) -> str:
    """Texte d'honnetete : groupe de jumeaux pour les grilles fixes, caveat de
    resolution pour les sources interpolees."""
    if not cfg["grille_fixe"]:
        base = (
            f"Source interpolee au point ({cfg['grille']}, {cfg['resolution']}) : valeurs "
            f"distinctes par construction. Resolution reelle {cfg['resolution']} -> finesse "
            f"sub-maille illusoire (caveat de resolution, pas une degenerescence mesurable)."
        )
    elif codes_jumeaux:
        liste = ", ".join(codes_jumeaux)
        base = (
            f"Degenerescence de pixel : partage la cellule {cfg['grille']} ({cfg['resolution']}) "
            f"avec {len(codes_jumeaux)} autre(s) point(s) ({liste}). Series {grandeur} identiques "
            f"(meme pixel source) -> ne pas presenter comme des mesures independantes "
            f"(D-29 generalise)."
        )
    else:
        base = (
            f"Point resolu sur {cfg['grille']} ({cfg['resolution']}) : aucun autre point "
            f"partageant la cellule pour {grandeur}."
        )
    return base + _CAVEAT_CONFIANCE


# === Orchestrateur I/O =====================================================


def calculer_et_inserer_degenerescence(session: Session) -> int:
    """Calcule et insere ``degenerescence_pixel`` dans ``grandeurs_metier``.

    Pour chaque (source, parametre) de l'epine radiative, lit les series climato
    mensuelles de toutes les localites, groupe par vecteur identique (jumeaux-pixel),
    et insere 1 ligne statique par localite (valeur = nombre de jumeaux).

    Args:
        session : session SQLAlchemy active (l'appelant commit).

    Returns:
        Nombre de lignes inserees.
    """
    nb_insere = 0
    for cfg in _CONFIG:
        rows = session.execute(
            text(
                """
                SELECT l.id AS loc_id, l.code AS loc_code, sm.id AS serie_id,
                       EXTRACT(YEAR FROM sm.periode_debut)::int AS an_deb,
                       EXTRACT(YEAR FROM sm.periode_fin)::int AS an_fin,
                       m.annee, m.mois, m.valeur
                FROM mesures_ressource_mensuelles m
                JOIN series_metadonnees sm ON sm.id = m.serie_id
                JOIN sources s ON s.id = sm.source_id
                JOIN localites l ON l.id = sm.localite_id
                WHERE s.code = :src AND sm.grandeur_code = :g
                  AND sm.granularite = 'mensuel' AND sm.periode_debut = :pdeb
                  AND m.valide_au IS NULL AND m.statut <> 'deprecie'
                ORDER BY l.code, m.annee, m.mois
                """
            ),
            {"src": cfg["source_code"], "g": cfg["grandeur_code"], "pdeb": cfg["periode_debut"]},
        ).all()

        # Reconstruit, par localite : id, code, serie source, fenetre, vecteur de valeurs.
        vecteurs: dict[int, tuple[float, ...]] = {}
        meta: dict[int, dict[str, object]] = {}
        accum: dict[int, list[float]] = defaultdict(list)
        for r in rows:
            accum[int(r.loc_id)].append(float(r.valeur))
            meta.setdefault(
                int(r.loc_id),
                {
                    "code": r.loc_code,
                    "serie_id": int(r.serie_id),
                    "an_deb": int(r.an_deb),
                    "an_fin": int(r.an_fin),
                },
            )
        for loc_id, vals in accum.items():
            vecteurs[loc_id] = tuple(vals)

        if not vecteurs:
            continue  # source/parametre absent (garde defensive)

        jumeaux = _grouper_par_pixel(vecteurs)
        code_par_id = {loc_id: str(m["code"]) for loc_id, m in meta.items()}

        lignes: list[dict[str, object]] = []
        for loc_id, ids_jumeaux in jumeaux.items():
            m = meta[loc_id]
            codes_jumeaux = sorted(code_par_id[j] for j in ids_jumeaux)
            lignes.append(
                {
                    "grandeur_code": GRANDEUR_DEGENERESCENCE,
                    "localite_id": loc_id,
                    "series_metadonnees_id": m["serie_id"],
                    "periode_type": "statique",
                    "annee_debut": m["an_deb"],
                    "annee_fin": m["an_fin"],
                    "mois": None,
                    "version_formule": VERSION_FORMULE,
                    "valeur": float(len(ids_jumeaux)),
                    "niveau_confiance_derive": NIVEAU_CONFIANCE_DERIVE,
                    "commentaire": _commentaire(cfg, cfg["grandeur_code"], codes_jumeaux),
                }
            )

        if lignes:
            session.execute(
                text(
                    """
                    INSERT INTO grandeurs_metier
                        (grandeur_code, localite_id, series_metadonnees_id,
                         periode_type, annee_debut, annee_fin, mois,
                         version_formule, valeur, niveau_confiance_derive,
                         commentaire_editorial)
                    VALUES
                        (:grandeur_code, :localite_id, :series_metadonnees_id,
                         :periode_type, :annee_debut, :annee_fin, :mois,
                         :version_formule, :valeur, :niveau_confiance_derive,
                         :commentaire)
                    """
                ),
                lignes,
            )
            nb_insere += len(lignes)

    session.flush()
    return nb_insere
