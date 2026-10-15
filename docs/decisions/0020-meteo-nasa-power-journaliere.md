# ADR-0020 : Météo journalière NASA POWER — lot « pilotes + régions »

Date : 2026-10-15. Statut : accepté — **gravé** (migration 0035).

## Contexte

Les grandeurs métier de l'API lisent des **séries compagnes journalières** de
la série GHI appelante : température (correction thermique NOCT, PR fourni et
PR réaliste, énergie utile ECS), précipitation (proxy de salissure HSU, PR
réaliste), albédo de surface (POA bifacial) ; les degrés-jours de climatisation
lisent directement une série T2M, et le service `humidex` croise T2M et
humidité. Sans ces séries, l'API répond 400 (`INCOMPATIBILITE_SOURCE_GRANDEUR`)
ou se replie sur un albédo constant.

Les contrats ont été préparés dans `seeds/meteo_civ.py` (sondage du
2026-10-15) : grandeurs déjà au référentiel (0002), périodes alignées sur le GHI
(1991-2025, albédo 2001-2025), journalier aux **34 localités** de l'ADR-0016
(3 pilotes + 31 régions), confiance B.

## Décision

| Grandeur | Paramètre NASA | Produit | Méthode | Unité | Période | Mesures |
|---|---|---|---|---|---|---:|
| `t2m` | `T2M` | MERRA-2 | `reanalyse` | °C | 1991-2025 | 434 656 |
| `rh2m` | `RH2M` | MERRA-2 | `reanalyse` | % | 1991-2025 | 434 656 |
| `vent_2m` | `WS2M` | MERRA-2 | `reanalyse` | m/s | 1991-2025 | 434 656 |
| `vent_10m` | `WS10M` | MERRA-2 | `reanalyse` | m/s | 1991-2025 | 434 656 |
| `precipitation` | `PRECTOTCORR` | MERRA-2 | `reanalyse` | mm/jour | 1991-2025 | 434 656 |
| `albedo_surface` | `ALLSKY_SRF_ALB` | CERES SYN1deg | `modele_satellitaire` | sans dimension | 2001-2025 | 310 454 |

- **204 séries** (`granularite='journalier'`, source `nasa_power` id 1,
  confiance B) et **2 483 734 mesures** dans `mesures_ressource`.
- **Unités** : l'unité servie par NASA POWER (`C`, `%`, `m/s`, `mm/day`,
  `dimensionless`) est celle de la grandeur au référentiel (`degree_celsius`,
  `pourcent`, `metre_par_seconde`, `mm_par_jour`, `sans_unite`) : aucune
  conversion. L'ingesteur refuse une autre unité servie ; la migration refuse
  une autre unité au référentiel.
- **Seeds** : CSV gzip (ADR-0015), un fichier par grandeur
  (`nasa_power_<grandeur>_journalier_pilotes_regions.csv.gz`, 11 Mo au total),
  écriture déterministe (régénération identique à l'octet, vérifiée) et
  relecture validée. Ingesteur `scripts/ingest_nasa_power_meteo_journalier.py` :
  une requête par point pour les 6 paramètres (34 requêtes, 4 simultanées,
  une quarantaine de secondes écriture comprise), option `--cache`.
- **Valeurs de remplissage** : l'ingesteur n'écrit pas une grandeur dont la
  période contient une valeur de remplissage (complétude stricte impossible,
  rien n'est bouché) et rapporte leur répartition. Constat : **aucune** dans les
  périodes gravées, albédo compris. Avant 2001, l'albédo est intégralement en
  valeur de remplissage (3 653 jours par point), d'où son contrat 2001-2025.
- **Migration 0035** : insertion par `COPY`, trigger d'audit par ligne actif.
  Garde-fous : identité de la source, unités du référentiel, 34 localités,
  **aucune série préexistante** (même code, ou série journalière NASA de même
  grandeur et localité, qui rendrait ambiguë la résolution des compagnes),
  34 séries et nombre de mesures par grandeur, total ; `ANALYZE` en fin de
  migration. `downgrade` supprime mesures puis séries. Durées mesurées, trigger
  d'audit compris et en concurrence avec d'autres chargements : 5 à 6 min pour
  l'upgrade, 2 à 3 min pour le downgrade. Chaque mesure insérée ou supprimée
  écrit une ligne de journal d'audit : prévoir quelques Go de disque par
  passage (voir « Coût disque » plus bas).

### Pluie : bornes relevées, valeurs aberrantes gravées telles quelles

NASA POWER sert **726,74 mm** le 2022-09-16 à San-Pédro et **710,75 mm** le
même jour à Gbôklé, au-delà de la borne de sanité initiale de 500 mm/jour ; la
moyenne de septembre 2022 à San-Pédro (56,28 mm/jour) dépasse aussi la borne
mensuelle initiale de 50. Décision d'intégration (2026-10-15), même doctrine
que pour le saut ERA5 (ADR-0018) : **on grave tel quel, avec une mise en
garde**. Les bornes de la pluie dans `seeds/meteo_civ.py` passent à
**60 mm/jour en mensuel** et **1000 mm/jour en journalier** ; aucune valeur
n'est corrigée ni écartée (voir « Pluie : valeurs aberrantes » plus bas).

### La mise en garde voyage avec les données

La note publique des 34 séries de pluie porte une mise en garde sourcée :
valeurs aberrantes probables servies par NASA POWER et non corrigées, jours
extrêmes de septembre 2022 dans l'ouest, pluie du 2025-12-02 au nord en saison
sèche, fortes pluies plus fréquentes depuis 2017, recoupement avec ERA5
recommandé (métadonnée seulement, comme la migration 0033 pour ERA5). Un test
vérifie que les jours au-delà de 200 mm de la base sont exactement ceux que la
note cite.

## Compatibilité avec l'API

Vérifiée par test (`test_series_resolues_comme_compagnes_par_l_api`), sans
modifier l'API, depuis les 34 séries GHI journalières NASA (1991-2025) :

| Résolveur | Filtre | Résultat |
|---|---|---|
| `_chercher_serie_compagne` (T2M, RH2M, vents, pluie) | même localité, source, `periode_debut` (1991-01-01) et granularité que le GHI | série trouvée aux 34 points |
| `_resoudre_serie_albedo_journalier` | `albedo_surface`, journalier, même localité et source | série trouvée aux 34 points |
| `_chercher_serie_pluie_nasa` (salissure) | pluie journalière `nasa_power` recouvrant la fenêtre des PM (2021-01 → 2025-08) | série trouvée aux 34 points |

*Révisé par l'ADR-0033 : la salissure et le PR réaliste prennent désormais la pluie
journalière GPM IMERG (`_chercher_serie_pluie_salissure`), jamais celle de NASA POWER
(ADR-0032).*

Le GHI, la T2M et la pluie partagent le même `periode_debut` : c'est ce qui
rend la recherche stricte de compagne possible. Une série DNI ou DHI (2001)
n'a pas de compagne T2M de même début, sans conséquence : les endpoints
concernés exigent une série GHI.

## Vérifications

| Contrôle | Résultat |
|---|---|
| Valeurs de remplissage dans les périodes gravées | aucune (2 483 734 valeurs) |
| Moyenne des jours du mois vs endpoint mensuel NASA (34 localités, 6 grandeurs, 81 600 mois) | écart max 0,005 = arrondi à 2 décimales du mensuel servi |
| Humidité relative | max 97,47 % (≤ 100) |
| Pluie | min 0 (≥ 0) |
| Vent à 10 m > vent à 2 m | tous les jours (434 656 paires), rapport moyen 1,63 |
| Fidélité base ↔ CSV | intégrale (test) |
| Aller-retour `downgrade 0033` / `upgrade head` | état 0033 restauré à l'identique, puis état 0035 identique (empreintes md5) |
| Deux téléchargements successifs de la source | 2 607 936 valeurs identiques |

## Constats

### Maille

Sur 34 localités, **29 séries distinctes** pour chaque grandeur MERRA-2 (maille
0,5° × 0,625°) et **22** pour l'albédo (maille CERES d'environ 1°, comme le
rayonnement, ADR-0015). Les doublons sont un fait de la source, gravés tels
quels.

### Climatologie 1991-2020 (albédo 2001-2020), moyenne des localités

| Grandeur | National | Min (localité) | Max (localité) | Corrélation avec la latitude |
|---|---:|---|---|---:|
| T2M (°C) | 26,14 | 24,49 (Tonkpi) | 27,28 (Bounkani) | +0,44 |
| RH2M (%) | 74,5 | 59,5 (Bounkani) | 86,7 (San-Pédro) | −0,97 |
| Vent 2 m (m/s) | 1,67 | 0,57 (Nawa) | 2,45 (Abidjan) | +0,13 |
| Vent 10 m (m/s) | 2,58 | 1,38 (Nawa) | 3,36 (Abidjan) | +0,22 |
| Pluie (mm/an) | 1317 | 907 (Bounkani) | 1843 (San-Pédro) | −0,73 |
| Albédo | 0,146 | 0,078 (Gbôklé) | 0,172 (Abidjan) | +0,26 |

### Saisonnalité (moyennes mensuelles 1991-2020)

| | Jan | Fév | Mar | Avr | Mai | Juin | Juil | Août | Sep | Oct | Nov | Déc |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| T2M nord (°C) | 25,4 | 27,9 | **29,6** | 29,4 | 28,4 | 27,0 | 25,5 | 24,7 | 25,0 | 26,0 | 26,3 | 25,0 |
| T2M sud (°C) | 26,7 | **27,3** | 27,1 | 26,7 | 26,3 | 25,3 | 24,4 | 24,2 | 24,8 | 25,4 | 26,2 | 26,4 |
| RH2M nord (%) | **32** | 32 | 46 | 61 | 68 | 73 | 79 | 84 | 83 | 78 | 62 | 43 |
| RH2M sud (%) | 74 | 77 | 82 | 85 | 87 | 88 | 87 | 85 | 86 | 86 | 84 | 79 |
| Pluie nord (mm/j) | 0,1 | 0,5 | 1,4 | 2,6 | 3,1 | 4,2 | 5,3 | **7,1** | 5,7 | 3,2 | 0,6 | 0,1 |
| Pluie sud (mm/j) | 0,9 | 2,2 | 4,0 | 5,1 | 6,6 | **9,2** | 4,0 | 2,6 | 4,3 | 5,8 | 3,3 | 1,6 |

(Nord : 7 localités au-delà de 8,5° N ; sud : 7 localités en deçà de 6° N.)

Le nord a un régime de mousson **unimodal** (pic de pluie en août ; harmattan
sec de décembre à février, humidité de 32 % en janvier-février ; plus forte
chaleur en mars) ; le sud est **bimodal** (grande saison des pluies en juin,
petite en octobre, petite saison sèche en août) et humide toute l'année. Le vent est le plus fort
en saison sèche au nord (harmattan) et en juillet-août au sud (mousson).
L'albédo varie peu (0,13 à 0,17 en moyenne mensuelle).

### Extrêmes et fréquences

- **T2M** : maximum journalier 35,36 °C le 2024-03-18 (Korhogo et Poro),
  minimum 16,93 °C le 2016-01-06 (Folon). 1 463 jours-localités au-dessus de
  32 °C, dont 379 dans le Bounkani.
- **Humidité** : 6,0 % des jours-localités au-dessus de 90 % (Tonkpi 15,8 %,
  San-Pédro 14,7 %, Nawa 14,1 % ; Tchologo, Bounkani, Korhogo et Poro autour de
  1 %). 5 069 jours-localités sous 20 %, presque tous de décembre à mars ;
  minimum 6,42 % (Bounkani, 2007-03-09).
- **Vent** : maximum 5,32 m/s à 2 m et 7,29 m/s à 10 m (Bounkani, 1992-01-24).
- **Albédo** : 0,01 à 0,40 ; 5 jours sous 0,05, tous dans le Tonkpi.

### Pluie : valeurs aberrantes

Les **5 seuls jours au-delà de 200 mm** de 1991-2025 (34 localités) tombent
tous en **septembre 2022, dans l'ouest et le sud-ouest** :

| Localité | Date | Pluie (mm) |
|---|---|---:|
| San-Pédro | 2022-09-16 | 726,74 |
| Gbôklé | 2022-09-16 | 710,75 |
| Guémon | 2022-09-23 | 329,59 |
| Cavally | 2022-09-23 | 329,59 |
| Nawa | 2022-09-23 | 248,92 |

Les quatre premiers sont les seuls jours au-delà de 300 mm. Le jour suivant au
classement plafonne à 191,22 mm (Bafing, 2022-08-20). Septembre 2022 est le
septembre le plus pluvieux de 1991-2025 dans **23 des 34 localités**. Rapporté à
la moyenne des septembres 1991-2020, l'excès est centré sur le sud-ouest
(× 10,0 à Gbôklé, × 8,7 à San-Pédro, × 5,7 dans la Nawa, × 4,8 au Guémon et au
Cavally), plus modéré à l'extrême ouest (× 2,9 dans le Tonkpi, × 2,4 dans le
Folon) et absent au sud-est (× 1,0 à 1,2 à Abidjan, dans La Mé,
l'Agnéby-Tiassa et l'Indénié-Djuablin).

Autre cas, au nord en pleine saison sèche : le **2025-12-02**, 84,12 mm dans le
Tchologo, 41,28 en Bagoué, 25,92 à Korhogo et dans le Poro (moyenne de décembre
1991-2020 : environ 0,1 mm/jour). Ces valeurs sont des faits de la source, non
recoupés ici avec une autre source : à vérifier avec ERA5 avant tout usage des
fortes pluies.

### Pluie : rupture de distribution vers 2017

| Période (34 localités) | Jours > 50 mm par an | 99,9e centile (mm) | Jours ≥ 1 mm par an et localité | Jours ≥ 5 mm par an et localité | Cumul (mm/an et localité) |
|---|---:|---:|---:|---:|---:|
| 1991-2015 | 4,4 | 39,7 | 239,6 | 86,8 | 1281 |
| 2016 | 21 | — | — | — | — |
| 2017-2025 | 55,6 | 86,5 | 230,2 | 92,2 | 1530 |

Aucun jour au-delà de 100 mm avant le 2015-06-04 ; 64 depuis, dont les deux
valeurs au-delà de 700 mm (2022-09-16). Le nombre de jours de pluie change
peu : c'est l'**intensité des fortes pluies** qui augmente brutalement, et
dans **les 34 localités** sans exception (de 0 à 0,84 jour > 50 mm par an en
1991-2015, de 0,56 à 5,33 en 2017-2025 ; Tonkpi et San-Pédro en tête). Hypothèse
la plus probable : un changement dans les observations qui corrigent la pluie
MERRA-2 (`PRECTOTCORR`), plutôt qu'un signal climatique. **Non établi ; les
valeurs ne sont pas corrigées.** Pour le proxy de salissure, le nombre de jours
nettoyants varie peu (−4 % au seuil par défaut de 1 mm, +6 % à 5 mm) ; les
cumuls et les fortes pluies postérieurs à 2016 sont à lire avec cette mise en
garde.

### Continuité 2020/2021

Moyennes des 34 localités, 2016-2020 → 2021-2025, et variabilité
interannuelle 2005-2020 (coefficient de variation des moyennes annuelles) :
T2M +0,8 % (1,0 %), RH2M +0,3 % (3,0 %), vents −0,9 % (≈ 4 %), pluie +2,6 %
(12,9 %), albédo −2,1 % (1,7 %). Pas de saut comparable à celui d'ERA5
(ADR-0018) ; l'albédo baisse un peu plus que sa variabilité, constat sans
interprétation.

## Coût disque

Mesuré sur la base de travail : ≈ 250 octets par mesure dans
`mesures_ressource` (index compris), soit ≈ 0,6 Go pour la migration, et
≈ 0,85 Ko de journal d'audit par ligne insérée **ou supprimée**, soit ≈ 2 Go par
`upgrade` comme par `downgrade`. Sept passages (upgrade, aller-retour,
réapplications) ont porté le journal d'audit de la base de travail à 14 Go. La
base passe d'environ 1,06 M à 3,54 M mesures journalières : toute nouvelle
série journalière de ce volume doit prévoir cet espace, en CI comme en
production.

## Conséquences

- Correction thermique, degrés-jours, PR réaliste, salissure, humidex et POA
  bifacial deviennent calculables aux 34 points avec des données de la base,
  sur 1991-2025 (albédo réel à partir de 2001).
- La pluie NASA POWER journalière est utilisable pour le nombre de jours
  nettoyants (salissure), mais ses fortes pluies et ses cumuls, surtout après
  2016, doivent être recoupés (ERA5) avant d'être interprétés.
- La météo journalière des 108 départements reste possible au même format si
  le besoin justifie le volume (≈ 7,9 M lignes de plus).
