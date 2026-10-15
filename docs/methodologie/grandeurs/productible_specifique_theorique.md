# Fiche méthodologique - `productible_specifique_theorique` (Productible spécifique théorique)

> Conventions communes : voir fiche HEP `hep.md`.
>
> Les §§ 7.2 et 8 décrivent le périmètre de l'instance d'origine
> (Guinée). L'application à la Côte d'Ivoire est au § 9.

## 1. Identification

| Champ | Valeur |
|---|---|
| Nom | Productible spécifique théorique |
| Code métier | `productible_specifique_theorique` |
| Unité | kWh/kWc (numériquement équivalent à h_eq à 1 kW/m² STC) |
| Famille | F1 - fait stocké |
| Stratégie de calcul | `stockee` (persistée dans `grandeurs_metier`) |
| Version courante | 1 |
| Périodicités exposées | annuel + mensuel (héritées de `hep` amont) |

## 2. Définition formelle

```
productible_specifique_theorique(periode) := hep(periode) * pr_theorique
```

Avec `pr_theorique = 0.8` par défaut (industry-standard conservateur,
cohérent IEC 61724-1 et pratiques bureaux d'études).

## 3. Choix de PR_théorique

- **0.8** - valeur conservatrice retenue Kuma v1, cohérente avec :
  - IEC 61724-1:2021 *Photovoltaic system performance - Part 1*
  - NREL PVWatts (PR par défaut 0.84)
  - Pratiques bureaux d'études (0.75-0.85 typique pour installations
    fixes inclinées)
- Permet la comparaison aux outils commerciaux tiers (PVGIS, NREL).
- Le PR utilisateur réel (paramétrable) est exposé via la grandeur
  `productible_pr_fourni`.

## 4. Source amont

`hep` calculée et stockée dans `grandeurs_metier`. Premier module Kuma
à consommer une grandeur Kuma calculée comme amont (chaîne de calculs
Kuma).

## 5. Politique de complétude

Pas de politique propre - héritée de `hep` amont. Si `hep` est absent
pour une `(localite, annee, [mois])`, `productible_specifique_theorique`
l'est aussi par construction.

## 6. Hypothèses physiques

- Convention STC héritée de HEP : `1 kWh/m²/j ↔ 1 h_eq/j à 1 kW/m²`.
- `pr_theorique = 0.8` capture les pertes système agrégées (onduleur,
  câblage, mismatch modules, salissure type, ombrage typique).
- Plan horizontal (transposition POA différée).
- Pas de correction thermique (différée à la grandeur
  `productible_correction_thermique`).

## 7. Limites et portée

### 7.1 PR_théorique fixe

`0.8` est une **borne unique** non paramétrable dans cette grandeur. Un
système réel peut avoir un PR ∈ [0.65, 0.92] selon technologie, climat,
design. Pour calcul paramétrable : grandeur `productible_pr_fourni`.

### 7.2 Co-localisation Kindia / Mamou

Productible_specifique_theorique = HEP × 0.8 → hérite directement de
HEP. Comme HEP, valeurs Kindia ≡ Mamou par effet pixel CERES SYN1deg
partagé.

### 7.3 Cohérence cross-grandeurs `hep` v2

Si `hep.version_formule_actuelle` passe à 2, les lignes
`productible_specifique_theorique` v1 deviennent techniquement
obsolètes mais ne sont pas automatiquement clôturées. Aucun cas
d'upgrade n'est prévu à ce stade.

## 8. Plage de valeurs typiques

### 8.1 Plage théorique attendue

Guinée tropicale, PR = 0.8 :
`productible_specifique_theorique_annuel ∈ [0.8 × 1700, 0.8 × 2100]`
soit **[1360, 1680] kWh/kWc/an**.

### 8.2 Plage observée 2021-2025 sur les 6 villes pilotes

| Ville | Min | Max | Moyenne |
|---|---:|---:|---:|
| Conakry-Kaloum | 1507 | 1563 | 1535 |
| Kankan | 1588 | 1648 | 1623 |
| Kindia | 1513 | 1604 | 1566 |
| Labé | 1577 | 1645 | 1615 |
| Mamou | 1513 | 1604 | 1566 |
| Nzérékoré | 1381 | 1429 | 1402 |

Plage globale [1381, 1648] kWh/kWc/an. Cohérent avec HEP × 0.8.

## 9. Application Côte d'Ivoire

Décision, vérifications et constats : ADR-0023 (migration 0038).

### 9.1 Calcul

`productible_specifique_theorique = hep × 0,8`, formule et version
inchangées (v1). L'amont est le HEP de l'instance, lui-même calculé
depuis le **GHI mensuel des 4 sources aux 142 localités** (fiche
`hep.md` § 9.1) ; le productible se calcule depuis les lignes `hep`
gravées, sa complétude est donc héritée par construction.

- Une série par source et localité :
  `productible_specifique_theorique_<source>_<loc>` (`nasa_power`
  1991-2025, `cams` 2005-2025, `sarah3` et `era5` 2005-2023). 568 séries
  (source `kuma_calculs`), 160 176 lignes mensuelles et 13 348
  annuelles, confiance B, statut `brut`. Les séries ERA5 portent la mise
  en garde du saut de 2021 (ADR-0018).
- **Équivalence avec le journalier démontrée** : elle est héritée du HEP,
  dont le calcul depuis le mensuel reproduit la définition journalière
  à l'arrondi près aux 34 localités du journalier NASA POWER (fiche
  `hep.md` § 9.2).

### 9.2 Lignes mensuelles sous `productible_specifique_theorique`

Les lignes mensuelles du productible sont gravées sous
`productible_specifique_theorique`, `periode_type = 'mensuel'`, et non
sous la grandeur `productible_mensuel` :

1. le service hérité recopie toutes les lignes `hep` courantes,
   annuelles **et** mensuelles, multipliées par le PR, sous la même
   grandeur (§ 1 : « annuel + mensuel ») ;
2. l'unité `kwh_par_kwc_periode` (kWh/kWc sur la période de la mesure)
   porte le mensuel comme l'annuel, alors que `kwh_par_kwc_mois` ne
   peut pas porter une valeur annuelle ;
3. `productible_mensuel` est désactivée au référentiel et n'a aucune
   série : la réactiver doublonnerait la ligne mensuelle sous un second
   code, alors que `periode_type` distingue déjà mensuel et annuel.

Un consommateur lit donc les deux pas dans la même série
(`/v1/series/productible_specifique_theorique_<source>_<loc>`) et les
distingue par `periode_type`.

### 9.3 Plage observée ; la plage guinéenne ne se transpose pas

Productible annuel moyen par localité, sur la période de chaque
source, puis distribution sur les 142 localités (kWh/kWc/an) :

| Source | Période | Moyenne | Min – max des moyennes par localité |
|---|---|---:|---:|
| NASA POWER | 1991-2025 | 1 418 | 1 318 – 1 653 |
| CAMS | 2005-2025 | 1 566 | 1 350 – 1 737 |
| SARAH-3 | 2005-2023 | 1 601 | 1 447 – 1 763 |
| ERA5 | 2005-2023 | 1 435 | 1 278 – 1 674 |

La plage théorique du § 8.1 (`[1360, 1680]` kWh/kWc/an, établie pour la
Guinée) **n'est pas transposable**, pas plus que celle du HEP dont elle
dérive : 2 688 des 13 348 valeurs annuelles ivoiriennes sont en
dessous et 970 au-dessus (mêmes effectifs que pour le HEP, fiche
`hep.md` § 9.4). Le désaccord des sources devient un désaccord de
productible : à Fresco, en moyenne sur la fenêtre commune 2005-2023, le
productible théorique va de 1 312 (NASA POWER) à 1 628 kWh/kWc/an
(SARAH-3).

Le productible reste théorique (§§ 6 et 7) : plan horizontal, PR fixe
0,8, sans correction thermique ; une borne de référence, pas un
productible garanti.

## 10. Versioning et historique

| Version | Date | Modifications |
|---|---|---|
| v1 | 2026-05 | Définition initiale, `pr_theorique = 0.8` fixe, consommation `hep` amont. |

## 11. Auteurs

- v1 - 2026-05 : Siba Kalivogui (Kuma Science).

## 12. Références bibliographiques

- IEC 61724-1:2021 *Photovoltaic system performance - Part 1: Monitoring*.
- NREL PVWatts - Performance Ratio par défaut.
- Fiche HEP - `docs/methodologie/grandeurs/hep.md`
