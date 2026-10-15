# ADR-0025 : Fraction diffuse CAMS, deuxième source

Date : 2026-10-15. Statut : accepté — **gravé** (migration 0040, 2026-10-15).

## Contexte

La fraction diffuse (`fraction_diffuse`, id 3) n'existe que depuis NASA POWER
(ADR-0014, étendue aux 142 localités par ADR-0017 et jusqu'en 2025 par
ADR-0018). ADR-0014 laissait ouverte une fraction diffuse par source :
l'identité de `grandeurs_metier` inclut la série, donc deux sources peuvent
coexister pour la même grandeur, la même localité et la même période. CAMS
Radiation sert un DHI et un GHI natifs (ADR-0011, ADR-0013), gravés aux 142
localités sur 2005-2025 : c'est la seule autre source où la fraction diffuse
se calcule sans reconstruction (PVGIS ne sert qu'un `Kd` arrondi, ADR-0013).

## Décision

### Même formule, même politique que la série NASA (version 1)

- Mensuel : `moy(DHI) / moy(GHI)` = `Σ DHI / Σ GHI` sur les jours du mois.
- Annuel : `Σ_m DHI_m·n_m / Σ_m GHI_m·n_m` (`n_m` = jours du mois), sommes en
  `numeric` puis quotient en `float8` (reproductible au bit près, ADR-0017) ;
  année gravée seulement si ses 12 mois existent dans les deux séries.
- Mêmes limites qu'ADR-0014 : la complétude des jours civils s'applique au
  grain mensuel (CAMS sert des irradiations mensuelles intégrées, converties
  en moyennes journalières, ADR-0011).

### Gravure (migration 0040)

- 142 séries `fraction_diffuse_cams_<localité>` (source `kuma_calculs`,
  méthode `calcul_derive`), période 2005-2025, à côté des séries
  `fraction_diffuse_nasa_power_<localité>`, inchangées ;
- **35 784 lignes mensuelles** (252 mois × 142) et **2 982 annuelles**
  (21 ans × 142), confiance **B** ;
- jointure SQL hors-ligne sur les séries CAMS **mensuelles** DHI et GHI ;
  garde-fous : aucune série CAMS préexistante, 142 séries amont par grandeur
  sur 2005-2025, comptes exacts, 21 années par localité, toute valeur dans
  `[0, 1]`. `ANALYZE grandeurs_metier` en fin de migration. Le `downgrade`
  supprime lignes et séries CAMS ; la série NASA reste intacte.

Le test d'intégration de la fraction diffuse NASA, qui supposait une seule
source pour la grandeur, se limite désormais aux séries NASA (filtre sur le
code de série) ; la série CAMS a ses propres tests (recalcul indépendant depuis
les seeds et CSV CAMS, coexistence avec NASA).

## Résultat — comparaison avec la fraction diffuse NASA (2005-2025)

Fenêtre commune 2005-2025, 142 localités, paires (localité, période) des deux
séries gravées. « Écart » = CAMS − NASA, en points de fraction.

| Période | CAMS | NASA | Écart | Écart relatif | Mois où CAMS > NASA |
|---|---:|---:|---:|---:|---:|
| Annuel | 0,489 | 0,521 | −0,032 | −6,3 % | 284 / 2 982 années |
| DJF (Harmattan) | 0,441 | 0,497 | **−0,056** | −11,5 % | 5,6 % |
| MAM | 0,489 | 0,523 | −0,033 | −6,3 % | 16,1 % |
| JJA (mousson) | 0,579 | 0,570 | +0,009 | +1,3 % | 52,1 % |
| SON | 0,471 | 0,509 | −0,038 | −8,1 % | 20,8 % |

*(Moyennes des valeurs gravées ; écart relatif = moyenne des `cams/nasa − 1`.)*

Par bande de latitude (écart CAMS − NASA) :

| Bande | Localités | Annuel CAMS | Annuel NASA | Annuel | DJF | JJA |
|---|---:|---:|---:|---:|---:|---:|
| < 6° N | 29 | 0,519 | 0,543 | −0,023 | −0,039 | +0,019 |
| 6 – 7,5° N | 58 | 0,510 | 0,538 | −0,028 | −0,050 | +0,022 |
| 7,5 – 9° N | 29 | 0,477 | 0,509 | −0,032 | −0,059 | +0,010 |
| ≥ 9° N | 26 | 0,425 | 0,476 | **−0,051** | **−0,085** | −0,030 |

Points pilotes (moyennes 2005-2025, CAMS / NASA) :

| Point | Annuel | DJF | JJA |
|---|---:|---:|---:|
| Abidjan | 0,592 / 0,544 | 0,574 / 0,543 | 0,666 / 0,579 |
| Yamoussoukro | 0,511 / 0,545 | 0,463 / 0,522 | 0,613 / 0,590 |
| Korhogo | 0,435 / 0,483 | 0,355 / 0,443 | 0,527 / 0,538 |

**Lecture (constats, pas validation) :**

- **CAMS voit moins de diffus que NASA**, de 0,032 en moyenne annuelle
  (−6,3 %), dans 136 localités sur 142. Les 6 exceptions sont toutes dans le
  sud-est, sous 6° N (Abidjan, Alépé, Sud-Comoé, Aboisso, Sikensi, Agboville).
- **Harmattan : NASA voit nettement plus de diffus** (−0,056 pour CAMS, NASA
  au-dessus dans 94 % des mois), surtout au nord (−0,085 au-delà de 9° N ;
  Korhogo 0,355 contre 0,443). **Mousson : les deux sources se rejoignent**
  en moyenne JJA (+0,009) ; au cœur de la mousson, **CAMS voit plus de diffus**
  (juillet +0,017, août +0,038 ; CAMS au-dessus dans 64 % et 71 % des mois),
  sauf au nord (−0,030 en JJA). L'amplitude saisonnière JJA − DJF de CAMS
  (0,139) vaut presque le double de celle de NASA (0,073).
- **Même gradient nord-sud, plus marqué chez CAMS.** La part diffuse décroît
  vers le nord dans les deux sources (corrélation avec la latitude −0,77 pour
  CAMS, −0,84 pour NASA ; corrélation entre sources des moyennes par localité
  0,91), et l'écart se creuse vers le nord (−0,023 sur le littoral, −0,051 au
  nord ; corrélation de l'écart avec la latitude −0,42). Plages des moyennes
  par localité : CAMS 0,405 (Tengréla) – 0,592 (Abidjan), NASA 0,443 (Folon) –
  0,555 (Adzopé).
- **Maille.** CAMS donne 126 valeurs moyennes distinctes sur 142 localités,
  NASA 35 (maille ~1°, ADR-0015) : CAMS résout un contraste entre le cordon
  littoral (Jacqueville 0,458, Fresco 0,451) et l'arrière-pays immédiat
  (Abidjan 0,592) que NASA ne distingue pas (0,544 à Jacqueville comme à
  Abidjan, même maille). Le plus grand écart est à Fresco (−0,099).
- **Plage de la fiche** (`[0,3 ; 0,6]`, régime tropical) : 8 valeurs annuelles
  CAMS sur 2 982 la dépassent (aucune pour NASA) ; au mensuel, 4 957 valeurs
  CAMS sur 35 784 en sortent (542 sous 0,3, 4 415 au-dessus de 0,6), contre
  2 700 pour NASA. Toutes restent dans `[0, 1]`.
- **Variabilité temporelle partagée en partie.** Anomalies mensuelles (écart
  à la climatologie du mois) corrélées à 0,72 en moyenne par localité (0,60 à
  0,84) ; moyennes nationales annuelles corrélées à 0,52. Continuité à la
  jonction 2020/2021 (moyenne nationale annuelle 2016-2020 → 2021-2025) :
  CAMS 0,483 → 0,487, NASA 0,524 → 0,513 (cohérent avec le DHI NASA −2,4 %,
  ADR-0018).

### Cohérence avec les constats DNI et DHI (ADR-0012, ADR-0013, ADR-0017)

Moyenne des ratios mensuels CAMS / NASA des composantes brutes, mêmes
142 localités et même fenêtre :

| Saison | GHI | DHI | DNI |
|---|---:|---:|---:|
| DJF | +11,0 % | −2,0 % | +50,5 % |
| MAM | +9,6 % | +2,5 % | +59,9 % |
| JJA | +12,0 % | +13,3 % | +77,8 % |
| SON | +11,5 % | +2,3 % | +63,6 % |
| Année | +11,0 % | +4,0 % | +63,0 % |

- **L'écart de fraction diffuse se déduit des écarts déjà gravés.** Avec un GHI
  CAMS supérieur d'environ 11 % et un DHI de 4 à 5 % (médianes ADR-0017 :
  +11,3 % et +5,4 %), la fraction CAMS doit être inférieure d'environ 5 à 6 % :
  c'est ce qu'on observe (−6,3 %).
- **La saisonnalité de l'écart est celle du DHI**, pas celle du GHI (quasi
  constant, +10 à +12 %) : le DHI CAMS passe de −2 % (DJF) à +13 % (JJA) par
  rapport à NASA, comme ADR-0013 l'avait vu aux 3 pilotes (CAMS plus haut en
  mousson, plus bas à Korhogo en saison sèche).
- **NASA aberrant bas du DNI** (ADR-0012, ADR-0017) : une composante directe plus
  faible pour un diffus voisin donne une part diffuse plus forte, ce que montre
  NASA hors mousson. Mais l'écart DNI culmine en JJA (+78 %), quand la fraction
  CAMS rejoint ou dépasse celle de NASA : la fraction diffuse **ne tranche pas**
  la question du DNI, et la fermeture GHI = DHI + DNI·cos θz ne se vérifie pas
  sur des moyennes mensuelles.
- Deux sources ne disent pas qui a raison. L'Harmattan (aérosols désertiques)
  et la mousson (nuages) sont précisément les régimes où les traitements des
  aérosols et des nuages diffèrent entre produits ; **aucune attribution
  physique n'est tranchée ici**. La mesure sol ESMAP/WAPP 2022-2024 (Jalon 4)
  est couverte par les deux séries.

## Conséquences

- Première grandeur dérivée **non-écart** à deux sources : un consommateur doit
  désormais choisir la série (`fraction_diffuse_nasa_power_<localité>` ou
  `fraction_diffuse_cams_<localité>`), la grandeur seule ne suffit plus à
  identifier une valeur.
- Le patron (même formule, même politique, séries par source) vaut pour toute
  grandeur F1 calculable depuis plusieurs sources brutes.
