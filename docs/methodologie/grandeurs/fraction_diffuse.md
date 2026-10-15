# Fiche méthodologique - `fraction_diffuse` (Fraction diffuse de l'irradiation)

> Conventions communes (versioning, politique de complétude, identité
> métier `grandeurs_metier`) : voir fiche HEP `hep.md`.
>
> Les §§ 3, 6 et 8.2 décrivent le périmètre de l'instance d'origine
> (Guinée). L'application à la Côte d'Ivoire est au § 9.

## 1. Identification

| Champ | Valeur |
|---|---|
| Nom | Fraction diffuse de l'irradiation |
| Code métier | `fraction_diffuse` |
| Unité | sans dimension |
| Famille | F1 - fait stocké |
| Stratégie de calcul | `stockee` (persistée dans `grandeurs_metier`) |
| Version courante | 1 |
| Périodicités exposées | annuel + mensuel |

## 2. Définition formelle

Rapport entre l'irradiation diffuse horizontale (DHI) et l'irradiation
globale horizontale (GHI) sur une période :

```
fraction_diffuse(annee)       := sum DHI(t) / sum GHI(t) sur t ∈ jours(annee)
fraction_diffuse(annee, mois) := sum DHI(t) / sum GHI(t) sur t ∈ jours(annee, mois)
```

## 3. Source amont

`dhi` et `ghi` journaliers NASA POWER (paramètres `ALLSKY_SFC_SW_DIFF`
et `ALLSKY_SFC_SW_DWN`). DHI source CERES SYN1deg + FLASHFlux.
Méthodologie NASA POWER : `https://power.larc.nasa.gov/docs/methodology/`.

## 4. Politique de complétude

Stricte 100% jours civils v1 sur l'**intersection** des dates présentes
dans DHI et GHI. Mêmes principes que `hep` (cf. fiche `hep.md` § 4).

Garde-fou supplémentaire : si `sum(GHI)` ≤ 0 sur la période (cas
pathologique non observable), la période est skipped (division par
zéro évitée).

## 5. Hypothèses physiques

Aucune hypothèse PV (ressource solaire pure). Pas de paramètre
utilisateur. Cohérence physique DHI ≤ GHI mathématiquement garantie par
construction NASA POWER → fraction_diffuse ∈ [0, 1].

## 6. Limites et portée

### 6.1 Granularité spatiale CERES SYN1deg

Co-localisation Kindia / Mamou dans le même pixel CERES SYN1deg
(1° × 1° 110 km à 10° N). Conséquence : valeurs fraction_diffuse
identiques pour ces deux localités. Cf. fiche HEP § 6.2.

### 6.2 Skip 2024 par sentinelle DHI

Une sentinelle `-999.0` observée sur DHI au cours de 2024 (panne CERES
ponctuelle) provoque le skip de l'année 2024 + du mois affecté pour les
6 villes. Décompte effectif : 378 lignes (vs 390 théorique sans
sentinelle).

## 7. Validation locale

Non bloquante à ce stade. Cf. fiche `hep.md` § 7.

## 8. Plage de valeurs typiques

### 8.1 Plage théorique attendue

Régime tropical africain : fraction_diffuse ∈ [0.3, 0.6] selon couverture
nuageuse.

### 8.2 Plage observée 2021-2025 sur les 6 villes pilotes

| Ville | Min | Max | Moyenne | Note |
|---|---:|---:|---:|---|
| Conakry-Kaloum | 0.432 | 0.456 | 0.443 | côtier |
| Kankan | 0.439 | 0.458 | 0.448 | soudanien |
| Kindia | 0.443 | 0.457 | 0.452 | pixel partagé Mamou |
| Labé | 0.439 | 0.458 | 0.449 | Fouta-Djalon |
| Mamou | 0.443 | 0.457 | 0.452 | pixel partagé Kindia |
| Nzérékoré | 0.492 | 0.529 | 0.507 | sud forestier (max) |

Plage globale [0.432, 0.529]. Nzérékoré présente la plus haute fraction
diffuse (climat équatorial humide, nuages fréquents). Conakry et Kankan
présentent les plus basses (climats plus secs).

## 9. Application Côte d'Ivoire

Deux sources, deux séries par localité : NASA POWER (ADR-0014, étendue
par ADR-0017 et ADR-0018) et CAMS Radiation (ADR-0025). Même formule,
même version (v1), même politique.

### 9.1 Calcul depuis le mensuel

L'instance porte le DHI et le GHI **mensuels** (moyenne journalière du
mois). Sur les jours d'un mois, `Σ DHI / Σ GHI = moy(DHI) / moy(GHI)` ;
sur une année, `Σ_m DHI_m·n_m / Σ_m GHI_m·n_m` (`n_m` = jours du mois).
La formule du § 2 est donc inchangée ; seule l'entrée change de grain.
Vérification contre le NASA POWER journalier (Abidjan, 2005) : écart
maximal 0,000035 sur la fraction mensuelle et 0,000006 sur l'annuelle,
dû à l'arrondi des seeds (ADR-0014).

Limite : la complétude « 100 % des jours civils » du § 4 ne se vérifie
pas au grain journalier sur un produit mensuel ; elle s'applique au
grain mensuel (une année n'est gravée que si ses 12 mois existent dans
les deux séries). Les séries mensuelles amont ne contiennent aucune
valeur de remplissage : le skip du § 6.2 n'a pas d'équivalent ici.
Sommes annuelles en `numeric`, quotient en `float8` : valeurs
reproductibles au bit près (ADR-0017).

| Source | Séries | Période | Lignes mensuelles | Lignes annuelles |
|---|---|---|---:|---:|
| NASA POWER | `fraction_diffuse_nasa_power_<loc>` | 2001-2025 | 42 600 | 3 550 |
| CAMS Radiation | `fraction_diffuse_cams_<loc>` | 2005-2025 | 35 784 | 2 982 |

142 localités par source (31 régions, 111 départements), source
`kuma_calculs`, confiance B, statut `brut`. La série NASA commence en
2001 : le DHI NASA est en rupture avant cette date (ADR-0013 ; la
première version de la gravure sur 1991-2020 a échoué sur des valeurs
supérieures à 1). CAMS sert un DHI et un GHI natifs ; c'est la seule
autre source où la fraction diffuse se calcule sans reconstruction.

Un consommateur doit **choisir la série** : la grandeur seule
n'identifie plus une valeur.

### 9.2 Plage observée et comparaison des deux sources

Fenêtre commune 2005-2025, moyennes des valeurs annuelles par localité :

| Source | Moyenne | Min (localité) | Max (localité) |
|---|---:|---|---|
| CAMS Radiation | 0,489 | 0,405 (Tengréla) | 0,592 (département d'Abidjan) |
| NASA POWER | 0,521 | 0,443 (Folon, Minignan) | 0,555 (Adzopé et sa cellule) |

- **Plage du § 8.1** (`[0,3 ; 0,6]`) : toutes les valeurs annuelles NASA
  y sont (0,410 à 0,577 sur 2001-2025) ; 8 valeurs annuelles CAMS sur
  2 982 la dépassent. Au mensuel, les deux sources en sortent
  régulièrement (CAMS plus souvent), toujours dans `[0, 1]`.
- **CAMS voit moins de diffus que NASA** dans 136 localités sur 142 ; les
  6 exceptions sont dans le sud-est.
- La part diffuse décroît du sud au nord dans les deux sources ; l'écart
  entre elles se creuse au nord et en saison sèche (Harmattan), et se
  resserre en mousson (ADR-0025).
- **Maille** : CAMS donne 126 valeurs moyennes distinctes sur 142
  localités, NASA 35 (cellules CERES de 1°) ; CAMS distingue le cordon
  littoral de l'arrière-pays que NASA confond. Le § 6.1 (Kindia et
  Mamou) vaut pour la Guinée.

Deux sources ne disent pas laquelle a raison : aucune attribution
physique n'est tranchée (ADR-0025).

## 10. Versioning et historique

| Version | Date | Modifications |
|---|---|---|
| v1 | 2026-05 | Définition initiale, ratio cumulatif DHI/GHI annuel + mensuel sur intersection des dates communes. |

## 11. Auteurs

- v1 - 2026-05 : Siba Kalivogui (Kuma Science).

## 12. Références bibliographiques

- NASA POWER methodology - `https://power.larc.nasa.gov/docs/methodology/`
- CERES SYN1deg - `https://ceres.larc.nasa.gov/data/`
- Fiche HEP référence pour conventions communes - `docs/methodologie/grandeurs/hep.md`
