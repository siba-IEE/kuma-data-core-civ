# Fiche méthodologique - `fraction_diffuse` (Fraction diffuse de l'irradiation)

> Conventions communes (versioning, politique de complétude, identité
> métier `grandeurs_metier`) : voir fiche HEP `hep.md`.

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

## 9. Versioning et historique

| Version | Date | Modifications |
|---|---|---|
| v1 | 2026-05 | Définition initiale, ratio cumulatif DHI/GHI annuel + mensuel sur intersection des dates communes. |

## 10. Auteurs

- v1 - 2026-05 : Siba Kalivogui (Kuma Science).

## 11. Références bibliographiques

- NASA POWER methodology - `https://power.larc.nasa.gov/docs/methodology/`
- CERES SYN1deg - `https://ceres.larc.nasa.gov/data/`
- Fiche HEP référence pour conventions communes - `docs/methodologie/grandeurs/hep.md`
