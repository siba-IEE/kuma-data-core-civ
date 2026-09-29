# ADR-0014 : Fraction diffuse NASA POWER (depuis le mensuel)

Date : 2026-09-29. Statut : accepté — **gravé** (migration 0024, 2026-09-29).

## Contexte

La grandeur `fraction_diffuse` (id 3, F1 `stockee`, sans dimension) est seedée
depuis 0002 avec sa fiche méthodologique
(`docs/methodologie/grandeurs/fraction_diffuse.md`) :

```
fraction_diffuse(annee, mois) := Σ DHI(t) / Σ GHI(t), t ∈ jours(annee, mois)
fraction_diffuse(annee)       := Σ DHI(t) / Σ GHI(t), t ∈ jours(annee)
```

Source amont fixée par la fiche : **NASA POWER** (DHI et GHI). Le service du
moteur (`services/grandeurs/fraction_diffuse.py`) part de mesures
**journalières** ; l'instance CIV ne porte que le **mensuel** NASA (moyenne
journalière du mois), gravé en 0008 (GHI) et 0021 (DHI, ADR-0013).

## Décision

### Calcul depuis le mensuel — même formule, version 1

Sur les jours d'un mois, `Σ DHI / Σ GHI = moy(DHI) / moy(GHI)`. Sur une année,
`Σ_m DHI_m·n_m / Σ_m GHI_m·n_m` (`n_m` = jours du mois). La formule de la fiche
est donc **inchangée** (`version_formule = 1`) ; seule l'entrée change de grain.

**Vérification de l'équivalence** contre le NASA POWER **journalier** (Abidjan,
2005, 365 jours, aucun remplissage) :

| Contrôle | Écart max |
|---|---:|
| moyenne des jours vs mensuel NASA (GHI et DHI) | 0,0001 kWh/m²/jour |
| fraction diffuse mensuelle, calcul journalier vs mensuel | 0,000035 |
| fraction diffuse annuelle 2005 (0,53956 vs 0,53957) | 0,000006 |

L'écart résiduel vient de l'arrondi des seeds à 4 décimales. **Limite** : la
complétude « 100 % des jours civils » de la fiche ne se vérifie pas au grain
journalier sur un produit mensuel ; elle est appliquée au grain mensuel (une
année n'est gravée que si ses 12 mois existent dans les deux séries), et les
séries mensuelles NASA ne contiennent aucune valeur de remplissage.

### Périmètre

- Source : NASA POWER seulement, comme le prévoit la fiche. L'identité de
  `grandeurs_metier` inclut la série, donc une fraction diffuse CAMS pourrait
  coexister ; ce serait une décision distincte.
- Fenêtre **2001-2020** : celle du DHI NASA (rupture avant 2001, ADR-0013).
- 3 séries `calcul_derive` (source `kuma_calculs`), **720 lignes mensuelles** et
  **60 annuelles**, confiance **B**.
- Calcul **hors-ligne, en base, par jointure SQL**. Garde-fous : nombre de
  lignes, et toute valeur dans `[0, 1]`.

Ce garde-fou `[0, 1]` a fait échouer la 1ʳᵉ version (DHI NASA 1991-2020) sur 10
valeurs > 1, révélant la rupture du DHI NASA avant 2001 (ADR-0013).

## Résultat (2001-2020)

| Point | Annuel moyen | Annuel min – max | Mensuel DJF | Mensuel JJA | Mensuel min – max |
|---|---:|---:|---:|---:|---:|
| Abidjan | 0,544 | 0,530 – 0,563 | 0,543 | 0,577 | 0,438 – 0,652 |
| Yamoussoukro | 0,548 | 0,531 – 0,567 | 0,527 | 0,591 | 0,442 – 0,659 |
| Korhogo | 0,483 | 0,460 – 0,506 | 0,441 | 0,539 | 0,345 – 0,595 |

Les valeurs **annuelles** sont toutes dans la plage tropicale attendue par la
fiche (`[0,3 ; 0,6]`) ; quelques valeurs **mensuelles** de mousson la
dépassent (jusqu'à 0,659), tout en restant dans `[0, 1]`. La part diffuse est
la plus forte en mousson (JJA) et la plus faible à Korhogo, le point le plus au
nord. Ce sont des constats sur
NASA POWER seul, pas une validation : la fraction diffuse hérite des biais des
deux entrées.

## Conséquences

- Première grandeur métier **non-écart** matérialisée dans l'instance.
- Le patron « calcul SQL hors-ligne depuis le mensuel » est réutilisable pour
  d'autres grandeurs F1 dont la formule est un rapport de sommes.
- Une fraction diffuse par source (CAMS) reste possible, sur décision.
