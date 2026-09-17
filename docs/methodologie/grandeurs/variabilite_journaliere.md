# Fiche méthodologique - `variabilite_journaliere` (Indice de variabilité journalière)

> Conventions communes : voir fiche HEP `hep.md`.

## 1. Identification

| Champ | Valeur |
|---|---|
| Nom | Indice de variabilité journalière (coefficient de variation) |
| Code métier | `variabilite_journaliere` |
| Unité | sans dimension |
| Famille | F1 - fait stocké |
| Stratégie de calcul | `stockee` (persistée dans `grandeurs_metier`) |
| Version courante | 1 |
| Périodicités exposées | **annuel uniquement** (cf. § 4) |

## 2. Définition formelle

Coefficient de variation (CoV) du GHI journalier sur une année :

```
CoV(annee) := sigma(GHI_jour sur annee) / mu(GHI_jour sur annee)
```

Avec sigma = écart-type d'échantillon (`ddof=0`, divisé par N), mu =
moyenne arithmétique. Indicateur statistique standard sans dimension.

## 3. Source amont

`ghi` journalier NASA POWER (paramètre `ALLSKY_SFC_SW_DWN`).

## 4. Périodicité annuelle uniquement

Pas de calcul mensuel. Justification : un mois (28-31 jours) est
statistiquement peu robuste pour un coefficient de variation qui
demande typiquement N ≥ 30 observations. Année (365-366 jours)
satisfait cette condition.

## 5. Politique de complétude

Stricte 100% jours civils v1 (héritée fiche `hep.md` § 4). Si une
année manque un jour de GHI, l'année est skipped.

Garde-fou supplémentaire : si `mean(GHI)` ≤ 0 sur la période (cas
pathologique non observable), l'année est skipped (CoV non défini).

## 6. Interprétation

- CoV 0.15 - climat très stable (équatorial humide, irradiation
  régulière toute l'année).
- CoV 0.25 - climat à transition saisonnière marquée (côtier tropical).
- CoV 0.40+ - climat à forte variabilité (latitudes moyennes,
  transitions été/hiver).

Utilité éditoriale principale : **dimensionnement de systèmes avec
stockage** (CoV élevé → besoin de stockage plus grand pour lisser la
production).

## 7. Limites et portée

### 7.1 Co-localisation Kindia / Mamou

`variabilite_journaliere` consomme GHI directement. Kindia et Mamou
partagent le même pixel CERES SYN1deg → CoV identique à la décimale
près (constat factuel : Kindia 0.190 ≡ Mamou 0.190).

### 7.2 Sensibilité au choix `ddof`

`ddof=0` (variance de population, divisé par N) retenu. Alternative
`ddof=1` (échantillon non biaisé, divisé par N-1) donnerait des
valeurs très légèrement supérieures (0.1% sur 365 obs). Choix
non discriminant à cette échelle, `ddof=0` plus simple et cohérent
avec NumPy default.

## 8. Plage de valeurs typiques

### 8.1 Plage théorique attendue

Climatologie solaire intertropicale : CoV ∈ [0.10, 0.40] selon zone.

### 8.2 Plage observée 2021-2025 sur les 6 villes pilotes

| Ville | Min | Max | Moyenne | Climat |
|---|---:|---:|---:|---|
| Conakry-Kaloum | 0.212 | 0.269 | 0.237 | côtier (max, transition saisons) |
| Kankan | 0.171 | 0.193 | 0.179 | soudanien |
| Kindia | 0.177 | 0.207 | 0.190 | pixel partagé Mamou |
| Labé | 0.180 | 0.220 | 0.194 | Fouta-Djalon |
| Mamou | 0.177 | 0.207 | 0.190 | pixel partagé Kindia |
| Nzérékoré | 0.156 | 0.192 | 0.177 | équatorial humide (min, stable) |

Plage globale [0.156, 0.269]. Conakry-Kaloum présente le CoV le plus
élevé (climat côtier avec saison sèche/humide marquée), Nzérékoré le
plus bas (climat équatorial humide plus stable). Cohérent avec la
climatologie ouest-africaine.

## 9. Versioning et historique

| Version | Date | Modifications |
|---|---|---|
| v1 | 2026-05 | Définition initiale CoV annuel, `ddof=0`, périodicité annuelle uniquement. |

## 10. Auteurs

- v1 - 2026-05 : Siba Kalivogui (Kuma Science).

## 11. Références bibliographiques

- Coefficient de variation - statistique classique, cf. Wikipedia /
  *Encyclopedia of Statistical Sciences*.
- Variability Index - PVsyst, Solargis (concept apparenté pour
  dimensionnement PV).
- NASA POWER methodology - `https://power.larc.nasa.gov/docs/methodology/`
- Fiche HEP - `docs/methodologie/grandeurs/hep.md`
