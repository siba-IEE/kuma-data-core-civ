# Fiche méthodologique - `indicateur_qualite_donnees` (score qualité 1-5)

> Conventions communes : voir fiche HEP `hep.md`.

## 1. Identification

| Champ | Valeur |
|---|---|
| Nom | Score éditorial de qualité d'une série mesurée |
| Code métier | `indicateur_qualite_donnees` |
| Unité | `sans_unite` (échelle ordinale 1-5) |
| Famille | F1 - fait stocké |
| Stratégie de calcul | `stockee` (persistée dans `grandeurs_metier`) |
| Version courante | 1 |
| Périodicités exposées | **statique uniquement** (1 valeur par série sur 2021-2025, cf. § 4) |

## 2. Définition formelle

### 2.1 Trois composantes pondérées

Le score continu est une combinaison linéaire de trois composantes
normalisées dans `[0, 1]`, pondérées selon une grille figée v1 :

| Composante | Définition | Plage | Coefficient |
|---|---|---|---|
| **C1 - Complétude** | `nb_mesures_courantes_non_depreciees / nb_jours_attendus_plage` | `[0, 1]` | 0.5 |
| **C2 - Niveau de confiance moyen** | Moyenne pondérée des `niveau_confiance_derive` sur les mesures courantes : `A=1.0`, `B=0.7`, `C=0.4` | `[0.4, 1.0]` | 0.3 |
| **C3 - Fiabilité de source** | Mapping `sources.fiabilite` : `haute=1.0`, `moyenne=0.7`, `faible=0.4` | `{0.4, 0.7, 1.0}` | 0.2 |

```
score_continu = 0.5 * C1 + 0.3 * C2 + 0.2 * C3
```

### 2.2 Binning vers l'échelle 1-5

Le score continu est projeté sur l'échelle ordinale `{1, 2, 3, 4, 5}`
fixée par le seed `grandeurs_referentiel` (migration 010) :

| Score continu | Score discret |
|---|---|
| `[0.0, 0.2)` | 1 |
| `[0.2, 0.4)` | 2 |
| `[0.4, 0.6)` | 3 |
| `[0.6, 0.8)` | 4 |
| `[0.8, 1.0]` | 5 |

Intervalles fermé-ouvert sur les bornes inférieures des bins 1-4 ; le
bin 5 est fermé à droite pour absorber le cas `score_continu = 1.0`
exactement (mesures parfaitement courantes, toutes en niveau A, source
en fiabilité haute).

### 2.3 Stockage

Une ligne `grandeurs_metier` par série évaluée :

- `grandeur_code = 'indicateur_qualite_donnees'`
- `periode_type = 'statique'`, `mois IS NULL`, `annee_debut = 2021`,
  `annee_fin = 2025`
- `valeur` = score discret entier dans `{1..5}`
- `niveau_confiance_derive = 'B'` (constant, cf. § 5.2)
- `series_metadonnees_id` = **ID de la série évaluée** (exception
  méthodologique, cf. § 6.3)

Le score continu n'est pas persisté - il est logué dans la migration
037 via `op.execute('-- ...')` ligne par ligne pour traçabilité
d'audit.

## 3. Source amont des données d'entrée

L'indicateur ne consomme aucune nouvelle donnée externe. Il agrège des
informations **déjà présentes dans le dépôt** :

| Lecture | Origine |
|---|---|
| C1 (numérateur) | `COUNT(mesures_ressource WHERE serie_id = :id AND valide_au IS NULL AND statut <> 'deprecie')` |
| C1 (dénominateur) | `nb_jours_civils(annee_debut, annee_fin)` = 1826 sur 2021-2025 |
| C2 | Moyenne pondérée de `mesures_ressource.niveau_confiance_derive` sur les mesures courantes |
| C3 | `sources.fiabilite` de la source de la série évaluée (lecture indirecte via `series_metadonnees.source_id`) |

Les 36 séries brutes évaluées sont toutes issues de NASA POWER
(source `nasa_power`, `fiabilite='haute'`, `methode_collecte='modele_satellitaire'`).
Acknowledgement NASA POWER hérité des séries amont.

## 4. Politique de complétude

**Non applicable au sens habituel.** Pour les autres grandeurs F1
stockées (`hep`, `humidex`, `fraction_diffuse`, etc.), la politique de
complétude conditionne l'insertion sur la présence intégrale des jours
civils amont (cf. fiche `hep.md` § 4). Ici, **l'indicateur est lui-même
une mesure de la complétude** des séries amont, exprimée par la
composante C1.

Conséquences :

- Aucune ligne n'est skipée pour cause d'incomplétude amont - au
  contraire, une série partielle produit simplement un score discret
  plus bas.
- Le score 1 ou 2 (théoriquement possible mais non observé, cf.
  § 8) marque éditorialement une série fortement incomplète ou
  faiblement fiable.
- Pas de niveau de confiance dégradé en C ; la ligne `grandeurs_metier`
  porte systématiquement `niveau_confiance_derive='B'` (cf. § 5.2).

## 5. Hypothèses méthodologiques

### 5.1 Pondération `(0.5, 0.3, 0.2)`

Pondération figée v1. La complétude domine (0.5) car elle est la plus
discriminante éditorialement : une série amont avec un trou systématique
sur une saison entière biaise toutes les grandeurs dérivées. Confiance
moyenne (0.3) et fiabilité de source (0.2) viennent moduler le score
mais ne le portent pas seuls. La paramétrabilité de la pondération est
différée v2+ avec déclencheur explicite (besoin éditorial concret).

### 5.2 Constantes (les 36 séries brutes)

Toutes les séries brutes partagent
`methode_collecte='modele_satellitaire'` et source `nasa_power`
`fiabilite='haute'`. Par règles R1-R4 de
`editorial/niveaux_confiance.py`, le niveau dérivé des mesures
journalières est uniformément `B`. Donc :

- C2 = 0.7 constant
- C3 = 1.0 constant
- `score_continu = 0.5 * C1 + 0.21 + 0.20 = 0.5 * C1 + 0.41`

Plage théorique : `score_continu ∈ [0.41, 0.91]`. Plage
discrétisée : `{3, 4, 5}`. Dominée par C1.

Le `niveau_confiance_derive` de la ligne `grandeurs_metier` portant
l'indicateur lui-même est `B` (R4 catch-all :
`methode_collecte='calcul_derive'` + source `kuma_calculs`
`fiabilite='haute'`). Pas de NULL.

### 5.3 Migration corrective de la contrainte EXCLUDE

La contrainte `ex_grandeurs_metier_identite_periode` (BTree-GiST posée
à la création de la table en migration 023) ne contenait pas
`series_metadonnees_id` dans sa clé. Forme initiale :

```
EXCLUDE USING gist (
    grandeur_code WITH =,
    localite_id WITH =,
    periode_type WITH =,
    annee_debut WITH =,
    annee_fin WITH =,
    COALESCE(mois, 0) WITH =,
    version_formule WITH =,
    tstzrange(valide_du, valide_au) WITH &&
)
```

Cette forme convenait aux 5 grandeurs calculées Kuma (1 série
calculée par `(localite, grandeur)` : la cardinalité par identité
métier coïncidait avec celle des séries pointées). Elle interdisait
en revanche les 36 lignes de l'indicateur, car
`indicateur_qualite_donnees` pointe **6 séries brutes par localité**
(GHI / DNI / DHI / T2M / RH2M / KT) - 6 lignes avec tuple EXCLUDE
identique.

Résolution retenue : **migration 037 corrective** ajoute
`series_metadonnees_id WITH =` à la clé EXCLUDE. La migration 038
(calcul + insertion 36 lignes) consomme le nouveau DDL.

Vérification factuelle préalable : 0 doublon hypothétique sur les
1 578 lignes courantes existantes avec la clé augmentée - modification
rétro-compatible.

### 5.4 Composantes écartées v1

Les composantes suivantes ont été **écartées explicitement v1** avec
déclencheur ouvert :

| Composante écartée | Déclencheur v2+ |
|---|---|
| Sentinelles (taux de mesures sentinelles avant filtrage) | Nécessite compteur persisté côté `series_metadonnees` |
| Cohérence cross-grandeurs (ex : GHI ≥ DHI quotidien) | Nécessite définition de seuils par grandeur |
| Latence climat-quality (âge max des mesures vs aujourd'hui) | Nécessite une politique de fraîcheur |
| Imputations / interpolations appliquées | Pas d'imputation à ce stade |

## 6. Limites et portée

### 6.1 Plage effective `{3, 4, 5}`

La plage théorique de l'indicateur est `{1, 2, 3, 4, 5}`. Du fait des
constantes C2=0.7 et C3=1.0, la plage observée est restreinte à
`{3, 4, 5}`. **Les valeurs 1 et 2 ne sont pas atteignables tant que les
36 séries brutes restent toutes NASA POWER `modele_satellitaire`.** Une
nouvelle source de fiabilité moyenne/faible ou une méthode de collecte
plus dégradée pourrait étendre la plage observée.

### 6.2 Non applicable aux séries calculées Kuma v1

**Limite éditoriale figée v1.** L'indicateur v1 ne s'applique pas aux 30
séries calculées Kuma (`hep`, `fraction_diffuse`, `humidex`,
`productible_specifique_theorique`, `variabilite_journaliere`). La
qualité de ces séries calculées est implicitement traçable via la
qualité des séries amont qu'elles consomment (GHI, DHI, T2M, RH2M, KT).
Une propagation récursive de l'indicateur des séries amont vers les
séries calculées sera introduite v2+ avec déclencheur explicite (besoin
éditorial concret de noter la qualité d'une grandeur calculée
indépendamment de ses entrées).

### 6.3 Exception méthodologique - `series_metadonnees_id`

Pour les autres grandeurs calculées Kuma, une **nouvelle entrée
`series_metadonnees`** est créée par seed avec
`source_code='kuma_calculs'` et la ligne `grandeurs_metier`
référence cette série calculée. Ici, **aucune nouvelle série n'est
créée** : la ligne `grandeurs_metier` portant
`grandeur_code='indicateur_qualite_donnees'` référence directement
la série évaluée (brute NASA POWER). Conséquence :
`gm.grandeur_code='indicateur_qualite_donnees'` ne correspond
**pas** à `sm.grandeur_code` (qui vaut `ghi`, `dni`, `dhi`, `t2m`,
`rh2m` ou `kt` selon la série pointée).

Cette exception a nécessité l'ajustement de la contrainte
`ex_grandeurs_metier_identite_periode`, résolu par la migration
corrective 037 (cf. § 5.3).

### 6.4 Pas de fenêtre glissante v1

Le score est statique sur la plage entière 2021-2025. Une périodicité
annuelle ou mensuelle est différée v2+ avec déclencheur.

### 6.5 Pas d'override éditorial v1

Le mécanisme `niveau_confiance_override` reste disponible côté lignes
individuelles de `mesures_ressource` ou `grandeurs_metier`. **Aucun
mécanisme symétrique d'override sur l'indicateur lui-même n'est exposé
v1.** Si Kuma souhaite éditorialement augmenter ou diminuer le score
d'une série au-delà de ce que la formule calcule, ce sera v2+.

### 6.6 Score continu non persisté

Seul le score discret 1-5 est persisté dans `grandeurs_metier.valeur`.
Le score continu est logué via `op.execute('-- ...')` dans la migration
037 pour audit ex post mais n'est pas relisible par requête SQL.

## 7. Validation locale

Non bloquante à ce stade. L'indicateur agrège des informations internes
au dépôt ; il n'a pas de référent terrain à confronter. La validité
éditoriale du score v1 dépend de la justesse de la pondération
`(0.5, 0.3, 0.2)`, qui peut être révisée v2+.

## 8. Plage de valeurs typiques

### 8.1 Plage théorique

`{1, 2, 3, 4, 5}` (échelle pré-cadrée par seed migration 010).

### 8.2 Plage effective théorique sous les constantes actuelles

Compte tenu des constantes `C2 = 0.7` et `C3 = 1.0`
(cf. § 5.2), la formule devient `score_continu = 0.5 * C1 + 0.41`.
La projection sur l'échelle 1-5 entier donne le mapping C1 ↔ score
discret suivant :

| Plage `C1` | Plage `score_continu` | Score discret |
|---|---|---|
| `[0.78, 1.00]` | `[0.80, 0.91]` | 5 |
| `[0.38, 0.78)` | `[0.60, 0.80)` | 4 |
| `[0.00, 0.38)` | `[0.41, 0.60)` | 3 |

Les bins 1 et 2 ne sont pas atteignables (les sols de
`score_continu = 0.41` pour C1 = 0 dépassent déjà 0.4, borne basse du
bin 3). Plage effective théorique : `{3, 4, 5}`.

### 8.3 Plage observée 2021-2025 sur les 36 séries brutes NASA POWER

Constat factuel à l'exécution de la migration 038 sur les 6 villes
pilotes :

- **18 séries** (GHI, T2M, RH2M × 6 villes) : `nb_mesures = 1826/1826`
  → `C1 = 1.0` → `score_continu = 0.9100` → score discret **5**.
- **18 séries** (DNI, DHI, KT × 6 villes) : `nb_mesures = 1825/1826`
  (1 sentinelle `-999.0` filtrée au 2025-12-31, liée à l'asymétrie de
  lag CERES) → `C1 = 0.99945` → `score_continu = 0.9097`
  → score discret **5**.

**Plage observée : `{5}`**. Tous les bruts NASA POWER atteignent le
bin maximum. La distinction entre 1 sentinelle filtrée et complétude
parfaite est invisible à l'échelle discrétisée, mais préservée dans le
log `op.execute('--')` de la migration 038
(`(serie_code, c1, c2, c3, score_continu, score_discret)`).

L'écart entre la plage théorique `{3, 4, 5}` et la plage observée
`{5}` reflète la qualité homogène et élevée des séries brutes NASA
POWER. L'introduction de sources futures à fiabilité moyenne/faible ou
de séries fortement incomplètes étendrait la plage observée.

## 9. Versioning et historique

| Version | Date | Modifications |
|---|---|---|
| v1 | 2026-05 | Définition initiale 3 composantes pondérées `(C1=0.5, C2=0.3, C3=0.2)`, binning fermé-ouvert sauf bin 5 fermé, périmètre 36 séries brutes, périodicité statique 2021-2025, pas de récursivité sur séries calculées, pas d'override symétrique. |

Toute révision méthodologique (pondération, composantes,
récursivité, binning) déclenchera v2 avec migration corrective sur
`grandeurs_referentiel.version_formule_actuelle` (même pattern que
HEP). Les lignes v1 restent en base ; la vue
`v_grandeurs_metier_courantes` filtre automatiquement sur la version
actuelle.

## 10. Auteurs

- **v1 - 2026-05** : Siba Kalivogui (Kuma Science).

## 11. Références bibliographiques

- Fiche HEP référence - `docs/methodologie/grandeurs/hep.md`
- Module `editorial/niveaux_confiance.py` (règles R1-R4) - `src/kuma_data_core/editorial/niveaux_confiance.py`
