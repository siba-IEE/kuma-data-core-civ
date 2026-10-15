# ADR-0032 — Pluie journalière : recoupement de NASA POWER avec ERA5, CHIRPS et IMERG

Date : 2026-10-15. Statut : accepté — **gravé** (migrations 0050-0051).

## Contexte

La pluie NASA POWER (`PRECTOTCORR`) est gravée en mensuel aux 142 localités
(0034) et en journalier aux 142 localités (0035 pour 34, 0047 pour 108). Deux
anomalies y avaient été relevées sans cause établie (ADR-0020, ADR-0031) :

- **des jours extrêmes improbables** : 726,74 mm à San-Pédro le 2022-09-16,
  20 jours au-delà de 200 mm aux 108 départements (25 jours-localités aux 142
  localités), dont 15 en
  septembre 2022, et Ouangolodougou 321,59 mm le 2025-12-02 en saison sèche ;
- **une rupture vers 2016-2017** : de 16,1 jours > 50 mm par an (1991-2015) à
  192,0 (2017-2025) aux 108 départements, soit ×11,9, sans hausse du nombre de
  jours de pluie.

Ces séries alimentent le proxy de salissure et le PR réaliste de l'API, qui
dépendent des épisodes de pluie journaliers.

## Décision

1. **Graver une deuxième source journalière** : la pluie ERA5 du CDS Copernicus
   aux 142 localités, 1991-2025 (migration 0050), au même point de grille que
   la pluie ERA5 mensuelle (0036), avec l'audit par série (ADR-0031).
2. **Recouper** NASA avec ERA5 jour par jour en base, et ponctuellement avec
   CHIRPS v2.0 et IMERG (non gravés).
3. **Préciser la mise en garde** des 284 séries de pluie NASA (142 mensuelles,
   142 journalières, migration 0051) avec l'origine désormais établie. Aucune
   valeur n'est corrigée ni retirée.

## Origine documentée de `PRECTOTCORR`

- POWER : *« The average MERRA-2 bias corrected total precipitation »*, servie
  sur la grille MERRA-2 (0,5° × 0,625°) ; la réponse 1991-2025 porte
  `"sources": ["MERRA2"]` (le passage à GEOS-IT ne concerne que les derniers
  mois servis).
- MERRA-2 (GMAO Office Note 9 ; NASA/TM-2015-104606 vol. 43 ; Reichle & Liu
  2014, TM vol. 35) : sur l'Afrique, la pluie du modèle est **recalée à
  l'échelle de la pentade (5 jours) et d'une maille de 2,5°** sur **CMAP**
  (produit « temps réel » v0011 depuis 2007), avec un facteur interpolé sur la
  grille fine puis appliqué heure par heure. Elle n'est fidèle aux observations
  qu'à cette échelle ; la répartition à l'intérieur de la pentade vient d'un
  modèle GEOS.
- Ce modèle de répartition a changé : MERRA jusqu'en 2014 (ou février 2016 selon
  les sources), puis GEOS FP-IT 5.9.1, et 5.12.4 en temps réel à partir de
  septembre 2016 (Reichle et al. 2017, *J. Climate* ; notes du GMAO). FP-IT
  avait un excès de pluie sur les terres, corrigé dans GEOS-IT.
- La NOAA qualifie CMAP temps réel d'*« experimental in nature and contains
  some flaws »*.

## Résultats

**Pluie journalière ERA5 gravée (0050).**
- Produit : l'horaire `reanalysis-era5-single-levels` (`total_precipitation`),
  sommé sur le jour civil UTC. Le cumul daté HH couvre l'heure qui finit à HH ;
  le jour J somme donc les cumuls de 01 h (J) à 00 h (J+1).
- Lecture nœud par nœud par le service de séries temporelles du CDS, dont les
  valeurs sont identiques à celles du jeu horaire maillé (649 440 valeurs
  comparées, écart nul).
- Volume : 142 séries, 1 815 328 mesures, au même point de grille 0,25° que le
  mensuel 0036 (110 mailles).
- Cohérence avec le mensuel 0036 : moyenne des jours = mensuel à 0,0036 mm/jour
  près (57 226 mois). Sommer de 00 h à 23 h donnerait jusqu'à 0,48 mm/jour
  d'écart, ce qui confirme le calage d'une heure.
- **Constat nouveau sur 0036.** Dans 13 des 17 mois de raccord entre expériences
  de production ERA5, la moyenne mensuelle servie par le CDS diffère de la
  somme des cumuls horaires, jusqu'à 0,386 mm/jour (Tengréla, 1995-09). Vérifié
  sur le jeu horaire maillé ; la note des séries mensuelles ERA5 le signale
  (0051).
- La valeur « ERA5 : 0,9 mm » citée pour San-Pédro le 2022-09-16 venait d'un
  relevé hors CDS (archive Open-Meteo). ERA5 du CDS donne **8,32 mm** (point de
  la région) et **12,82 mm** (point du département) ; les mentions sont
  corrigées.

**Recoupement NASA ↔ ERA5 jour par jour** (142 localités, 1991-2025, 1 815 328
paires, calculé en base).
- **Aucun des 25 jours-localités NASA au-delà de 200 mm n'est confirmé.** ERA5
  y donne au plus 18,1 mm le jour même et 19,0 mm sur J ± 1, et son cumul de
  trois jours ne dépasse pas 48,3 mm, contre 270 à 938 mm pour NASA.
  Septembre 2022 à San-Pédro : NASA 1 688,5 mm, ERA5 111,9 à 169,2 mm.
- **La marche de 2016-2017 est propre à NASA.** Jours-localités > 50 mm par an :

  | | 1991-2015 | 2016 | 2017-2025 | Rapport |
  |---|---:|---:|---:|---:|
  | NASA > 50 mm | 20,5 | 109 | 247,6 | ×12,1 |
  | ERA5 > 50 mm | 88,5 | 173 | 147,6 | ×1,67 |
  | NASA > 100 mm | 0,44 | 2 | 31,2 | ×71 |
  | ERA5 > 100 mm | 11,7 | 18 | 20,6 | ×1,76 |

  - ERA5 monte progressivement et irrégulièrement depuis environ 2008 (73 par
    an en 1991-2007, 127 en 2008-2016, 148 en 2017-2025).
  - NASA monte par marche : 49 en 2015, 109 en 2016, puis 190 à 463 par an.
- **Cumul et centiles** (1991-2015 → 2017-2025) :
  - cumul annuel : NASA 1 299 → 1 556 mm (+19,8 %), ERA5 1 288 → 1 240 mm (−3,7 %) ;
  - jours ≥ 1 mm : NASA −3,6 %, ERA5 −10,1 % ;
  - 99,9ᵉ centile : NASA 40,4 → 86,6 mm (×2,14), ERA5 63,2 → 77,7 mm (×1,23).
- **Changement de comportement de NASA.** Les deux sources restent en phase sur
  l'occurrence des pluies (Spearman médian par localité 0,620 → 0,704).
  - Ce sont les **intensités** qui divergent : les jours où ERA5 dépasse 20 mm,
    NASA donne en moyenne 10,2 → 16,2 mm ; les jours secs selon ERA5, NASA
    dépasse 50 mm 1,6 → 16,1 fois par an.
  - Le rapport des cumuls mensuels moyens NASA/ERA5 passe de 1,016 à 1,255.
- **Ce que le recoupement n'établit pas.** ERA5 n'est pas une mesure au sol et a
  ses propres dérives : jours de pluie en baisse de 10 %, surtout en 2020-2025,
  et 18 jours-localités au-delà de 200 mm que NASA ne montre pas (264 mm en
  région San-Pédro le 2019-05-31). Seules des stations au sol (SODEXAM)
  trancheraient la climatologie des fortes pluies.


**CHIRPS v2.0 et IMERG (vérification ponctuelle, non gravés).**
- **Jours extrêmes.**
  - CHIRPS donne **0 mm** le jour même, la veille et le lendemain à San-Pédro,
    Sassandra, Téhini et Tabou, les jours où NASA sert 264 à 727 mm ; le total
    CHIRPS de la pentade y est aussi nul.
  - IMERG, servi par POWER lui-même (`IMERG_PRECTOT`), donne moins de 15 mm.
  - À Taï, il a réellement plu (CHIRPS 55,7 mm), mais NASA en sert sept fois plus.
  - À Ouangolodougou : CHIRPS 4 mm, IMERG 0,31 mm.
- **Chaque jour extrême tombe dans une pentade où CMAP temps réel** affiche,
  pour la maille ou une maille voisine, 5 à plus de 40 fois sa climatologie,
  alors qu'IMERG n'y voit rien de tel. La pluie NASA reproduit donc une entrée
  CMAP aberrante, concentrée par le modèle sur une maille et un jour.
- **Rupture.**
  - CHIRPS et IMERG ne montrent **aucune rupture** des jours > 50 mm entre 2005
    et 2025 (San-Pédro, Korhogo, Abidjan).
  - Chez NASA, la part du jour le plus pluvieux dans la pentade passe de
    0,32-0,36 (1991-2014) à 0,38-0,39 (2015-2016), puis 0,41-0,44 (2017-2025).
    Chez IMERG, elle reste stable.
  - Avant 2015, NASA est au contraire **trop lisse** : 99,9ᵉ centile de 22 à
    65 mm contre 50 à 92 mm pour CHIRPS.
  - Le facteur ×11,9 compare donc un avant sous-dispersé à un après gonflé par
    des extrêmes parasites.

## Conséquences

- La pluie journalière NASA ne doit servir **ni pour les extrêmes, ni pour les
  tendances, ni pour les épisodes de pluie** (salissure, lessivage). Son cumul
  mensuel, recalé sur CMAP, reste utilisable avec prudence, sauf depuis 2016,
  où il dérive de +25 % par rapport à ERA5.
- La mise en garde voyage avec les données (0051) : 284 séries de pluie NASA et
  142 séries mensuelles de pluie ERA5 portent les constats ci-dessus ; la
  citation ERA5 hors CDS de 0034 est remplacée par les valeurs du CDS en base.
- La pluie journalière ERA5 est désormais en base aux 142 localités et peut
  servir de source de comparaison. Le proxy de salissure de l'API reste épinglé
  sur NASA ; le basculer sur une autre source est une décision distincte.
- **Piste ouverte** : `IMERG_PRECTOT` (POWER, 0,1°, depuis 1998, combinaison
  satellite et pluviomètres), sans rupture constatée, est un candidat naturel
  pour la pluie journalière des épisodes.
