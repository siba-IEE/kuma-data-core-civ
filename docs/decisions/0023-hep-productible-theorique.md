# ADR-0023 : Heures équivalentes pleines et productible spécifique théorique sur tout le territoire

Date : 2026-10-15. Statut : accepté — **gravé** (migration 0038).

## Contexte

Deux grandeurs F1 `stockee` sont seedées depuis 0002 avec leurs fiches
méthodologiques héritées de l'instance Guinée :

- `hep` (id 1, unité `heure_equivalente_pleine`) —
  `docs/methodologie/grandeurs/hep.md` : `HEP_jour(t) := GHI_jour(t)` (convention
  STC 1 kWh/m² ↔ 1 h_eq à 1 kW/m²), sommée sur les jours du mois et de l'année,
  depuis le GHI **journalier** NASA POWER, avec une complétude stricte (tous les
  jours civils) ;
- `productible_specifique_theorique` (id 4, unité `kwh_par_kwc_periode`) —
  `productible_specifique_theorique.md` : `HEP × 0,8` (PR théorique fixe), annuel
  et mensuel, calculé depuis les lignes `hep` déjà gravées.

L'instance CIV porte le GHI **mensuel** (moyenne journalière du mois) des 4
sources aux 142 localités (ADR-0015, ADR-0018), et le GHI journalier NASA
seulement aux 34 localités du lot journalier (ADR-0016). Le référentiel contient
aussi `productible_mensuel` (id 6, unité `kwh_par_kwc_mois`) : il fallait
trancher où vont les lignes mensuelles du productible.

## Décision

### Formule de la fiche, depuis le mensuel — version 1

```
HEP_mensuel(a, m) := Σ_{t ∈ jours(a, m)} GHI(t) = GHI_mois(a, m) × n_jours(a, m)
HEP_annuel(a)     := Σ_{m=1..12} HEP_mensuel(a, m)        (années complètes seulement)
PST(période)      := HEP(période) × 0,8                   (mensuel et annuel)
```

Sur les jours d'un mois, la somme des GHI journaliers vaut le nombre de jours
fois leur moyenne : la formule de la fiche est **inchangée** (`version_formule =
1`), seule l'entrée change de grain — même raisonnement que la fraction diffuse
(ADR-0014). La complétude stricte s'applique au grain mensuel : une ligne
mensuelle par mesure mensuelle gravée, une ligne annuelle seulement si les 12
mois existent. Les séries mensuelles des 4 sources sont complètes et sans valeur
de remplissage ; aucune année n'est écartée.

### Équivalence avec la définition journalière héritée (vérifiée)

Aux 34 localités du journalier NASA, 1991-2025, la fonction de la fiche
(`services/grandeurs/hep.py`, `_agreger_hep_journaliers`, complétude stricte des
jours civils) appliquée au GHI journalier des CSV, comparée au HEP NASA gravé
depuis le mensuel :

| Contrôle | Périodes | Écart max | Écart moyen | Écart relatif max |
|---|---:|---:|---:|---:|
| HEP mensuel | 14 280 mois | 0,0053 h_eq (Gontougo, mai 2001) | 0,0019 h_eq | 4,6·10⁻⁵ |
| HEP annuel | 1 190 années | 0,025 h_eq (Bounkani, 2013) | 0,0064 h_eq | 1,4·10⁻⁵ |

Aucun biais (écart signé moyen +0,00002 h_eq par mois). L'écart est celui de
l'arrondi déjà mesuré entre la moyenne des jours NASA et le mensuel NASA
(≤ 0,00017 kWh/m²/jour, ADR-0016), multiplié par le nombre de jours. Le test
d'intégration l'exige sous 2·10⁻⁴ h_eq par jour de la période, sur toutes les
périodes.

### Mensuel du productible : `productible_specifique_theorique`, pas `productible_mensuel`

Les lignes mensuelles du productible sont gravées sous
`productible_specifique_theorique`, `periode_type = 'mensuel'`. Trois raisons :

1. **Le code et la fiche hérités** : le service
   `calculer_et_inserer_productible_specifique_theorique` recopie toutes les
   lignes `hep` courantes, annuelles **et** mensuelles, multipliées par le PR, sous
   la même grandeur (il compte `nb_mensuel_insere`) ; la fiche expose « annuel +
   mensuel (héritées de `hep` amont) ».
2. **L'unité** : `kwh_par_kwc_periode` (id 160) est définie comme le total « sur
   la période de la mesure (mensuelle ou annuelle) », introduite précisément pour
   corriger l'étiquette de `productible_specifique_theorique`. `kwh_par_kwc_mois`
   ne peut pas porter une valeur annuelle.
3. **Le référentiel** : `productible_mensuel` est **désactivée** (`actif =
   false`, `desactive_le` renseigné dès 0002) et n'a aucune série. La réactiver
   doublonnerait la ligne mensuelle du productible sous un second code, alors que
   l'identité de `grandeurs_metier` distingue déjà mensuel et annuel par
   `periode_type`.

### Séries : une par (grandeur, source, localité)

Le HEP est un GHI pondéré par les jours : il hérite du désaccord entre sources,
qui est le savoir que ce moteur trace (ADR-0009). Aucune source n'est donc
désignée « la » source du HEP ; chacune a sa série.

| Source | Jeton | Période | Lignes par localité et par grandeur |
|---|---|---|---:|
| NASA POWER | `nasa_power` | 1991-2025 | 420 + 35 |
| CAMS | `cams` | 2005-2025 | 252 + 21 |
| SARAH-3 | `sarah3` | 2005-2023 | 228 + 19 |
| ERA5 | `era5` | 2005-2023 | 228 + 19 |

- Codes `hep_<jeton>_<localité>` et
  `productible_specifique_theorique_<jeton>_<localité>`, sur le modèle de
  `fraction_diffuse_nasa_power_<localité>` ; source `kuma_calculs`,
  `calcul_derive`, `granularite` NULL.
- **1 136 séries**, **173 524 lignes** par grandeur, **347 048** au total.
  Confiance **B** (règle R4, et `min(B, B)` des entrées), statut `brut`.
- Les 284 séries dérivées d'ERA5 portent la mise en garde du saut de 2021, même
  phrase que la migration 0033 (ADR-0018).

### Calcul et garde-fous

Calcul **hors-ligne, en SQL, dans la migration**, par jointure sur les séries GHI
mensuelles désignées **par leur code** (les séries journalières NASA, qui
partagent localité, source et grandeur, ne peuvent pas s'y glisser). Le
productible se calcule depuis les lignes `hep` gravées : sa complétude est
héritée par construction, comme dans la chaîne de la fiche.

Produits et sommes en `numeric` : les GHI gravés (4 décimales) sont relus
exactement, le résultat est arrondi une seule fois en `float8`. Les valeurs sont
donc reproductibles au bit près et le test les compare **à l'égalité stricte** à
un recalcul indépendant en décimal exact depuis les seeds et CSV. Un aller-retour
0038 → 0033 → 0038 redonne la même empreinte (valeurs comparées bit à bit), et
l'état 0033 intermédiaire est identique à l'original.

Garde-fous : grandeurs actives en version 1 avec leur unité ; aucune série ni
ligne préexistante ; chaque série amont complète (12 mois × années de la source,
mesures courantes) ; comptes exacts par (grandeur, source, période) et total ;
domaine `0 < HEP ≤ 12 h_eq par jour de la période` (au-delà du rayonnement
extraterrestre) ; Σ des 12 mois = annuel. `ANALYZE` avant le calcul et en fin
de migration. Durée mesurée : environ 1 min 30, dont l'essentiel tient à
l'index d'exclusion GiST et au trigger d'audit (≈ 250 µs par ligne).

## Résultat — 142 localités

HEP annuel moyen par localité sur la période de chaque source, puis distribution
nationale (h_eq/an ; productible = HEP × 0,8, kWh/kWc/an) :

| Source | Période | Moyenne nationale | Min (localité) | Max (localité) | PST moyen | PST min – max |
|---|---|---:|---|---|---:|---:|
| NASA POWER | 1991-2025 | 1 772 | 1 648 (Divo, Fresco, Grand-Lahou, Guitry, Lakota, Lôh-Djiboua) | 2 066 (Folon, Minignan) | 1 418 | 1 318 – 1 653 |
| CAMS | 2005-2025 | 1 957 | 1 687 (Abidjan) | 2 171 (Tengréla) | 1 566 | 1 350 – 1 737 |
| SARAH-3 | 2005-2023 | 2 001 | 1 808 (Alépé) | 2 204 (Tengréla) | 1 601 | 1 447 – 1 763 |
| ERA5 | 2005-2023 | 1 794 | 1 597 (Guéyo) | 2 093 (Tengréla) | 1 435 | 1 278 – 1 674 |

Les ex aequo NASA sont des localités du même pixel (~1°, 35 valeurs distinctes
sur 142, ADR-0015). Sur la fenêtre commune 2005-2023, NASA donne 1 768 (1 640 –
2 060) ; les autres sources sont inchangées à 2 h_eq près. Extrêmes
(localité, année) : 1 527 h_eq (ERA5, Aboisso 2014) et 2 247 h_eq (SARAH-3,
Tengréla 2015).

**Écart à NASA** (moyenne par localité, 2005-2023) : SARAH-3 +13,4 % (+6,1 à
+24,1 %), CAMS +10,8 % (−0,7 à +19,1 %), ERA5 +1,5 % (−4,4 à +10,5 %) — du
même ordre que les écarts GHI mensuels d'ADR-0017 (médianes +13,5 / +11,3 /
+0,6 % sur 2005-2020), puisque le HEP est un GHI pondéré par les jours.

**Dispersion inter-source par localité** (2005-2023, `(max − min) / moyenne` des
4 sources) : de **6,2 %** (M'Bengué) à **21,5 %** (Fresco), médiane 13,5 %
(quartiles 10,3 – 15,8 %), 51 localités au-delà de 15 %. Corrélation avec la
latitude −0,68 : 14,8 % en moyenne au sud de 6° N (29 localités), 9,4 % au nord
de 9° N (26). SARAH-3 est la source la plus haute dans 140 localités sur 142 ; la
plus basse est NASA (88) ou ERA5 (53). CAMS et SARAH-3 seuls ne s'écartent que de
2,1 % en médiane (7,3 % au plus) : la dispersion vient surtout de NASA et d'ERA5,
plus bas. Exemple : à Fresco, le productible théorique va de 1 312 (NASA) à
1 628 kWh/kWc/an (SARAH-3).

**Gradient nord-sud** (2005-2023, HEP annuel moyen par bande de latitude) :

| Source | < 6° N (29) | 6-8° N (71) | 8-9° N (16) | ≥ 9° N (26) | Nord / sud | Pente | Corrélation |
|---|---:|---:|---:|---:|---:|---:|---:|
| NASA POWER | 1 680 | 1 707 | 1 879 | 1 962 | +16,8 % | 70 h_eq/° | 0,87 |
| CAMS | 1 863 | 1 924 | 2 015 | 2 117 | +13,6 % | 58 h_eq/° | 0,84 |
| SARAH-3 | 1 931 | 1 963 | 2 048 | 2 153 | +11,5 % | 51 h_eq/° | 0,80 |
| ERA5 | 1 717 | 1 719 | 1 879 | 2 031 | +18,3 % | 79 h_eq/° | 0,82 |

**Années extrêmes** (moyenne nationale du HEP annuel) :

| Source | Année la plus basse | Année la plus haute | Amplitude | Variabilité interannuelle |
|---|---|---|---:|---:|
| NASA POWER (1991-2025) | 2005 (1 729) | 1994 (1 827) | 5,7 % | 1,2 % |
| CAMS (2005-2025) | 2009 (1 908) | 2021 (2 016) | 5,7 % | 1,4 % |
| SARAH-3 (2005-2023) | 2009 (1 920) | 2021 (2 039) | 6,2 % | 1,3 % |
| ERA5 (2005-2023) | 2014 (1 753) | 2021 (1 849) | 5,5 % | 1,7 % |

Sur 2005-2023, l'année la plus haute de NASA est 2008 (1 803) ; 2021 n'y est pas
extrême (1 790). Moyenne nationale 2021-2023 par rapport à 2016-2020 : ERA5
+3,5 %, CAMS +1,2 %, SARAH-3 +0,6 %, NASA +0,2 % — le saut ERA5 d'ADR-0018 se
retrouve tel quel dans le HEP, et ses trois dernières années (1 849, 1 844,
1 847) dépassent toutes son maximum 2005-2020 (1 822).

**Lecture (constats, pas validation) :**

- Le HEP n'ajoute pas d'information physique au GHI ; il le traduit en unité
  d'ingénieur. Le désaccord des sources devient un désaccord de productible :
  **13,5 % en médiane, plus de 20 % dans le sud-ouest et sur le littoral**
  (Fresco, Grand-Lahou, Taï). Dans le sud, le productible théorique est une
  fourchette, pas une valeur.
- Le gradient sud → nord du rayonnement (ADR-0015) donne au nord 11 à 18 % de
  HEP de plus qu'au sud, selon la source ; c'est au nord que les sources
  s'accordent le mieux.
- La plage « typique » de la fiche héritée ([1 700 ; 2 100] h_eq/an, Guinée) ne
  se transpose pas : 2 688 des 13 348 valeurs annuelles sont en dessous (NASA
  1 833, ERA5 839) et 970 au-dessus (SARAH-3 526, CAMS 411). Le garde-fou de la
  migration est donc physique, pas climatologique.
- Le productible reste théorique : plan horizontal, PR fixe 0,8, sans correction
  thermique ni salissure — une borne de référence, pas un productible garanti.

## Réalisation

- Migration **0038** (`2026_10_15_0038_hep_productible_theorique.py`), aucun seed
  ni réseau.
- Tests `tests/integration/db/test_grandeur_hep_productible_seed.py` : contrat
  (grandeurs, `productible_mensuel` inactive et vide, séries, mise en garde ERA5
  relue sur la série brute), complétude et domaine, fidélité au bit près par
  recalcul indépendant, somme des 12 mois = annuel, équivalence avec le
  journalier hérité.
- `test_extension_2025_seed.py::test_mise_en_garde_era5` attend désormais les 852
  séries annotées (568 de 0033 et 284 de 0038).

## Conséquences

- Premières grandeurs de productivité de l'instance, à toutes les localités et
  aux 4 sources : le productible théorique se compare d'une source à l'autre
  comme le rayonnement.
- Cohérence structurelle : toute correction d'un GHI mensuel impose de régénérer
  HEP et productible par une nouvelle migration, jamais à la main. Le
  prolongement de SARAH-3 et ERA5 au-delà de 2023 suivra le même contrat.
- Restent à traiter : la description de `productible_specifique_theorique` au
  référentiel dit encore « journalier » (étiquette héritée, valeurs par
  période) ; les fiches `hep.md` et `productible_specifique_theorique.md`
  décrivent le périmètre guinéen ; le passage au plan incliné (`poa_parametrable`)
  et le PR fourni par l'utilisateur relèvent des grandeurs F2.
