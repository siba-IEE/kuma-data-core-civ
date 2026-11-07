# ADR-0039 — Ciel clair, irradiation extraterrestre et fiabilité CAMS

Date : 2026-11-07. Statut : accepté — **gravé** (migration 0058).

## Contexte

CAMS Radiation est la source de rayonnement la plus fine de la base : 126
points distincts pour 142 localités, contre 35 pour NASA POWER (ADR-0027). Son
tous ciels est gravé en mensuel (ADR-0011, ADR-0013, ADR-0018, ADR-0037) et en
journalier (ADR-0035).

Les réponses de CAMS contiennent davantage. Chaque ligne donne aussi :
- le **ciel clair** du modèle McClear : GHI, direct horizontal, DHI et DNI
  qu'on recevrait sans nuage, compte tenu des aérosols, de la vapeur d'eau et
  de l'ozone des analyses CAMS ;
- l'**irradiation extraterrestre** sur plan horizontal (`TOA`) ;
- la **fiabilité** (`Reliability`) : part des pas de 15 minutes couverts par
  des images Meteosat fiables.

Seul le tous ciels était gravé. La fiabilité était résumée par l'ingesteur
journalier, sans être gravée.

L'utilisateur a choisi d'approfondir CAMS, en commençant par ces colonnes. Ce
sont des données brutes, en confiance B.

## Décision

1. **Données** : les réponses déjà en cache, sans nouvelle requête.
   - Journalier : `ingest_cams_radiation_journalier.py --ciel-clair`, même
     cache que 0054.
   - Mensuel : `ingest_cams_radiation_mensuel.py --ciel-clair`, même cache que
     la révision (ADR-0037).
   - Colonnes repérées par nom ; le mode normal de l'ingesteur journalier
     régénère toujours les CSV de 0054 à l'octet près.
2. **Cinq grandeurs nouvelles** au référentiel (F1, `stockee`) :

   | Code (id) | Colonne CAMS | Unité |
   |---|---|---|
   | `ghi_ciel_clair` (42) | `Clear sky GHI` | kWh/m²/jour |
   | `dni_ciel_clair` (43) | `Clear sky BNI` | kWh/m²/jour |
   | `dhi_ciel_clair` (44) | `Clear sky DHI` | kWh/m²/jour |
   | `irradiation_extraterrestre` (45) | `TOA` | kWh/m²/jour |
   | `fiabilite_satellite` (46) | `Reliability` | sans unité, 0 à 1 |

   Le direct horizontal par ciel clair n'est pas gravé : il se déduit du DNI.
3. **Conversion** : comme le tous ciels, Wh/m² intégrés sur le pas →
   kWh/m²/jour (÷ 1000, et ÷ nombre de jours du mois en mensuel). La fiabilité
   est gravée telle que servie.
4. **Gravure** (migration 0058), aux 142 localités, 2005-2025, source
   `cams_radiation`, méthode `modele_satellitaire`, confiance B :
   - 710 séries journalières, 5 445 700 mesures, par `COPY` avec l'audit par
     série (ADR-0031) ;
   - 710 séries mensuelles, 178 920 mesures, audit ligne à ligne ;
   - 710 lignes de dégénérescence de pixel, selon la règle de 0042
     (ADR-0027).
5. **Pas de lacune** : McClear ne dépend pas des images Meteosat. CAMS sert le
   ciel clair et l'irradiation extraterrestre les jours où le tous ciels
   manque (2005-01-11 et 12, 2006-01-10 et 11, 2006-09-23 dans 54 localités).

## Résultats

**Cohérence** :
- la moyenne des jours de chaque mois redonne le mensuel à 0,00007
  kWh/m²/jour près (35 784 mois-localités par grandeur) ;
- la fiabilité mensuelle s'écarte de la moyenne des jours d'au plus 0,016 :
  CAMS ne la calcule pas ainsi ;
- le GHI tous ciels mensuel ne dépasse jamais le ciel clair ;
- 126 points distincts pour chaque famille, comme le tous ciels (16 localités
  partagent les coordonnées d'une autre).

**Indice de ciel clair** (tous ciels / ciel clair, mensuel, 2005-2025) :

| | Moyenne | Janvier | Août | Par localité |
|---|---:|---:|---:|---|
| GHI | 0,809 | 0,95 | 0,64 | de 0,706 (Abidjan) à 0,879 (Tengréla) |
| DNI | 0,616 | 0,88 | 0,36 | — |
| DHI | 1,26 | — | — | — |

Les nuages arrêtent 19 % du global et 38 % du direct. Ils augmentent le diffus
de 26 %. Le contraste est saisonnier : ciel presque clair en saison sèche,
mousson d'août très couverte. Il est aussi géographique : la côte est plus
couverte que le nord.

**Ciel clair en Harmattan** : le DNI par ciel clair baisse de décembre à
février, à 5,4 kWh/m²/jour en moyenne contre 7,3 en septembre. Le minimum
mensuel est de 2,94 (Tiapoum, janvier 2007).

La hauteur du soleil n'explique qu'une partie de cette baisse. Rapporté à
l'irradiation extraterrestre, le DNI par ciel clair est au plus bas en février
et mars, quand le soleil est au plus haut :

| Mois | Ciel clair / extraterrestre, DNI | Ciel clair / extraterrestre, GHI | Extraterrestre (kWh/m²/jour) |
|---|---:|---:|---:|
| Janvier | 0,59 | 0,64 | 9,22 |
| Février | 0,55 | 0,64 | 9,84 |
| Mars | 0,53 | 0,65 | 10,34 |
| Septembre | 0,71 | 0,70 | 10,28 |
| Décembre | 0,60 | 0,64 | 8,98 |

C'est l'effet des aérosols de la saison sèche (Harmattan) dans McClear, sans
nuage. Le GHI par ciel clair en souffre moins : ce que les aérosols retirent
au direct revient en partie en diffus.

**Irradiation extraterrestre** : elle redonne l'irradiation calculée pour
`kt` (0041 : Spencer 1971, constante solaire 1361 W/m²) à +0,08 % en moyenne
(de −0,33 % à +0,44 %).

**Fiabilité** :
- journalier : médiane 0,985, et 1 733 jours-localités sous 0,9 sur
  1 089 140 ;
- les jours sans images (lacunes du tous ciels), elle vaut environ 0,52 ;
- mensuel : de 0,959 (Bangolo, janvier 2006) à 0,989.

Les jours où le GHI tous ciels égale le ciel clair (6,2 % des
jours-localités) ont la même fiabilité que les autres (médiane 0,984 contre
0,985) : ce sont des jours sans nuage détecté, pas des jours d'images
manquantes.

**Reproductibilité** :
- régénérer les dix CSV depuis le cache redonne les mêmes octets ;
- l'aller-retour `downgrade`/`upgrade` redonne la même empreinte.

## Conséquences

- L'indice de ciel clair se calcule désormais par source, au jour et au mois,
  aux 142 localités. Il sépare l'effet des nuages de celui des aérosols, ce
  que l'indice de clarté `kt` ne fait pas.
- Le DNI par ciel clair donne une borne haute physique au DNI tous ciels de
  CAMS, et un repère de l'Harmattan pour la salissure.
- La fiabilité qualifie chaque jour CAMS. Un calcul qui exige des jours bien
  observés peut écarter ceux de fiabilité basse.
- Pistes ouvertes :
  - graver l'indice de ciel clair comme grandeur dérivée ;
  - le rayonnement horaire CAMS ;
  - les aérosols CAMS EAC4, qui expliqueraient la baisse du ciel clair en
    Harmattan.
