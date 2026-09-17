# Fiche méthodologique - `productible_specifique_theorique` (Productible spécifique théorique)

> Conventions communes : voir fiche HEP `hep.md`.

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

## 9. Versioning et historique

| Version | Date | Modifications |
|---|---|---|
| v1 | 2026-05 | Définition initiale, `pr_theorique = 0.8` fixe, consommation `hep` amont. |

## 10. Auteurs

- v1 - 2026-05 : Siba Kalivogui (Kuma Science).

## 11. Références bibliographiques

- IEC 61724-1:2021 *Photovoltaic system performance - Part 1: Monitoring*.
- NREL PVWatts - Performance Ratio par défaut.
- Fiche HEP - `docs/methodologie/grandeurs/hep.md`
