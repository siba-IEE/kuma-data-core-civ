# ADR-0019 : Météo mensuelle NASA POWER aux 142 localités

Date : 2026-10-15. Statut : accepté — **gravé** (migration 0034).

## Contexte

Le moteur ne porte jusqu'ici que du rayonnement (ADR-0007 à ADR-0018). Les
grandeurs métier en attente — correction thermique du productible, humidex,
degrés-jours, salissure, POA bifacial — demandent la **température**,
l'**humidité relative**, le **vent**, les **précipitations** et l'**albédo**.
Ces six grandeurs existent au référentiel depuis la migration 0002 ; leurs
contrats NASA POWER sont posés dans `seeds/meteo_civ.py` (sondage du
2026-10-15) : périodes alignées sur le GHI (1991-2025, normale OMM 1991-2020
prolongée, ADR-0018), albédo 2001-2025.

## Décision

### Source, contrats et périmètre

| Grandeur | Paramètre NASA | Origine | Unité servie = référentiel | Période | Méthode |
|---|---|---|---|---|---|
| `t2m` | `T2M` | MERRA-2 | °C (`degree_celsius`) | 1991-2025 | `reanalyse` |
| `rh2m` | `RH2M` | MERRA-2 | % (`pourcent`) | 1991-2025 | `reanalyse` |
| `vent_2m` | `WS2M` | MERRA-2 | m/s (`metre_par_seconde`) | 1991-2025 | `reanalyse` |
| `vent_10m` | `WS10M` | MERRA-2 | m/s (`metre_par_seconde`) | 1991-2025 | `reanalyse` |
| `precipitation` | `PRECTOTCORR` | MERRA-2 corrigé | mm/jour (`mm_par_jour`) | 1991-2025 | `reanalyse` |
| `albedo_surface` | `ALLSKY_SRF_ALB` | CERES SYN1deg | sans dimension (`sans_unite`) | 2001-2025 | `modele_satellitaire` |

- **142 localités** (`points_nationaux` : 3 pilotes + 31 régions + 108
  départements), comme le rayonnement mensuel. Source `nasa_power` (id 1),
  confiance **B**, statut `brut`, `granularite='mensuel'`.
- **Aucune conversion** : l'unité servie par NASA (`parameters.<P>.units` :
  `C`, `%`, `m/s`, `mm/day`, `dimensionless`) est celle de la grandeur au
  référentiel. L'ingesteur s'arrête si l'unité servie change ; la migration
  s'arrête si l'unité du référentiel change.
- **Albédo avant 2001** : servi en -999 (18 460 valeurs de remplissage sur les
  142 réponses, toutes avant 2001) — même rupture CERES que le DNI et le DHI
  (ADR-0013). Rien n'est bouché : le contrat commence en 2001.
- **Une seule adaptation des contrats** (`seeds/meteo_civ.py`) : la
  borne de sanité des précipitations mensuelles passe de **50 à 60 mm/jour**,
  pour graver tel quel le mois aberrant de septembre 2022 (voir plus bas). La
  borne a joué son rôle en le révélant ; la valeur n'est ni corrigée ni
  remplacée (même doctrine que le saut ERA5, ADR-0018).

### Seeds, ingesteur, migration

- **Ingesteur** `scripts/ingest_nasa_power_meteo_mensuel.py` : une requête
  `/api/temporal/monthly/point` (communauté `RE`) par localité pour les 6
  paramètres, 4 requêtes simultanées au plus, réponses brutes en cache
  (`--cache`) pour la reprise. Mois 13 (moyenne annuelle) écarté. Garde-fous :
  unité servie, aucune valeur de remplissage dans la période du contrat,
  complétude, bornes, relecture validée. 142 requêtes en ~35 s.
- **Seeds** : 6 CSV gzip `nasa_power_<grandeur>_mensuel_civ142.csv.gz`
  (ADR-0015), 1,56 Mo au total, écriture déterministe (régénération à l'octet
  près vérifiée). Valeurs au centième, telles que servies.
- **Migration 0034** : **852 séries**, **340 800 mesures** (5 × 142 × 420 +
  142 × 300), insérées par `COPY` (~50 s, trigger d'audit compris). Garde-fous :
  identité de la source, unités du référentiel, 142 localités, **aucune série
  préexistante**, comptes par grandeur et total ; `ANALYZE` en fin de migration.
- **Notes publiques** sourcées et datées (paramètre, origine, maille, unité,
  période, date d'extraction). Les mises en garde voyagent avec les données :
  précipitations (mois aberrants), vent à 2 m (effet du couvert forestier),
  albédo (absent avant 2001, pixel littoral).

## Vérifications

| Contrôle | Résultat |
|---|---|
| Valeurs de remplissage dans les périodes gravées | aucune |
| Mensuel = moyenne des jours du journalier NASA (Abidjan, Korhogo, San-Pédro ; 6 paramètres, 7 200 mois) | écart max 0,0050, moyen 0,0024 à 0,0027 : arrondi au centième ; aucun mois au-delà |
| `PRECTOTCORR` mensuel | moyenne journalière en mm/jour, pas un cumul (vérifié contre le journalier) |
| Albédo mensuel | moyenne arithmétique des jours (pas une moyenne pondérée par le rayonnement) |
| HR <= 100 % | 59 640 / 59 640 (max 92,94 %, Danané 1991-08) |
| Vent 10 m >= vent 2 m | 59 640 / 59 640 paires, aucune inversion ni égalité |
| Albédo dans [0,1 ; 0,4] | 41 470 / 42 600 ; 1 130 mois < 0,1 (19 localités), aucun > 0,4 |
| Fidélité base ↔ CSV | intégrale (test) |
| Aller-retour `downgrade 0033` / `upgrade` | empreintes md5 identiques |

Les deux derniers contrôles physiques sont **signalés** par les tests, pas
imposés : ni l'un ni l'autre n'est universel.

## Constats

### Résolution : jumeaux de pixel

| Maille | Grandeurs | Séries distinctes / 111 départements | / 31 régions | / 142 |
|---|---|---:|---:|---:|
| MERRA-2 0,5° × 0,625° | T2M, RH2M, WS2M, WS10M, PRECTOTCORR | 76 | 28 | 77 |
| CERES SYN1deg 1° | albédo (comme le rayonnement NASA, ADR-0015) | 35 | 22 | 35 |

Les cinq paramètres MERRA-2 partagent **exactement la même partition** ; celle
de l'albédo est identique à celle du GHI NASA. 49 départements ont un pixel
MERRA-2 à eux seuls ; les plus gros groupes de jumeaux : Yamoussoukro,
Attiégouakro, Didiévi, Kouassi-Kouassikro, Toumodi (5) ; Man, Biankouma,
Facobly, Kouibly (4). La maille météo est plus fine que la maille solaire de
NASA (0,5° × 0,625° contre 1°), mais reste celle d'une réanalyse : une valeur de
pixel, pas une mesure de station.

### Gradients nationaux

Moyennes 1991-2020 (albédo 2001-2020) sur les 111 départements :

| Grandeur | Min | Max | Moyenne | r (latitude) |
|---|---|---|---:|---:|
| T2M (°C) | 24,29 (Danané) | 27,32 (Téhini) | 26,09 | +0,31 |
| RH2M (%) | 57,9 (Tengréla) | 86,7 (San-Pédro) | 74,6 | **−0,97** |
| Pluie (mm/jour) | 2,47 (Bouna) | 5,09 (Tabou) | 3,66 | −0,62 |
| Pluie (mm/an) | 907 (Bouna) | 1 859 (Tabou) | 1 340 | −0,61 |
| WS2M (m/s) | 0,12 (Issia) | 3,40 (Grand-Bassam) | 1,64 | +0,04 |
| WS10M (m/s) | 0,97 (Issia) | 4,11 (Grand-Bassam) | 2,54 | +0,14 |
| Albédo | 0,078 (Sassandra) | 0,172 (Abidjan) | 0,150 | −0,07 |

**Lecture :**

- L'**humidité** décroît du sud au nord de façon presque linéaire (r = −0,97),
  la **pluie** aussi, plus irrégulièrement (le sud-ouest, Tabou, est le plus
  arrosé ; le nord-est, Bouna, le plus sec).
- La **température moyenne annuelle** varie peu (3 °C d'écart) et dépend
  surtout de l'**altitude du pixel** : T2M ≈ 23,23 + 0,63 × latitude
  − 7,2 °C/km × altitude explique 88 % de la variance (gradient vertical proche
  des 6,5 °C/km standard). Les départements les plus frais sont ceux des monts
  de l'ouest (Danané, 502 m ; Man, 456 m). Le gradient nord-sud est en revanche
  net sur l'**amplitude saisonnière** (de 2,5 °C à Taï à 6,4 °C à Minignan ;
  r = +0,82) et sur la saison chaude (T2M de mars-mai : r = +0,79).
- Le **vent** ne suit pas la latitude : il est le plus fort sur le littoral est
  (Grand-Bassam) et le plus faible sous la forêt du centre-ouest.

### Saisonnalité (moyennes 1991-2020)

| Localité (lat.) | T2M DJF / MAM / JJA (°C) | HR DJF / JJA (%) | Pluie DJF / MAM / JJA / SON (mm/jour) |
|---|---|---|---|
| Abidjan (5,4) | 27,4 / 27,1 / 24,8 | 75,8 / 87,2 | 1,5 / 5,4 / 4,5 / 4,0 |
| Yamoussoukro (6,8) | 27,7 / 27,6 / 25,3 | 56,8 / 83,2 | 1,0 / 4,0 / 4,4 / 3,9 |
| Korhogo (9,4) | 26,3 / 29,1 / 25,8 | 34,9 / 78,6 | 0,2 / 2,4 / 5,2 / 3,1 |
| Tengréla (10,5) | 26,3 / 30,4 / 26,1 | 28,8 / 79,1 | 0,1 / 2,0 / 7,5 / 3,4 |

- **Harmattan (DJF)** : l'humidité de décembre-février tombe à 28,8 % à
  Tengréla contre 83,5 % au sud (r = −0,97 avec la latitude) ; minimum mensuel
  10,28 % (Tengréla, février 2001). Le vent à 10 m culmine en DJF au nord
  (3,6 m/s à Tengréla).
- **Mousson** : régime **unimodal** au nord (pic d'août : 6,7 mm/jour à Korhogo,
  9,7 à Tengréla ; décembre-janvier quasi secs) ; régime **bimodal** au sud
  (pic de juin à 8,6 mm/jour à Abidjan, petite saison sèche d'août à
  1,6 mm/jour, reprise en octobre à 5,5). Le vent du sud culmine en JJA
  (flux de mousson : 4,0 m/s à Abidjan).
- Le mois le plus chaud (climatologie, 111 départements) est **février** (48)
  ou **mars** (58), **avril** pour 5 départements (dont Tengréla, 30,9 °C ;
  record mensuel 33,65 °C, Tengréla, mars 2024). Le plus frais est **août** (63
  départements), **juillet** pour 39 (tous entre 5,8 et 7,7° N), **décembre** à
  l'extrême nord (9, à partir de 9,5° N : Tengréla, Minignan, Odienné…), où
  l'Harmattan l'emporte sur la mousson.

### Variabilité interannuelle

Moyennes nationales annuelles (111 départements) : aucune rupture visible de la
température, qui varie à l'inverse de l'humidité et de la pluie (années sèches
2002-2007 plus chaudes : 2002 à 26,96 °C, 67,7 % ; 1999 à 25,32 °C, 78,2 %). Le
vent à 10 m baisse de 6 % entre 1991-2000 (2,57 m/s) et 2016-2025 (2,42 m/s) :
constat, pas interprétation.

## Anomalies de la source (gravées telles quelles)

**Précipitations, septembre 2022** : dans **30 localités** de l'ouest (21
départements, 9 régions ; latitudes 4,75 à 7,17), septembre 2022 dépasse le
double du plus fort des 34 autres septembres. Au point extrême, San-Pédro,
NASA sert **56,28 mm/jour** (1 688,5 mm dans le mois, dont **726,74 mm le
16 septembre**) ; ERA5 à San-Pédro (archive Open-Meteo, point de la région,
consultée le 2026-10-15) donne **146,8 mm** (4,89 mm/jour, 0,9 mm le 16). La moyenne
nationale de septembre 2022 est de 15,55 mm/jour contre 5,56 pour la normale
1991-2020 ; 2022 devient l'année la plus pluvieuse de la série (4,96 mm/jour).

Autres mois isolés (plus du double du maximum des autres années pour le même
mois) : Ouangolodougou décembre 2025 (11,01 mm/jour contre 0,59 au plus ; ERA5 :
0,38), Kong et Téhini mars 2023 (12,34 et 15,89), Tabou mars 2020 et octobre
2024 (15,67 et 33,07). Seuls San-Pédro (septembre 2022) et Ouangolodougou
(décembre 2025) ont été recoupés avec ERA5 : le quota quotidien de l'archive a
borné les contrôles.

**Hypothèse** : artefacts de la correction de `PRECTOTCORR` par les analyses
pluviométriques. **Non établi ; valeurs non corrigées.** Les 142 notes publiques
de précipitations portent la mise en garde. Les climatologies 1991-2020 ne sont
pas touchées (septembre 2022 est hors normale) ; les années 2022-2025 sont à lire
avec ce caveat.

**Vent à 2 m sous forêt** : le rapport WS2M / WS10M (moyennes 1991-2020) vaut
0,66 en médiane, 0,83 sur le littoral (Grand-Bassam), mais descend à **0,12 à
Issia**, 0,26 à Zoukougbeu, 0,31 à Danané ; 15 localités de l'ouest forestier
et montagneux (Daloa, Soubré, Taï, Man…) sont sous 0,5. C'est l'effet du couvert végétal dans la réanalyse
(hauteur de déplacement), pas une mesure : pour un modèle thermique de module,
le vent à 10 m est le plus robuste.

**Albédo littoral** : Sassandra et les régions de San-Pédro et du Gbôklé
partagent un pixel CERES dont l'albédo vaut 0,078 en moyenne (0,06 à 0,11 ; 270
mois sur 300 sous 0,1), contre 0,148 sur les 142 localités, vraisemblablement
par la part d'océan dans le pixel de 1° ; le département de San-Pédro (5,0° N),
dans le pixel voisin, est à 0,158. Les monts de l'ouest (Danané, Man) descendent
aussi sous 0,1 certains mois. Le maximum (0,34, Ouellé, août 2019) reste dans la
plage usuelle.

## Conséquences

- Les grandeurs métier mensuelles (correction thermique, humidex, degrés-jours,
  POA avec albédo) deviennent calculables aux 142 localités, sur la fenêtre des
  mesures sol ESMAP (2022-2024) comprise.
- **Contrat partagé** : les bornes des précipitations de `meteo_civ.py` sont
  portées à 60 mm/jour (mensuel) et 1000 mm/jour (journalier, pour le jour du
  16/09/2022 à San-Pédro, 726,74 mm), de sorte que le mensuel et le journalier
  gravent le même artefact tel quel.
- Pour la pluie à l'échelle d'un événement (salissure), MERRA-2 corrigé reste
  une source de comparaison : un produit pluviométrique satellitaire (IMERG,
  CHIRPS) serait une source à évaluer.
