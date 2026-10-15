# Fiche méthodologique - HEP (Heures équivalentes pleines)

> Toute révision méthodologique (formule, politique de complétude,
> hypothèses) déclenche une incrémentation de `version_formule` et une
> entrée dans la section *Historique des versions*.
>
> Les §§ 3, 4.3, 6.2, 6.4 et 8 décrivent le périmètre de l'instance
> d'origine (Guinée). L'application à la Côte d'Ivoire est au § 9.

## 1. Identification

| Champ | Valeur |
|---|---|
| Nom | Heures équivalentes pleines |
| Code métier | `hep` |
| Unité | `h_eq` (heure équivalente pleine) |
| Famille | F1 - fait stocké |
| Stratégie de calcul | `stockee` (persistée dans `grandeurs_metier`) |
| Version courante | 1 |
| Périodicités exposées | annuel + mensuel |

## 2. Définition formelle

HEP est l'énergie produite par un système photovoltaïque par
kilowatt-crête nominal, exprimée en heures équivalentes pleines.
Cadre éditorial : Kuma stocke HEP comme **ressource solaire**, pas
comme productible PV réel.

### 2.1 Définition opérationnelle v1

Convention `1 kWh/m²/j ↔ 1 h_eq/j à 1 kW/m² STC` (irradiance nominale
standard test conditions = 1000 W/m²). Sous cette convention, la valeur
journalière de HEP est numériquement égale à l'irradiation globale
horizontale en kWh/m²/j :

```
HEP_jour(t) := GHI_jour(t)
```

L'agrégation temporelle est une somme cumulative directe :

```
HEP_mensuel(annee, mois) := sum_{t ∈ jours(annee, mois)} HEP_jour(t)
HEP_annuel(annee)        := sum_{t ∈ jours(annee)} HEP_jour(t)
                         = sum_{m=1..12} HEP_mensuel(annee, m)
```

### 2.2 Stockage

- 1 ligne `grandeurs_metier` `periode_type='annuel'` par (localité, année).
- 12 lignes `grandeurs_metier` `periode_type='mensuel'` par (localité, année).
- Identité métier étendue avec `version_formule` : la révision de la
  formule v1 → v2 ouvre de nouvelles lignes côte-à-côte des v1, qui
  restent en base pour audit.

## 3. Source amont des données d'entrée

| Paramètre | Valeur |
|---|---|
| Grandeur amont | `ghi` (irradiation globale horizontale journalière) |
| Source primaire | NASA POWER - Prediction Of Worldwide Energy Resources |
| Paramètre NASA | `ALLSKY_SFC_SW_DWN` |
| Méthode satellitaire amont | CERES SYN1deg + FLASHFlux |
| Résolution native solaire | 1° × 1° (110 km au sol à 10° N) |
| Granularité temporelle | journalière |
| Plage couverte | 2021-01-01 → 2025-12-31 (climat-quality) |
| Ingestion Kuma | migration 018 (Conakry-Kaloum) + migration 022 (5 autres villes) |
| URL méthodologie NASA POWER | `https://power.larc.nasa.gov/docs/methodology/` |

Acknowledgement NASA POWER : « These data were obtained from the NASA
Langley Research Center (LaRC) POWER Project funded through the NASA
Earth Science / Applied Science Program. » Convention propagée par le
`commentaire_editorial` de chaque série calculée.

## 4. Politique de complétude

**Règle stricte v1 - 100% jours civils.**

- **HEP annuel** pour `(localite, annee)` : insère **si et seulement si**
  la série GHI amont contient exactement `N_jours_civils(annee)` mesures
  journalières courantes non dépréciées (`N=365` non bissextile, `N=366`
  bissextile).
- **HEP mensuel** pour `(localite, annee, mois)` : insère **si et
  seulement si** la série GHI amont contient exactement
  `calendar.monthrange(annee, mois)[1]` mesures journalières courantes
  non dépréciées.

Si la condition n'est pas remplie, **aucune ligne n'est créée** pour
cette identité. Pas d'imputation, pas de valeur dégradée, pas de niveau
de confiance dégradé en C par défaut.

### 4.1 Justification

Cohérent avec la doctrine éditoriale : Kuma engage son autorité sur la
correction du calcul et ne publie pas ce qui n'est pas validé. Une
imputation silencieuse de jours manquants violerait ces deux principes.

### 4.2 Traçabilité de l'absence

L'absence d'une ligne `grandeurs_metier` pour une `(localite, annee, [mois])`
n'est pas matérialisée par une ligne placeholder dans la table. La trace
éditoriale vit dans le `commentaire_editorial` de la série
`series_metadonnees` correspondante et dans le journal applicatif de
la migration d'ingestion.

### 4.3 Constat

À l'exécution (migration 027) sur les 6 villes pilotes, **toutes les
30 (localité, année) et 360 (localité, année, mois) ont passé la
politique** sans skip. Décompte effectif = décompte théorique =
390 lignes.

## 5. Hypothèses physiques

### 5.1 Conversion STC

`1 kWh/m²/j ↔ 1 h_eq/j à 1 kW/m² STC`. L'irradiance nominale STC =
1000 W/m². Cette équivalence numérique est exacte sous l'hypothèse de
production strictement proportionnelle à l'irradiance, sans seuil bas
de fonctionnement ni saturation haute.

### 5.2 Plan horizontal

HEP intègre l'irradiation globale **horizontale** (GHI). Pour un système
photovoltaïque réel, la surface est typiquement inclinée à un angle
d'inclinaison optimal pour le site. La transposition GHI → POA
paramétrable est différée à la grandeur `poa_parametrable`.

### 5.3 Pas de correction thermique

HEP v1 ne corrige pas la perte de rendement due à la température de
fonctionnement du module. Cette correction est différée à la grandeur
`productible_correction_thermique`.

### 5.4 Pas de Performance Ratio

HEP v1 ne décote pas l'énergie disponible par le PR (Performance Ratio)
qui capture les pertes d'onduleur, de câblage, de mismatch modules,
d'ombrage, de soiling. PR utilisateur dépendant, différé à la grandeur
`productible_pr_fourni`.

## 6. Limites et portée

### 6.1 HEP = ressource solaire, pas productible PV réel

HEP est une **borne haute** théorique du productible PV. Un système
réel produira systématiquement moins (PR < 1, pertes thermiques,
orientation non-horizontale, etc.). L'éditeur Kuma porte explicitement
cette distinction.

### 6.2 Granularité spatiale CERES SYN1deg

La grille NASA POWER source pour le GHI a une résolution native de
1° × 1° (110 km au sol à 10° N). Conséquence pour le périmètre pilote :
les villes de **Kindia** (10.06° N, -12.86° E) et **Mamou**
(10.37° N, -12.10° E) tombent dans le même pixel et présentent donc
des valeurs GHI identiques sur 2021-2025, et par conséquent des HEP
identiques à la décimale près. Les quatre autres villes pilotes
(Conakry-Kaloum, Kankan, Labé, Nzérékoré) sont chacune dans un pixel
distinct.

Cette limite affecte symétriquement toute grandeur dérivée du GHI
(`kt`, `fraction_diffuse`, productibles). La résolution supérieure
d'ERA5-Land (9 km natif) ou l'interpolation entre stations ANM Guinée
permettraient de discriminer Kindia et Mamou.

### 6.3 Indépendance par rapport à la température

HEP intègre uniquement le GHI, **indépendamment de la température T2M**.
La sous-estimation de l'altitude du Fouta-Djalon par MERRA-2 n'affecte
donc pas HEP. À l'inverse, la grandeur
`productible_correction_thermique` reposera sur T2M et héritera de ce
caveat.

### 6.4 Périmètre géographique

HEP v1 est calculée uniquement pour les 6 villes pilotes
(Conakry-Kaloum, Kindia, Mamou, Labé, Kankan, Nzérékoré). Extension à
d'autres localités guinéennes ou à un autre pays différée.

## 7. Validation locale

Non bloquante à ce stade. Le schéma de la table `validations` et
`sources_validation` est différé. Aucune confrontation à des données
terrain réelles (stations ANM, EDG, mini-grids privés) n'est requise
pour l'instant.

Quand une source locale se libérera (typiquement via une
caractérisation ANM Guinée), une campagne de validation HEP pourra être
déclenchée et une note de confiance documentée dans
`commentaire_editorial` des lignes concernées, sans modification de la
formule v1.

## 8. Plage de valeurs typiques

### 8.1 Plage théorique attendue

Pour la Guinée tropicale (entre 6° N et 12° N, ressources solaires
considérées comme uniformément élevées), HEP_annuel est typiquement
dans **[1700, 2100] h_eq/an**.

### 8.2 Plage observée 2021-2025 sur les 6 villes pilotes

Mesures empiriques à l'exécution (migration 027) :

| Ville | HEP_annuel min | HEP_annuel max | Pixel CERES |
|---|---:|---:|---|
| Conakry-Kaloum | 1884 | 1954 | côtier distinct |
| Kindia | 1891 | 2005 | pixel partagé avec Mamou |
| Mamou | 1891 | 2005 | pixel partagé avec Kindia |
| Labé | 1971 | 2056 | Fouta-Djalon distinct |
| Kankan | 1985 | 2060 | intérieur soudanien distinct |
| Nzérékoré | 1727 | 1786 | sud forestier distinct |

**Plage globale observée : [1727, 2060] h_eq/an**, intégralement dans
[1700, 2100] prévue. Nzérékoré (sud forestier, climatologie nuageuse
plus marquée) est le minimum observé. Kankan (intérieur soudanien, ciel
clair plus fréquent) est le maximum.

### 8.3 Cohérence somme

L'invariant `sum_{m=1..12} HEP_mensuel(annee, m) = HEP_annuel(annee)`
est vérifié à `rel=1e-9` près sur les 30 (localité, année) du périmètre
(test d'intégration).

## 9. Application Côte d'Ivoire

Décision, vérifications et constats : ADR-0023 (migration 0038).

### 9.1 Calcul depuis le GHI mensuel des 4 sources

L'instance Côte d'Ivoire porte le GHI **mensuel** (moyenne journalière
du mois, kWh/m²/jour) de 4 sources aux 142 localités (31 régions, 111
départements) ; le GHI journalier NASA POWER n'existe qu'aux 34
localités du lot journalier (ADR-0016). Le HEP y est calculé depuis le
mensuel :

```
HEP_mensuel(annee, mois) := GHI_mois(annee, mois) × n_jours(annee, mois)
HEP_annuel(annee)        := sum_{m=1..12} HEP_mensuel(annee, m)   (années complètes seulement)
```

Sur les jours d'un mois, la somme des GHI journaliers vaut le nombre de
jours fois leur moyenne : la formule du § 2 est **inchangée**
(`version_formule = 1`), seule l'entrée change de grain. La complétude
du § 4 s'applique au grain mensuel : une ligne mensuelle par mesure
mensuelle gravée, une ligne annuelle seulement si les 12 mois existent.
Les séries amont sont complètes, sans valeur de remplissage : aucune
année n'est écartée.

| Source | Série amont | Période | Séries `hep` |
|---|---|---|---|
| NASA POWER | `nasa_power_ghi_mensuel_<loc>` | 1991-2025 | `hep_nasa_power_<loc>` |
| CAMS Radiation | `cams_ghi_mensuel_<loc>` | 2005-2025 | `hep_cams_<loc>` |
| SARAH-3 (PVGIS) | `sarah3_ghi_mensuel_<loc>` | 2005-2023 | `hep_sarah3_<loc>` |
| ERA5 (PVGIS) | `era5_ghi_mensuel_<loc>` | 2005-2023 | `hep_era5_<loc>` |

Aucune source n'est désignée « la » source du HEP : un GHI pondéré par
les jours hérite du désaccord entre sources, qui est le savoir tracé
(ADR-0009) ; chacune a donc sa série. 568 séries (source `kuma_calculs`,
méthode `calcul_derive`), 160 176 lignes mensuelles et 13 348 annuelles,
confiance B, statut `brut`. Les séries `hep_era5_<loc>` portent la mise
en garde du saut ERA5 de 2021 (ADR-0018). Calcul hors-ligne en SQL dans
la migration, sommes en `numeric` : valeurs reproductibles au bit près.

### 9.2 Équivalence avec la définition journalière (démontrée)

Aux 34 localités du journalier NASA POWER, sur 1991-2025, la fonction de
la fiche (`services/grandeurs/hep.py`, `_agreger_hep_journaliers`,
complétude stricte des jours civils) appliquée au GHI journalier a été
comparée au HEP NASA calculé depuis le mensuel :

| Contrôle | Périodes | Écart max | Écart relatif max |
|---|---:|---:|---:|
| HEP mensuel | 14 280 mois | 0,0053 h_eq | 4,6·10⁻⁵ |
| HEP annuel | 1 190 années | 0,025 h_eq | 1,4·10⁻⁵ |

Aucun biais : l'écart est l'arrondi déjà mesuré entre la moyenne des
jours NASA et le mensuel NASA (≤ 0,00017 kWh/m²/jour, ADR-0016),
multiplié par le nombre de jours. Le test d'intégration exige un écart
inférieur à 2·10⁻⁴ h_eq par jour de la période, sur toutes les périodes.

### 9.3 Productible théorique

Le productible spécifique théorique se calcule depuis ces lignes `hep`,
mensuelles comprises, et ses lignes mensuelles sont gravées sous
`productible_specifique_theorique` : voir la fiche
`productible_specifique_theorique.md` § 9.

### 9.4 Plage observée ; la plage guinéenne ne se transpose pas

HEP annuel moyen par localité, sur la période de chaque source, puis
distribution sur les 142 localités (h_eq/an) :

| Source | Période | Moyenne | Min – max des moyennes par localité | Min – max des valeurs annuelles |
|---|---|---:|---:|---:|
| NASA POWER | 1991-2025 | 1 772 | 1 648 – 2 066 | 1 591 – 2 116 |
| CAMS | 2005-2025 | 1 957 | 1 687 – 2 171 | 1 623 – 2 219 |
| SARAH-3 | 2005-2023 | 2 001 | 1 808 – 2 204 | 1 738 – 2 247 |
| ERA5 | 2005-2023 | 1 794 | 1 597 – 2 093 | 1 527 – 2 134 |

La plage typique du § 8.1 (`[1700, 2100]` h_eq/an, établie pour la
Guinée) **n'est pas transposable** : sur les 13 348 valeurs annuelles
ivoiriennes, 2 688 sont en dessous (NASA POWER 1 833, ERA5 839, CAMS 16)
et 970 au-dessus (SARAH-3 526, CAMS 411, ERA5 19, NASA POWER 14). Le
garde-fou du calcul ivoirien est donc physique (`0 < HEP ≤ 12 h_eq` par
jour de la période, borne placée au-dessus du rayonnement
extraterrestre, environ 10,5), pas climatologique.

Lecture (constats, pas validation, détail dans ADR-0023) : le HEP croît
du sud au nord ; les sources s'écartent davantage au sud, où le HEP est
une fourchette plutôt qu'une valeur. SARAH-3 est la source la plus
haute, NASA POWER et ERA5 les plus basses.

### 9.5 Maille

Le § 6.2 (Kindia et Mamou) vaut pour la Guinée. En Côte d'Ivoire, NASA
POWER ne distingue que 35 séries GHI mensuelles sur 142 localités
(cellules CERES de 1°) : des localités d'une même cellule ont un HEP
NASA identique, ce que la grandeur `degenerescence_pixel` rend explicite
(ADR-0027). SARAH-3, ERA5 (PVGIS) et CAMS distinguent les 126 points de
coordonnées distinctes.

## 10. Versioning et historique

| Version | Date | Modifications |
|---|---|---|
| v1 | 2026-05 | Définition initiale. Agrégation cumulative GHI, politique de complétude 100% jours civils stricte, plan horizontal STC. |

Toute révision méthodologique (formule, politique de complétude,
hypothèses, source amont) déclenche v2 avec entrée d'historique dans
ce même tableau. Les lignes `grandeurs_metier` v1 restent en base. La
vue `v_grandeurs_metier_courantes` filtre automatiquement sur la
version actuelle.

## 11. Auteurs

- **v1 - 2026-05** : Siba Kalivogui (Kuma Science).

## 12. Références bibliographiques

- NASA POWER methodology - `https://power.larc.nasa.gov/docs/methodology/`
- CERES SYN1deg - `https://ceres.larc.nasa.gov/data/`
