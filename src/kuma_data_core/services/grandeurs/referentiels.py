"""Calculs des 3 grandeurs F1 calculee_volee référentielles.

Module de calcul et d'insertion des 3 grandeurs métier externes
multi-référence :

- ``ecart_relatif_referentiel`` : divergence inter-source contemporaine
  entre NASA POWER Kuma 2021-2025 (agrégé mensuel à la volée depuis
  ``mesures_ressource``) et PVGIS-SARAH3 ICDR 2021-2023 (lookup direct
  dans ``mesures_ressource_mensuelles``). Plage 2021-2023 = chevauchement
  effective. Sortie : 216 lignes (36 mois x 6 villes).

- ``rang_referentiel_temporel`` : percentile de la valeur Kuma 2021-2025
  dans la climatologie NASA POWER 1991-2020 stratifiée par mois calendrier
  (n=30 par mois). Cohérence intra-source NASA POWER. Sortie : 360 lignes.

- ``rang_referentiel_spatial`` : rang ordinal 1-6 de la valeur Kuma dans
  le pool des 6 villes Kuma pour le même mois. Cohérence intra-périmètre.
  Sortie : 360 lignes.

Total : 936 lignes ``grandeurs_metier`` insérées.

Pattern fonctions pures + orchestrateur I/O.

Niveau de confiance dérivé uniforme ``'B'`` sur les 936 lignes.
Justifications :

- écart relatif : signal indirect par construction (combinaison 2 sources).
- rang temporel : caveat sur validation publique quantile mapping
  NASA POWER limitée au longwave.
- rang spatial : limite statistique n=6 villes.

Mappings réels :

- ``grandeur_code`` (VARCHAR FK vers ``grandeurs_referentiel.code``) au
  lieu de ``grandeur_referentiel_id``.
- Unité héritée via la FK (``grandeurs_referentiel.unite_id``).
- Période encodée via ``(periode_type='mensuel', annee_debut=annee,
  annee_fin=annee, mois=mois)`` au lieu de ``(periode_debut, periode_fin)``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict

from sqlalchemy import text
from sqlalchemy.orm import Session

# === Constantes module =====================================================

GRANDEUR_ECART: str = "ecart_relatif_referentiel"
GRANDEUR_RANG_TEMPOREL: str = "rang_referentiel_temporel"
GRANDEUR_RANG_SPATIAL: str = "rang_referentiel_spatial"

NIVEAU_CONFIANCE_DERIVE_1_7B: str = "B"
VERSION_FORMULE_1_7B: int = 1

ANNEE_KUMA_DEBUT: int = 2021
ANNEE_KUMA_FIN: int = 2025
ANNEE_SARAH3_FIN: int = 2023
ANNEE_CLIMATO_DEBUT: int = 1991
ANNEE_CLIMATO_FIN: int = 2020

N_VILLES_KUMA: int = 6

SEUIL_SARAH3_MIN_DEFAUT: float = 0.5
"""Seuil minimal (kWh/m²/jour) en dessous duquel la valeur SARAH-3
mensuelle est jugée pathologique et l'écart relatif n'est pas calculé
(stocké NULL plutôt qu'une valeur amplifiée mathématiquement absurde).

Justification : la formule ``(k - s) / s * 100`` diverge quand
``s -> 0``. Pour le GHI Afrique tropicale ouest, toute valeur SARAH-3
< 0.5 kWh/m²/jour est physiquement inexplicable (couverture nuageuse
totale en plein hiver donnerait 2-3 minimum) - c'est nécessairement
un défaut amont (sentinelle mal nettoyée, divergence d'unité dans
l'ingestion, etc.).

Le seuil est paramétrable via :func:`recalculer_ecart_relatif_referentiel`
pour pouvoir l'ajuster sans modifier le code.
"""


# === Types ================================================================


class ContexteVille(TypedDict):
    """Contexte d'ingestion par localité pour l'orchestrateur référentiels."""

    localite_id: int
    code_serie_kuma_daily: str
    code_serie_sarah3: str
    code_serie_power_1991_2020: str


class CalculReferentielsResultat(TypedDict):
    """Résultat d'un appel à :func:`calculer_et_inserer_referentiels`."""

    nb_ecart_insere: int
    nb_rang_temporel_insere: int
    nb_rang_spatial_insere: int
    nb_total: int


# === Fonctions pures ======================================================


def _agreger_mensuel(valeurs_journalieres: Sequence[float]) -> float:
    """Moyenne arithmétique mensuelle (sans I/O).

    Args:
        valeurs_journalieres : 28-31 valeurs typiquement.

    Returns:
        Moyenne.

    Raises:
        ValueError : si vide.
    """
    if not valeurs_journalieres:
        raise ValueError("Aucune valeur journaliere a agreger")
    return sum(valeurs_journalieres) / len(valeurs_journalieres)


def _calcul_ecart_relatif(valeur_kuma: float, valeur_sarah3: float) -> float:
    """Écart relatif inter-source en pourcent signé.

    Formule : ``(kuma - sarah3) / sarah3 * 100``.

    Raises:
        ValueError : si ``valeur_sarah3`` nulle.
    """
    if valeur_sarah3 == 0.0:
        raise ValueError("Ecart relatif indefini : valeur SARAH-3 nulle")
    return (valeur_kuma - valeur_sarah3) / valeur_sarah3 * 100.0


def _calcul_rang_temporel(valeur_kuma: float, distribution: Sequence[float]) -> float:
    """Percentile dans la distribution (formule type 7 numpy/R).

    Formule : ``p = (rang - 1) / (n - 1) * 100`` avec capping ``[0, 100]``.
    Rang gère les ex-aequo par demi-rang (interpolation linéaire).

    Raises:
        ValueError : si n < 2.
    """
    if len(distribution) < 2:
        raise ValueError(f"Distribution insuffisante : n={len(distribution)} (>= 2 requis)")

    n = len(distribution)
    nb_strict_inf = sum(1 for v in distribution if v < valeur_kuma)
    nb_egaux = sum(1 for v in distribution if v == valeur_kuma)
    rang = nb_strict_inf + (nb_egaux + 1) / 2.0
    percentile = (rang - 1) / (n - 1) * 100.0
    return max(0.0, min(100.0, percentile))


def _calcul_rang_spatial(valeurs_par_localite: dict[int, float]) -> dict[int, int]:
    """Rang ordinal 1-N dans le pool des N localités (tri croissant).

    Ex-aequo gérées par ordre numpy.argsort (premier arrivé, premier
    servi) - comportement déterministe par l'ordre du dict d'entrée.

    Returns:
        ``{localite_id: rang_ordinal_1_a_N}``.

    Raises:
        ValueError : si dict vide.
    """
    if not valeurs_par_localite:
        raise ValueError("Aucune valeur a classer")
    items_tries = sorted(valeurs_par_localite.items(), key=lambda kv: kv[1])
    return {loc_id: idx + 1 for idx, (loc_id, _) in enumerate(items_tries)}


# === Helpers I/O ==========================================================


def _lire_kuma_mensuel(session: Session, code_serie: str) -> dict[tuple[int, int], float]:
    """Agrège en moyenne mensuelle les mesures Kuma NASA POWER 2021-2025."""
    rows = session.execute(
        text(
            """
            SELECT
                EXTRACT(YEAR FROM mr.instant_mesure)::int AS annee,
                EXTRACT(MONTH FROM mr.instant_mesure)::int AS mois,
                AVG(mr.valeur) AS moyenne
            FROM mesures_ressource mr
            JOIN series_metadonnees sm ON sm.id = mr.serie_id
            WHERE sm.code = :code
              AND mr.valide_au IS NULL
              AND mr.statut <> 'deprecie'
            GROUP BY annee, mois
            ORDER BY annee, mois
            """
        ),
        {"code": code_serie},
    ).all()
    return {(int(r.annee), int(r.mois)): float(r.moyenne) for r in rows}


def _lire_mensuel(session: Session, code_serie: str) -> dict[tuple[int, int], float]:
    """Lit les valeurs mensuelles d'une série depuis ``mesures_ressource_mensuelles``."""
    rows = session.execute(
        text(
            """
            SELECT m.annee, m.mois, m.valeur
            FROM mesures_ressource_mensuelles m
            JOIN series_metadonnees sm ON sm.id = m.serie_id
            WHERE sm.code = :code
              AND m.valide_au IS NULL
              AND m.statut <> 'deprecie'
            ORDER BY m.annee, m.mois
            """
        ),
        {"code": code_serie},
    ).all()
    return {(int(r.annee), int(r.mois)): float(r.valeur) for r in rows}


def _bulk_insert_grandeurs_metier(session: Session, lignes: list[dict[str, object]]) -> None:
    """Insert bulk dans ``grandeurs_metier`` (helper interne)."""
    if not lignes:
        return
    session.execute(
        text(
            """
            INSERT INTO grandeurs_metier
                (grandeur_code, localite_id, series_metadonnees_id,
                 periode_type, annee_debut, annee_fin, mois,
                 version_formule, valeur, niveau_confiance_derive)
            VALUES
                (:grandeur_code, :localite_id, :series_metadonnees_id,
                 :periode_type, :annee_debut, :annee_fin, :mois,
                 :version_formule, :valeur, :niveau_confiance_derive)
            """
        ),
        lignes,
    )


# === Orchestrateur I/O ====================================================


def calculer_et_inserer_referentiels(
    *,
    session: Session,
    contextes_villes: Sequence[ContexteVille],
    serie_id_par_grandeur_localite: dict[tuple[str, int], int],
) -> CalculReferentielsResultat:
    """Calcule et insère les 936 lignes des 3 grandeurs F1 calculee_volee.

    Args:
        session : session SQLAlchemy active (add+flush, pas commit).
        contextes_villes : séquence par localité avec clés :
            ``localite_id``, ``code_serie_kuma_daily``, ``code_serie_sarah3``,
            ``code_serie_power_1991_2020``.
        serie_id_par_grandeur_localite : mapping
            ``{(grandeur_code, localite_id): series_metadonnees_id}`` pour
            les 18 séries calculées pré-insérées par la migration appelante.

    Returns:
        :class:`CalculReferentielsResultat`.
    """
    nb_ecart = 0
    nb_rang_temporel = 0
    nb_rang_spatial = 0

    # Pré-charge des mesures Kuma mensuelles (utilisées par les 3 étapes)
    kuma_par_localite: dict[int, dict[tuple[int, int], float]] = {}
    for ctx in contextes_villes:
        loc_id = ctx["localite_id"]
        kuma_par_localite[loc_id] = _lire_kuma_mensuel(session, ctx["code_serie_kuma_daily"])

    # === ecart_relatif_referentiel (216 lignes attendues) ====================
    for ctx in contextes_villes:
        loc_id = ctx["localite_id"]
        sarah3 = _lire_mensuel(session, ctx["code_serie_sarah3"])
        serie_id = serie_id_par_grandeur_localite[(GRANDEUR_ECART, loc_id)]

        lignes: list[dict[str, object]] = []
        for annee in range(ANNEE_KUMA_DEBUT, ANNEE_SARAH3_FIN + 1):
            for mois in range(1, 13):
                kuma_v = kuma_par_localite[loc_id].get((annee, mois))
                sarah3_v = sarah3.get((annee, mois))
                if kuma_v is None or sarah3_v is None:
                    continue
                ecart_pct = _calcul_ecart_relatif(kuma_v, sarah3_v)
                lignes.append(
                    {
                        "grandeur_code": GRANDEUR_ECART,
                        "localite_id": loc_id,
                        "series_metadonnees_id": serie_id,
                        "periode_type": "mensuel",
                        "annee_debut": annee,
                        "annee_fin": annee,
                        "mois": mois,
                        "version_formule": VERSION_FORMULE_1_7B,
                        "valeur": ecart_pct,
                        "niveau_confiance_derive": NIVEAU_CONFIANCE_DERIVE_1_7B,
                    }
                )
        _bulk_insert_grandeurs_metier(session, lignes)
        nb_ecart += len(lignes)

    # === rang_referentiel_temporel (360 lignes attendues) ====================
    for ctx in contextes_villes:
        loc_id = ctx["localite_id"]
        climato = _lire_mensuel(session, ctx["code_serie_power_1991_2020"])

        # Distribution stratifiée par mois calendrier
        distribution_par_mois: dict[int, list[float]] = {m: [] for m in range(1, 13)}
        for (annee_clim, mois_clim), valeur in climato.items():
            if ANNEE_CLIMATO_DEBUT <= annee_clim <= ANNEE_CLIMATO_FIN:
                distribution_par_mois[mois_clim].append(valeur)

        serie_id = serie_id_par_grandeur_localite[(GRANDEUR_RANG_TEMPOREL, loc_id)]

        lignes = []
        for annee in range(ANNEE_KUMA_DEBUT, ANNEE_KUMA_FIN + 1):
            for mois in range(1, 13):
                kuma_v = kuma_par_localite[loc_id].get((annee, mois))
                distribution = distribution_par_mois.get(mois, [])
                if kuma_v is None or len(distribution) < 2:
                    continue
                percentile = _calcul_rang_temporel(kuma_v, distribution)
                lignes.append(
                    {
                        "grandeur_code": GRANDEUR_RANG_TEMPOREL,
                        "localite_id": loc_id,
                        "series_metadonnees_id": serie_id,
                        "periode_type": "mensuel",
                        "annee_debut": annee,
                        "annee_fin": annee,
                        "mois": mois,
                        "version_formule": VERSION_FORMULE_1_7B,
                        "valeur": percentile,
                        "niveau_confiance_derive": NIVEAU_CONFIANCE_DERIVE_1_7B,
                    }
                )
        _bulk_insert_grandeurs_metier(session, lignes)
        nb_rang_temporel += len(lignes)

    # === rang_referentiel_spatial (360 lignes attendues) =====================
    lignes_spatial: list[dict[str, object]] = []
    for annee in range(ANNEE_KUMA_DEBUT, ANNEE_KUMA_FIN + 1):
        for mois in range(1, 13):
            valeurs_par_loc: dict[int, float] = {}
            for loc_id, kuma_mens in kuma_par_localite.items():
                valeur_loc = kuma_mens.get((annee, mois))
                if valeur_loc is not None:
                    valeurs_par_loc[loc_id] = valeur_loc
            if len(valeurs_par_loc) != N_VILLES_KUMA:
                continue
            rangs = _calcul_rang_spatial(valeurs_par_loc)
            for loc_id, rang in rangs.items():
                serie_id = serie_id_par_grandeur_localite[(GRANDEUR_RANG_SPATIAL, loc_id)]
                lignes_spatial.append(
                    {
                        "grandeur_code": GRANDEUR_RANG_SPATIAL,
                        "localite_id": loc_id,
                        "series_metadonnees_id": serie_id,
                        "periode_type": "mensuel",
                        "annee_debut": annee,
                        "annee_fin": annee,
                        "mois": mois,
                        "version_formule": VERSION_FORMULE_1_7B,
                        "valeur": float(rang),
                        "niveau_confiance_derive": NIVEAU_CONFIANCE_DERIVE_1_7B,
                    }
                )

    _bulk_insert_grandeurs_metier(session, lignes_spatial)
    nb_rang_spatial += len(lignes_spatial)

    session.flush()

    return {
        "nb_ecart_insere": nb_ecart,
        "nb_rang_temporel_insere": nb_rang_temporel,
        "nb_rang_spatial_insere": nb_rang_spatial,
        "nb_total": nb_ecart + nb_rang_temporel + nb_rang_spatial,
    }


# === Recalcul corrige ecart_relatif (migration 046+) ======================


def _calcul_ecart_relatif_avec_seuil(
    valeur_kuma: float,
    valeur_sarah3: float,
    seuil_sarah3_min: float,
) -> float | None:
    """Variante robuste de :func:`_calcul_ecart_relatif` avec garde-fou seuil.

    Identique à la formule canonique ``(kuma - sarah3) / sarah3 * 100``
    sauf que les valeurs SARAH-3 inférieures au seuil sont jugées
    pathologiques et l'écart n'est pas calculé (retour ``None`` plutôt
    qu'une amplification mathématiquement absurde par 1/s pour s -> 0).

    Args:
        valeur_kuma : moyenne mensuelle Kuma (kWh/m²/jour).
        valeur_sarah3 : moyenne mensuelle SARAH-3 (kWh/m²/jour, post-044).
        seuil_sarah3_min : seuil minimal SARAH-3 (kWh/m²/jour). En dessous,
            la fonction retourne ``None``.

    Returns:
        Écart relatif en pourcent signé, ou ``None`` si SARAH-3 < seuil.

    Notes:
        Cette fonction est volontairement séparée de :func:`_calcul_ecart_relatif`
        qui reste utilisée par :func:`calculer_et_inserer_referentiels` (migration
        042) pour ne pas changer le comportement historique. Elle sert le
        recalcul corrigé en migration 046.
    """
    if valeur_sarah3 < seuil_sarah3_min:
        return None
    return (valeur_kuma - valeur_sarah3) / valeur_sarah3 * 100.0


def _decouvrir_contextes_villes_depuis_db(session: Session) -> list[ContexteVille]:
    """Reconstruit les contextes des 6 villes pilotes à partir de la base.

    Évite la duplication du dictionnaire de localités de la migration
    042. Les codes des séries Kuma daily, SARAH-3 et power 1991-2020 suivent
    une convention stable (helpers ``_code_serie_*`` de la migration
    042) qu'on reconstruit ici en interrogeant ``series_metadonnees`` par
    grandeur + source.

    Args:
        session : session SQLAlchemy active.

    Returns:
        Liste de ContexteVille pour les 6 villes Kuma pilotes.

    Raises:
        RuntimeError : si l'on ne trouve pas les 6 contextes attendus.
    """
    rows = session.execute(
        text(
            """
            SELECT
                sm.localite_id,
                MAX(CASE WHEN s.code = 'nasa_power'
                         AND sm.grandeur_code = 'ghi'
                         AND sm.periode_debut = '2021-01-01'
                         AND sm.periode_fin = '2025-12-31'
                    THEN sm.code END) AS code_kuma_daily,
                MAX(CASE WHEN s.code = 'sarah3_monthly'
                         AND sm.grandeur_code = 'ghi'
                    THEN sm.code END) AS code_sarah3,
                MAX(CASE WHEN s.code = 'nasa_power'
                         AND sm.grandeur_code = 'ghi'
                         AND sm.periode_debut = '1991-01-01'
                         AND sm.periode_fin = '2020-12-31'
                    THEN sm.code END) AS code_power_climato
            FROM series_metadonnees sm
            JOIN sources s ON s.id = sm.source_id
            WHERE sm.grandeur_code = 'ghi'
              AND s.code IN ('nasa_power', 'sarah3_monthly')
            GROUP BY sm.localite_id
            HAVING MAX(CASE WHEN s.code = 'sarah3_monthly' THEN 1 ELSE 0 END) = 1
            ORDER BY sm.localite_id
            """
        )
    ).all()
    contextes: list[ContexteVille] = []
    for r in rows:
        if r.code_kuma_daily is None or r.code_sarah3 is None:
            continue
        contextes.append(
            {
                "localite_id": int(r.localite_id),
                "code_serie_kuma_daily": r.code_kuma_daily,
                "code_serie_sarah3": r.code_sarah3,
                "code_serie_power_1991_2020": r.code_power_climato or "",
            }
        )
    if len(contextes) != N_VILLES_KUMA:
        raise RuntimeError(
            f"Recalcul ecart_relatif : {len(contextes)} contextes villes "
            f"trouvés (attendu {N_VILLES_KUMA}). Vérifier le seed des séries "
            f"NASA POWER + SARAH-3."
        )
    return contextes


def _resoudre_serie_id_ecart_par_localite(session: Session) -> dict[int, int]:
    """Résout ``{localite_id: series_metadonnees.id}`` pour les 6 séries
    ``ecart_relatif_referentiel`` calculées Kuma post-migration 042.
    """
    rows = session.execute(
        text(
            """
            SELECT sm.localite_id, sm.id AS serie_id
            FROM series_metadonnees sm
            JOIN sources s ON s.id = sm.source_id
            WHERE sm.grandeur_code = :grandeur
              AND s.code = 'kuma_calculs'
            """
        ),
        {"grandeur": GRANDEUR_ECART},
    ).all()
    return {int(r.localite_id): int(r.serie_id) for r in rows}


def recalculer_ecart_relatif_referentiel(
    *,
    session: Session,
    seuil_sarah3_min: float = SEUIL_SARAH3_MIN_DEFAUT,
) -> tuple[int, int]:
    """Recalcule ``ecart_relatif_referentiel`` depuis la donnée brute (migration 046).

    Reconstruit les 216 lignes attendues (6 villes x 36 mois 2021-2023) en
    relisant directement ``mesures_ressource`` (NASA POWER agrégé en
    moyenne mensuelle) et ``mesures_ressource_mensuelles`` (SARAH-3 daily
    post-044), avec un garde-fou ``seuil_sarah3_min``.

    Quand SARAH-3 < seuil pour un (ville, mois), la ligne est insérée
    avec ``valeur = NULL`` plutôt que d'amplifier mathématiquement la
    division par une valeur quasi-nulle (cf. bug migration 045 amplifiant
    +2929 % sur une ligne pathologique de CI).

    Note schéma : ``grandeurs_metier.valeur`` doit être nullable pour
    accepter les NULL. La migration 046 relâche le ``NOT NULL`` au
    préalable.

    Args:
        session : session SQLAlchemy active. L'appelant commit.
        seuil_sarah3_min : seuil minimal SARAH-3 (kWh/m²/jour).

    Returns:
        ``(nb_lignes_inserees, nb_lignes_null)`` - somme = 216 sur le
        dataset sain.
    """
    contextes = _decouvrir_contextes_villes_depuis_db(session)
    serie_id_par_loc = _resoudre_serie_id_ecart_par_localite(session)

    nb_total = 0
    nb_null = 0

    for ctx in contextes:
        loc_id = ctx["localite_id"]
        kuma_mens = _lire_kuma_mensuel(session, ctx["code_serie_kuma_daily"])
        sarah3_mens = _lire_mensuel(session, ctx["code_serie_sarah3"])
        serie_id = serie_id_par_loc.get(loc_id)
        if serie_id is None:
            # Pas de série ecart_relatif_referentiel pour cette localité,
            # impossible normalement après migration 042. Garde défensive.
            continue

        lignes: list[dict[str, object]] = []
        for annee in range(ANNEE_KUMA_DEBUT, ANNEE_SARAH3_FIN + 1):
            for mois in range(1, 13):
                kuma_v = kuma_mens.get((annee, mois))
                sarah3_v = sarah3_mens.get((annee, mois))
                if kuma_v is None or sarah3_v is None:
                    continue
                ecart_pct = _calcul_ecart_relatif_avec_seuil(kuma_v, sarah3_v, seuil_sarah3_min)
                if ecart_pct is None:
                    nb_null += 1
                lignes.append(
                    {
                        "grandeur_code": GRANDEUR_ECART,
                        "localite_id": loc_id,
                        "series_metadonnees_id": serie_id,
                        "periode_type": "mensuel",
                        "annee_debut": annee,
                        "annee_fin": annee,
                        "mois": mois,
                        "version_formule": VERSION_FORMULE_1_7B,
                        "valeur": ecart_pct,
                        "niveau_confiance_derive": NIVEAU_CONFIANCE_DERIVE_1_7B,
                    }
                )
        _bulk_insert_grandeurs_metier(session, lignes)
        nb_total += len(lignes)

    session.flush()
    return nb_total, nb_null


# === Atlas : écart inter-source étendu aux 33 (densification) =============


class ContexteEcartInterSource(TypedDict):
    """Contexte par localité pour l'écart inter-source de l'atlas.

    NASA daily (agrégé mensuel à la volée) vs une référence mensuelle (SARAH-3
    pour le GHI, CAMS pour le DNI), sur la fenêtre commune.
    """

    localite_id: int
    code_serie_nasa_daily: str
    code_serie_reference: str
    series_metadonnees_id: int


def calculer_et_inserer_ecart_inter_source(
    *,
    session: Session,
    contextes: Sequence[ContexteEcartInterSource],
    grandeur_code: str,
    annee_debut: int,
    annee_fin: int,
    seuil_reference_min: float = SEUIL_SARAH3_MIN_DEFAUT,
    niveau_confiance: str = NIVEAU_CONFIANCE_DERIVE_1_7B,
) -> tuple[int, int]:
    """Écart inter-source NASA-daily-agrégé vs référence mensuelle, matérialisé.

    Sert l'atlas : étend l'écart aux 33 sur la fenêtre commune.
    GHI = NASA vs SARAH-3 (``ecart_relatif_referentiel``) ; DNI = NASA vs CAMS
    (``ecart_relatif_dni_cams``). **Réutilise les helpers purs** (zéro physique
    nouvelle) : agrégation daily->mensuel (``_lire_kuma_mensuel``), lecture mensuelle
    de la référence (``_lire_mensuel``), formule signée avec garde-fou seuil
    (``_calcul_ecart_relatif_avec_seuil``). La valeur stockée est **signée**
    ``(nasa - ref) / ref * 100`` ; le ``|ecart|`` est le signal primaire côté
    consommation, pas une correction de biais.

    Args:
        session : session SQLAlchemy active (l'appelant commit).
        contextes : par localité, séries NASA daily + référence + série calculée cible.
        grandeur_code : ``ecart_relatif_referentiel`` (GHI) ou ``ecart_relatif_dni_cams``.
        annee_debut, annee_fin : fenêtre commune (atlas : 2021-2023).
        seuil_reference_min : garde-fou (référence < seuil -> valeur NULL, pas une
            amplification absurde).
        niveau_confiance : 'B' (inter-source, pas terrain).

    Returns:
        ``(nb_lignes_inserees, nb_lignes_null)``.
    """
    nb_total = 0
    nb_null = 0
    for ctx in contextes:
        nasa = _lire_kuma_mensuel(session, ctx["code_serie_nasa_daily"])
        reference = _lire_mensuel(session, ctx["code_serie_reference"])

        lignes: list[dict[str, object]] = []
        for annee in range(annee_debut, annee_fin + 1):
            for mois in range(1, 13):
                valeur_nasa = nasa.get((annee, mois))
                valeur_ref = reference.get((annee, mois))
                if valeur_nasa is None or valeur_ref is None:
                    continue
                ecart = _calcul_ecart_relatif_avec_seuil(
                    valeur_nasa, valeur_ref, seuil_reference_min
                )
                if ecart is None:
                    nb_null += 1
                lignes.append(
                    {
                        "grandeur_code": grandeur_code,
                        "localite_id": ctx["localite_id"],
                        "series_metadonnees_id": ctx["series_metadonnees_id"],
                        "periode_type": "mensuel",
                        "annee_debut": annee,
                        "annee_fin": annee,
                        "mois": mois,
                        "version_formule": VERSION_FORMULE_1_7B,
                        "valeur": ecart,
                        "niveau_confiance_derive": niveau_confiance,
                    }
                )
        _bulk_insert_grandeurs_metier(session, lignes)
        nb_total += len(lignes)

    session.flush()
    return nb_total, nb_null


# === Rang temporel focalisé (densification) ================================


class ContexteRangTemporel(TypedDict):
    """Contexte par localité pour le rang temporel focalisé.

    Percentile de la valeur Kuma (NASA daily agrégé mensuel à la volée) dans la
    climatologie NASA POWER 1991-2020 stratifiée par mois calendrier.
    """

    localite_id: int
    code_serie_kuma_daily: str
    code_serie_power_1991_2020: str
    series_metadonnees_id: int


def calculer_et_inserer_rang_temporel(
    *,
    session: Session,
    contextes: Sequence[ContexteRangTemporel],
    grandeur_code: str = GRANDEUR_RANG_TEMPOREL,
    annee_debut: int = ANNEE_KUMA_DEBUT,
    annee_fin: int = ANNEE_KUMA_FIN,
    niveau_confiance: str = NIVEAU_CONFIANCE_DERIVE_1_7B,
) -> int:
    """Rang temporel seul, matérialisé (étape rang temporel extraite pour la densification).

    Fonction **focalisée** : ne calcule QUE le ``rang_referentiel_temporel``, jamais
    l'écart ni le rang spatial. Permet d'étendre le rang temporel aux 28 communes sans
    passer par :func:`calculer_et_inserer_referentiels`, qui recalculerait le rang spatial
    sur un pool élargi et corromprait le pool-6 figé des consommateurs média. Réutilise les
    mêmes helpers purs (``_lire_kuma_mensuel``, ``_lire_mensuel``, ``_calcul_rang_temporel``)
    que l'orchestrateur combine : formule numériquement identique.

    Args:
        session : session SQLAlchemy active (l'appelant commit).
        contextes : par localité, NASA daily + climato mensuelle 1991-2020 + série cible.
        grandeur_code : ``rang_referentiel_temporel``.
        annee_debut, annee_fin : fenêtre Kuma (2021-2025).
        niveau_confiance : 'B' (cohérence intra-source).

    Returns:
        Nombre de lignes insérées.
    """
    nb_total = 0
    for ctx in contextes:
        climato = _lire_mensuel(session, ctx["code_serie_power_1991_2020"])
        distribution_par_mois: dict[int, list[float]] = {m: [] for m in range(1, 13)}
        for (annee_clim, mois_clim), valeur in climato.items():
            if ANNEE_CLIMATO_DEBUT <= annee_clim <= ANNEE_CLIMATO_FIN:
                distribution_par_mois[mois_clim].append(valeur)
        kuma = _lire_kuma_mensuel(session, ctx["code_serie_kuma_daily"])

        lignes: list[dict[str, object]] = []
        for annee in range(annee_debut, annee_fin + 1):
            for mois in range(1, 13):
                kuma_v = kuma.get((annee, mois))
                distribution = distribution_par_mois.get(mois, [])
                if kuma_v is None or len(distribution) < 2:
                    continue
                percentile = _calcul_rang_temporel(kuma_v, distribution)
                lignes.append(
                    {
                        "grandeur_code": grandeur_code,
                        "localite_id": ctx["localite_id"],
                        "series_metadonnees_id": ctx["series_metadonnees_id"],
                        "periode_type": "mensuel",
                        "annee_debut": annee,
                        "annee_fin": annee,
                        "mois": mois,
                        "version_formule": VERSION_FORMULE_1_7B,
                        "valeur": percentile,
                        "niveau_confiance_derive": niveau_confiance,
                    }
                )
        _bulk_insert_grandeurs_metier(session, lignes)
        nb_total += len(lignes)

    session.flush()
    return nb_total
