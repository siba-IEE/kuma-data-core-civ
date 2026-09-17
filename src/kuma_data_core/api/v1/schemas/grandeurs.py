"""Schémas Pydantic des endpoints `/api/v1/grandeurs/<code>`.

Cinq grandeurs F2 paramétrables :

- :class:`ParametresPOA` : POA paramétrable (Perez + Liu-Jordan fallback).
- :class:`ParametresProductibleCorrectionThermique` : NOCT simple.
- :class:`ParametresProductiblePRFourni` : PR brut + PR_T (correction
  paramétrée).
- :class:`ParametresEnergieUtileECS` : Hottel-Whillier-Bliss bord-capteur.
- :class:`ParametresDegreJourClimatisation` : moyenne journalière agrégée
  mensuel.

Schémas résultats discriminés (cohérente avec ``MesureLue``) :

- :class:`ResultatJournalier` : ``granularite = 'journalier'``, ``instant: date``.
- :class:`ResultatMensuel` : ``granularite = 'mensuel'``, ``instant: str``
  format ``YYYY-MM``.
- :data:`ResultatGrandeurF2` : union discriminée.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

# === Paramètres communs ===================================================


class ParametresCommunsF2(BaseModel):
    """Paramètres communs à tous les endpoints F2 paramétrables.

    Le champ ``format_sortie`` est exposé en query string sous le nom
    URL ``format`` via ``Query(alias="format")`` côté handler - alias
    nécessaire pour éviter le shadow du built-in Python ``format``
    (cf. ``api/v1/series.py``).
    """

    code_serie_source: str = Field(
        ...,
        min_length=1,
        max_length=80,
        description="Code de la serie F1 source dans series_metadonnees.",
    )
    periode_debut: date = Field(..., description="Date de debut (inclusive).")
    periode_fin: date = Field(..., description="Date de fin (inclusive).")
    format_sortie: Literal["json", "csv"] = Field(
        "json",
        alias="format",
        description="Format de reponse : 'json' (defaut) ou 'csv'.",
    )

    @model_validator(mode="after")
    def _valider_plage_temporelle(self) -> ParametresCommunsF2:
        if self.periode_fin < self.periode_debut:
            raise ValueError("periode_fin doit etre superieure ou egale a periode_debut")
        return self


# === Paramètres par grandeur ==============================================


class ParametresPOA(ParametresCommunsF2):
    """Paramètres POA paramétrable (modèle Perez 1990 + Liu-Jordan fallback)."""

    inclinaison_deg: float = Field(
        ...,
        ge=0,
        le=90,
        description="Inclinaison beta du plan (degres, 0=horizontal, 90=vertical).",
    )
    orientation_deg: float = Field(
        ...,
        ge=0,
        lt=360,
        description=(
            "Orientation gamma du plan (azimut en degres, 0=nord, 90=est, 180=sud, 270=ouest)."
        ),
    )
    albedo_sol: float = Field(
        0.2,
        ge=0,
        le=1,
        description="Albedo du sol (defaut 0.2, typique sol vegetalise).",
    )
    methode: Literal["moyenne_journaliere", "integration_horaire"] = Field(
        "moyenne_journaliere",
        description=(
            "Methode de calcul. 'moyenne_journaliere' (defaut, retro-compatible) : "
            "Perez au midi solaire sur les totaux journaliers, serie source journaliere. "
            "'integration_horaire' : Perez par heure integre sur la journee, serie source "
            "horaire (GHI + compagnes DNI/DHI horaires) ; leve le biais de moyennage L-TR-6 "
            "(surestimation +16 % pour un plan incline, etude §9.2)."
        ),
    )


class ParametresBifacial(ParametresCommunsF2):
    """Paramètres POA bifacial (modèle infinite-sheds row-aware, pvlib).

    Distinct du ``ParametresPOA`` mono-plan : ajoute la géométrie de rangées
    (gcr, hauteur, pitch) et la bifacialité du module. L'albédo est résolu depuis
    la série ``albedo_surface`` (réel par localité) ; ``albedo_sol`` n'est qu'un
    **repli** si cette série est absente.
    """

    inclinaison_deg: float = Field(
        ..., ge=0, le=90, description="Inclinaison beta du plan (degres, 0=horizontal)."
    )
    orientation_deg: float = Field(
        ...,
        ge=0,
        lt=360,
        description="Orientation gamma (azimut degres, 0=nord, 90=est, 180=sud, 270=ouest).",
    )
    gcr: float = Field(
        ..., gt=0, le=1, description="Ground coverage ratio (largeur capteur / pitch), dans ]0, 1]."
    )
    hauteur_m: float = Field(
        ...,
        gt=0,
        description="Hauteur du centre de rangee au-dessus du sol (m, meme unite que pitch).",
    )
    pitch_m: float = Field(
        ..., gt=0, description="Espacement rangee a rangee (m, meme unite que hauteur)."
    )
    bifacialite: float = Field(
        0.8,
        ge=0,
        le=1,
        description="Bifacialite du module (rendement face arriere / avant, defaut 0.8).",
    )
    albedo_sol: float = Field(
        0.2,
        ge=0,
        le=1,
        description="Albedo de repli si la serie albedo_surface est absente (defaut 0.2).",
    )
    methode: Literal["moyenne_journaliere", "integration_horaire"] = Field(
        "moyenne_journaliere",
        description=(
            "Methode de calcul. 'moyenne_journaliere' (defaut) : infinite-sheds au midi "
            "solaire sur les totaux journaliers (serie source journaliere). "
            "'integration_horaire' : infinite-sheds par heure integre sur la journee (serie "
            "source horaire + compagnes DNI/DHI horaires ; albedo journalier broadcast aux "
            "heures) ; leve le biais de moyennage L-TR-6."
        ),
    )


class ParametresProductibleCorrectionThermique(ParametresCommunsF2):
    """Paramètres productible avec correction thermique NOCT simple (Ross 1980).

    Modèle thermique unique en API : Ross 1980 (NOCT simple). Le modèle
    Faiman 2008 (dépendant du vent) a été codé et testé puis retiré de
    l'API : Faiman relève du régime terrain, calibration locale u0/u1
    requise pour éviter une fausse confiance B.
    """

    noct_degc: float = Field(
        ...,
        ge=40,
        le=50,
        description="NOCT (°C), fiche produit module (typique 45).",
    )
    coeff_temp_pourcent_par_degc: float = Field(
        ...,
        ge=-0.6,
        le=-0.1,
        description="Coefficient temperature gamma_Pmax (%/°C), valeur negative.",
    )
    puissance_stc_wc: float = Field(
        ...,
        gt=0,
        description="Puissance nominale STC du systeme (Wc).",
    )
    methode: Literal["moyenne_journaliere", "integration_horaire"] = Field(
        "moyenne_journaliere",
        description=(
            "Methode de calcul. 'moyenne_journaliere' (defaut, retro-compatible) : "
            "T_cell calcule sur l'irradiance moyennee 24 h (serie source journaliere). "
            "'integration_horaire' : T_cell et correction appliques par heure sur le GHI "
            "horaire (serie source horaire + T2M horaire), integres sur la journee ; "
            "leve le biais de moyennage L-TR-6 (la moyenne 24 h sous-estime le pic de "
            "midi -> surestime le productible)."
        ),
    )


class ParametresProductiblePRFourni(ParametresCommunsF2):
    """Paramètres productible avec PR fourni (Marion 2005 + Dierauf 2013).

    Si ``correction == 'temperature'``, les paramètres ``noct_degc`` et
    ``coeff_temp_pourcent_par_degc`` sont obligatoires (validation
    conditionnelle ``_valider_parametres_temperature``).
    """

    pr_fourni: float = Field(
        ...,
        ge=0,
        le=1,
        description="Performance Ratio fourni par l'appelant (sans unite).",
    )
    correction: Literal["aucune", "temperature"] = Field(
        "aucune",
        description="Type de correction : 'aucune' (PR brut) ou 'temperature' (PR_T).",
    )
    puissance_stc_wc: float = Field(
        ...,
        gt=0,
        description="Puissance nominale STC du systeme (Wc).",
    )
    noct_degc: float | None = Field(
        None,
        ge=40,
        le=50,
        description="NOCT (°C) - obligatoire si correction='temperature'.",
    )
    coeff_temp_pourcent_par_degc: float | None = Field(
        None,
        ge=-0.6,
        le=-0.1,
        description=(
            "Coefficient temperature gamma_Pmax (%/°C) - obligatoire si correction='temperature'."
        ),
    )
    methode: Literal["moyenne_journaliere", "integration_horaire"] = Field(
        "moyenne_journaliere",
        description=(
            "Methode de calcul. 'moyenne_journaliere' (defaut, retro-compatible) : "
            "PR applique sur l'irradiance journaliere, serie source journaliere. "
            "'integration_horaire' : PR applique par heure (serie source horaire ; + T2M "
            "horaire si correction='temperature'), integre sur la journee. Pour "
            "correction='aucune' (PR brut, lineaire), l'horaire est identique au journalier "
            "(expose pour coherence d'interface) ; le gain L-TR-6 ne porte que sur "
            "correction='temperature' (T_cell non-lineaire, biais de Jensen)."
        ),
    )

    @model_validator(mode="after")
    def _valider_parametres_temperature(self) -> ParametresProductiblePRFourni:
        if self.correction == "temperature":
            manquants: list[str] = []
            if self.noct_degc is None:
                manquants.append("noct_degc")
            if self.coeff_temp_pourcent_par_degc is None:
                manquants.append("coeff_temp_pourcent_par_degc")
            if manquants:
                raise ValueError(f"correction='temperature' requiert : {', '.join(manquants)}")
        return self


class ParametresEnergieUtileECS(ParametresCommunsF2):
    """Paramètres énergie utile ECS bord-capteur (Hottel-Whillier-Bliss 1958)."""

    rendement_optique_eta0: float = Field(
        ...,
        ge=0.5,
        le=0.9,
        description=("Rendement optique eta0 (sans unite), fiche capteur Solar Keymark."),
    )
    pertes_lineaires_a1: float = Field(
        ...,
        ge=1,
        le=8,
        description="Coefficient pertes lineaires a1 (W/(m²·K)).",
    )
    pertes_quadratiques_a2: float = Field(
        ...,
        ge=0,
        le=0.05,
        description="Coefficient pertes quadratiques a2 (W/(m²·K²)).",
    )
    temperature_fluide_entree_degc: float = Field(
        ...,
        ge=10,
        le=90,
        description="Temperature fluide caloporteur a l'entree T_in (°C).",
    )
    methode: Literal["moyenne_journaliere", "integration_horaire"] = Field(
        "moyenne_journaliere",
        description=(
            "Methode de calcul. 'moyenne_journaliere' (defaut, retro-compatible) : "
            "rendement HWB calcule sur l'irradiance moyennee 24 h (serie source journaliere). "
            "'integration_horaire' : rendement applique par heure sur le GHI horaire reel "
            "(serie source horaire + T2M horaire), integre sur la journee ; leve le biais de "
            "moyennage L-TR-6 (rendement HWB non-lineaire en G, biais de Jensen)."
        ),
    )


class ParametresDegreJourClimatisation(ParametresCommunsF2):
    """Paramètres degrés-jours de climatisation (Erbs 1983 + Schoenau & Kehrig 1990)."""

    base_temperature_degc: float = Field(
        ...,
        ge=10,
        le=35,
        description="Base de reference T_b (°C, plage couvrant 18.3 ASHRAE a 26 CEDEAO).",
    )
    methode: Literal["moyenne_journaliere", "integration_horaire"] = Field(
        "moyenne_journaliere",
        description=(
            "Methode de calcul. 'moyenne_journaliere' (defaut, retro-compatible) : "
            "ecart de la moyenne quotidienne a T_b, serie source journaliere. "
            "'integration_horaire' (Erbs 1983) : integration des ecarts horaires "
            "positifs a T_b, leve le biais de moyennage tropical (-5 a -15 %, dette "
            "D-42) ; exige une serie source horaire (granularite='horaire')."
        ),
    )


# === Réponse de la grandeur F1 calculee_volee ghi_exceedance ==============


class ReponseGhiExceedance(BaseModel):
    """Réponse de l'endpoint ``/v1/grandeurs/ghi_exceedance/{code_localite}``.

    Exceedance inter-annuelle de l'irradiation annuelle pour une ville
    pilote, dérivée de la série GHI mensuelle 1991-2020 NASA POWER.
    Calculée à la volée à chaque appel, jamais stockée.
    """

    code_grandeur: Literal["ghi_exceedance"] = "ghi_exceedance"
    code_localite: str = Field(
        ...,
        description="Code de la localite cible (ex. gin_kankan, gin_conakry_kaloum).",
    )
    code_serie_source: str = Field(
        ...,
        description=(
            "Code D-32 de la serie GHI mensuelle source 1991-2020 utilisee "
            "pour le calcul (ex. gin_kankan_ghi_power_1991_2020)."
        ),
    )
    periode: str = Field(
        ...,
        pattern=r"^\d{4}-\d{4}$",
        description="Fenetre climatologique source au format YYYY-YYYY (ex. 1991-2020).",
    )
    base_annees: int = Field(
        ...,
        ge=2,
        description="Nombre d'annees utilisees pour le calcul des percentiles.",
    )
    p50: float = Field(
        ...,
        gt=0,
        description="Mediane de l'irradiation annuelle (kWh/m²/an). Annee typique.",
    )
    p90: float = Field(
        ...,
        gt=0,
        description=(
            "Exceedance P90 = irradiation annuelle depassee 90 % des annees "
            "(percentile 10 cote distribution). Scenario conservateur. "
            "Strictement < p50 par construction."
        ),
    )
    unite: str = Field(
        "kWh/m²/an",
        description="Unite des valeurs p50 et p90.",
    )
    methode_percentile: str = Field(
        ...,
        description="Methode d'interpolation des percentiles (ex. 'linear' numpy).",
    )
    niveau_confiance: Literal["A", "B", "C"] = Field(
        ...,
        description="Niveau de confiance du calcul. 'B' (modele satellitaire) en phase 1.",
    )
    limite: str = Field(
        ...,
        description=(
            "Avertissement editorial sur la portee du resultat : exceedance "
            "inter-annuelle uniquement, pas un P90 bancable complet. Pour les "
            "villes co-localisees (dette D-29 Kindia/Mamou), mention "
            "explicite de l'identite des P50/P90 avec la ville jumelle."
        ),
    )


# === Résultats discriminés (granularité journalier vs mensuel) ============


class ResultatJournalier(BaseModel):
    """Élément de réponse F2 à granularité journalière."""

    granularite: Literal["journalier"] = "journalier"
    instant: date
    valeur: float
    unite: str
    niveau_confiance: Literal["A", "B", "C"]


class ResultatMensuel(BaseModel):
    """Élément de réponse F2 à granularité mensuelle (instant format YYYY-MM)."""

    granularite: Literal["mensuel"] = "mensuel"
    instant: str = Field(
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description="Mois calendaire au format YYYY-MM.",
    )
    valeur: float
    unite: str
    niveau_confiance: Literal["A", "B", "C"]


ResultatGrandeurF2 = Annotated[
    ResultatJournalier | ResultatMensuel,
    Field(discriminator="granularite"),
]
"""Union discriminée des 2 catégories de résultats F2.

Le champ discriminant ``granularite`` (Literal) permet la
désérialisation type-safe côté client : la catégorie est inscrite
explicitement dans chaque résultat retourné.
"""


# === Soiling (F1 calculee_volee) ====================================


class MesureSoilingJour(BaseModel):
    """Perte de salissure d'un jour (proxy HSU, % de transmission perdue)."""

    instant: date
    perte_pct: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Perte de transmission = (1 - ratio HSU) x 100, bornee [0, 100].",
    )
    niveau_confiance: Literal["A", "B", "C"] = "B"


class ReponseTauxSalissureProxy(BaseModel):
    """Réponse de ``/v1/grandeurs/taux_salissure_proxy/{code_serie_source}``.

    Proxy de salissure (modèle HSU, Coello & Boyle 2019) sur la fenêtre d'overlap
    PM EAC4 ∩ pluie NASA POWER. Calculée à la volée, jamais stockée.
    """

    code_grandeur: Literal["taux_salissure_proxy"] = "taux_salissure_proxy"
    code_serie_source: str = Field(..., description="Code D-32 de la serie PM2.5 source (EAC4).")
    code_localite: str = Field(..., description="Code de la localite (derive de la serie source).")
    periode: str = Field(
        ...,
        description="Fenetre effective (intersection PM ∩ pluie), YYYY-MM-DD/YYYY-MM-DD.",
    )
    unite: str = Field(default="%", description="Unite des pertes (pourcent).")
    surface_tilt_deg: float = Field(..., description="Inclinaison fixe utilisee (defaut F1, deg).")
    cleaning_threshold_mm: float = Field(
        ..., description="Seuil de pluie nettoyante utilise (defaut F1, mm)."
    )
    mesures: list[MesureSoilingJour] = Field(..., description="Perte de salissure par jour.")
    limite: str = Field(
        ...,
        description=(
            "Avertissement editorial : proxy modele (pas une mesure, terrain D-67) ; "
            "spin-up (premiers jours sous-estimes, L-SOIL-3) ; grille EAC4 grossiere "
            "(L-SOIL-4)."
        ),
    )


# === PR réaliste saisonnier (F1 calculee_volee) ===================


ModeCorrectionPR = Literal["aucune", "temperature", "salissure", "temperature_salissure"]
"""Modes de correction du PR réaliste (superposition thermique et/ou salissure)."""


class ParametresPRRealiste(BaseModel):
    """Paramètres (query) de l'endpoint ``pr_realiste``. La série GHI source est en path.

    Doctrine PR-référence : ``pr_fourni`` est supposé **hors salissure ET hors
    température** ; les corrections se superposent en facteurs multiplicatifs séparables.
    """

    pr_fourni: float = Field(
        ...,
        ge=0,
        le=1,
        description="PR de reference (ratio sans unite), hors salissure et hors temperature.",
    )
    correction: ModeCorrectionPR = Field(
        "temperature_salissure",
        description="Mode de correction superpose (defaut : thermique + salissure).",
    )
    noct_degc: float | None = Field(
        None,
        ge=40,
        le=50,
        description="NOCT (°C) - obligatoire si la correction inclut la temperature.",
    )
    coeff_temp_pourcent_par_degc: float | None = Field(
        None,
        ge=-0.6,
        le=-0.1,
        description=(
            "Coefficient temperature gamma_Pmax (%/°C, negatif) - obligatoire si la "
            "correction inclut la temperature (validation cote endpoint : 422 si absent)."
        ),
    )


class MesureJourPR(BaseModel):
    """PR réaliste d'un jour (ratio sans dimension)."""

    instant: date
    pr_realiste: float
    niveau_confiance: Literal["A", "B", "C"] = "B"


class MesureMoisPR(BaseModel):
    """PR réaliste moyen d'un mois (la courbe mensuelle = la 'PR saisonnière')."""

    instant: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="Mois (YYYY-MM).")
    pr_realiste: float
    niveau_confiance: Literal["A", "B", "C"] = "B"


class ReponsePRRealiste(BaseModel):
    """Réponse de ``/v1/grandeurs/pr_realiste/{code_serie_source}`` (calculée à la volée)."""

    code_grandeur: Literal["pr_realiste"] = "pr_realiste"
    code_serie_source: str = Field(..., description="Code D-32 de la serie GHI source.")
    code_localite: str = Field(..., description="Code de la localite (derive de la serie GHI).")
    periode: str = Field(
        ..., description="Fenetre effective (intersection selon le mode), YYYY-MM-DD/YYYY-MM-DD."
    )
    unite: str = Field(default="ratio", description="PR adimensionnel (ratio [0, 1]).")
    correction: ModeCorrectionPR = Field(..., description="Mode de correction applique.")
    pr_fourni: float = Field(..., description="PR de reference fourni (echo).")
    mesures_journalier: list[MesureJourPR] = Field(..., description="PR realiste par jour.")
    mesures_mensuel: list[MesureMoisPR] = Field(
        ..., description="PR realiste moyen par mois (courbe saisonniere, creux Harmattan)."
    )
    limite: str = Field(..., description="Caveats : doctrine PR-reference, L-PR/L-SOIL/L-TR-6.")


# === Réponse complète =====================================================


class ReponseGrandeurF2(BaseModel):
    """Réponse complète d'un endpoint F2 paramétrable."""

    code_grandeur: str = Field(
        ...,
        description="Code de la grandeur F2 calculee (cf. grandeurs_referentiel).",
    )
    code_serie_source: str = Field(
        ...,
        description="Code de la serie F1 source utilisee pour le calcul.",
    )
    parametres_appliques: dict[str, object] = Field(
        ...,
        description="Echo des parametres techniques utilisateur reçus.",
    )
    resultats: list[ResultatGrandeurF2] = Field(
        default_factory=list,
        description="Liste ordonnee des resultats F2 calcules sur la fenetre demandee.",
    )


# === Atlas Temps 2 : fiche d'incertitude inter-source (F1 lecture/assemblage) ===


class EcartPaireInterSource(BaseModel):
    """Écart inter-source pour une paire (grandeur), agrégé sur 2021-2023.

    Pairwise par grandeur (GHI : NASA vs SARAH-3 ; DNI : NASA vs CAMS), pas un consensus
    à trois. ``ecart_abs_pct`` (magnitude, médiane) = signal d'incertitude PRIMAIRE ; le
    signe est purement orientationnel, JAMAIS une correction de biais (anti-absolu).
    """

    grandeur: Literal["ghi", "dni"]
    paire: str = Field(
        ..., description="Couple de sources compare (ex. 'NASA POWER vs PVGIS-SARAH3')."
    )
    ecart_abs_pct: float = Field(
        ...,
        ge=0.0,
        description="Mediane des |ecarts mensuels| (%), 2021-2023. Signal d'incertitude PRIMAIRE.",
    )
    ecart_signe_pct: float = Field(
        ...,
        description=(
            "Moyenne signee des ecarts mensuels (%). Orientation SEULEMENT (ex. negatif = "
            "NASA < reference) ; jamais une correction de biais (l'atlas est inter-source / "
            "relatif, pas l'absolu vs sol, D-67)."
        ),
    )
    n_mois: int = Field(
        ..., ge=1, description="Nombre de mois compares (36 attendu sur 2021-2023)."
    )


class DegenerescenceFiche(BaseModel):
    """Dégénérescence de pixel, propriété du (localité, grille-source), rendue UNE fois.

    Niveau-localité (pas par grandeur) : GHI et DNI partagent la grille NASA CERES, donc
    une seule valeur représentative. ``note`` = caveat éditorial (groupe de jumeaux +
    nature exacte) transmis brut.
    """

    n_jumeaux: int = Field(
        ...,
        ge=0,
        description="Nombre d'autres points partageant la cellule NASA CERES (0 = point resolu).",
    )
    grille: str = Field(
        ...,
        description="Grille source de la degenerescence (ex. 'CERES SYN1deg 1 deg / 110 km').",
    )
    note: str = Field(..., description="Caveat editorial brut (groupe de jumeaux + nature, B-3).")


class ReponseIncertitudeInterSource(BaseModel):
    """Fiche d'incertitude INTER-SOURCE d'une localité (atlas Temps 2, lecture/assemblage).

    Assemble SANS les fusionner les deux axes d'honnêteté : écart inter-source (relatif,
    par paire/grandeur) et dégénérescence de pixel. Confiance B (inter-source, relatif) ;
    ne quantifie PAS l'incertitude absolue vs mesure sol (terrain).
    """

    code_grandeur: Literal["incertitude_inter_source"] = "incertitude_inter_source"
    code_localite: str = Field(..., description="Code de la localite (ex. gin_boffa).")
    fenetre: str = Field(..., description="Fenetre commune du triptyque (figee, ex. '2021-2023').")
    ecarts: list[EcartPaireInterSource] = Field(
        ..., description="Ecart inter-source par paire/grandeur (AXE 1, distinct)."
    )
    degenerescence: DegenerescenceFiche = Field(
        ...,
        description="Degenerescence de pixel niveau-localite (AXE 2, distinct), rendue une fois.",
    )
    niveau_confiance: Literal["A", "B", "C"] = Field(
        ...,
        description="Confiance derivee LUE des donnees (B attendu : inter-source, pas terrain).",
    )
    limite: str = Field(
        ...,
        description=(
            "Avertissement editorial : incertitude inter-source / relative, confiance B ; "
            "ne quantifie PAS l'incertitude absolue vs mesure sol (terrain, D-67)."
        ),
    )


class FichePointIncertitude(ReponseIncertitudeInterSource):
    """Fiche d'incertitude inter-source d'un point + ses coordonnées (pour la carte/collection).

    Strictement la fiche Temps 2 (héritée, contrat inchangé) augmentée de lat/lon, pour que
    le consommateur média (snapshot atlas) place chaque point sans second appel.
    """

    latitude_deg: float = Field(..., description="Latitude du point (degres).")
    longitude_deg: float = Field(..., description="Longitude du point (degres).")


class ReponseIncertitudeInterSourceCollection(BaseModel):
    """Collection paginée des fiches d'incertitude inter-source des points de l'atlas.

    Enveloppe identique à /v1/series (``items`` / ``total`` / ``limit`` / ``offset``), pour
    que la sync média (Zod) la valide avec le pattern existant. Lecture/assemblage pur.
    """

    items: list[FichePointIncertitude] = Field(
        ..., description="Fiches par point de l'atlas (chacune = fiche Temps 2 + coordonnees)."
    )
    total: int = Field(..., ge=0, description="Nombre total de points de l'atlas (34 attendu).")
    limit: int = Field(..., ge=1, description="Taille de page demandee.")
    offset: int = Field(..., ge=0, description="Decalage de pagination.")
