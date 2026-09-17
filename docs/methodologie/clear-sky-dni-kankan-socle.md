# Clear-sky DNI Kankan - socle ciel-clair vs traitement nuages

> Note d'analyse (analyse seule - aucune migration, aucune écriture en base,
> aucune série Core). Comparaison clear-sky ciblée pour isoler la composante
> aérosol du biais de fond et expliquer la cause du sur-biais DNI CAMS (+28 %),
> en prolongement de
> [`calage-dni-kankan-terrain-lite.md`](calage-dni-kankan-terrain-lite.md).
> Teste si ce sur-biais vient du **socle ciel-clair** de CAMS (turbidité/aérosol)
> ou de son **traitement nuages**.
> Chiffres reproductibles par
> [`scripts/analyse_clear_sky_dni_kankan.py`](../../scripts/analyse_clear_sky_dni_kankan.py)
> (lit la série sol en base + l'artefact CAMS, détecte les heures claires, compare).

## 1. Données et méthode

- **Sol (vérité)** : `gin_kankan_dni_esmap_wapp_2021_2023` (CHP1, confiance A,
  17 520 h). GHI sol **1-min** (CSV QC WAPP) pour la détection ciel-clair.
- **CAMS BNIc horaire** : artefact
  [`scripts/donnees/cams_bnic_horaire_kankan_2021_2023.csv.gz`](../../scripts/donnees/cams_bnic_horaire_kankan_2021_2023.csv.gz)
  tiré par
  [`scripts/preparer_artefact_cams_bnic_horaire.py`](../../scripts/preparer_artefact_cams_bnic_horaire.py)
  (dataset ADS `cams-solar-radiation-timeseries`, `time_step=1hour`, **col 6
  Clear sky BNI** = DNI ciel-clair modélisé ; 26 280 h, 2021-2023). Unité : au pas
  horaire, l'intégrale **Wh/m² sur 1 h vaut la moyenne W/m²** → comparable au sol.
- **Détection ciel-clair côté sol** : `pvlib.clearsky.detect_clearsky`
  (Reno-Hansen) sur le **GHI sol 1-min** vs un GHI clear-sky modélisé (Ineichen +
  turbidité Linke climatologique). Masque clair par minute → **heure « claire »**
  si ≥ 85 % des minutes de jour sont claires. Détecter sur le **GHI** puis tester
  le **DNI** garde les deux quasi indépendants.
- **Convention** : **biais = CAMS − sol** (positif = sur-estimation CAMS).
- **Périmètre du test** : heures claires **de plein soleil** (élévation ≥ 10°),
  où le DNI est énergétiquement significatif et le signal turbidité propre.

## 2. Contexte - facteur nuage interne CAMS (zéro-download)

Facteur `BNI/BNIc` mensuel (all-sky / clear-sky, 36 mois) - *contexte, pas le
test* (intègre toutes les heures de jour) :

| Saison | BNI/BNIc | Lecture |
|---|---|---|
| Harmattan | **0,888** | quasi clair (11 % de perte nuageuse au mois) |
| Intersaison | 0,711 | |
| Mousson | 0,546 | très nuageux (45 % de perte) |
| Global | 0,722 | |

## 3. Détection ciel-clair (sol)

8 279 heures de jour sur 2 ans. Heures **détectées claires** (robuste au seuil) :

| Seuil frac. claire | h claires | Harmattan / Mousson / Intersaison |
|---|---|---|
| 0,75 | 1 171 | 812 / 92 / 267 |
| **0,85 (réf)** | **938** | **640 / 73 / 225** |
| 0,95 | 662 | 444 / 52 / 166 |

Après filtre plein soleil (élév. ≥ 10°) et appariement CAMS : **892 heures
claires** retenues pour le test.

## 4. Résultat - DNI sol vs CAMS BNIc sur heures claires

| Sous-ensemble | n | sol (W/m²) | BNIc | **MBD** | **%** | RMSD | % |
|---|---|---|---|---|---|---|---|
| **GLOBAL** | 892 | 598,1 | 655,8 | **+57,7** | **+9,6 %** | 110,6 | 18,5 % |
| Harmattan | 598 | 619,2 | 696,9 | +77,7 | **+12,6 %** | 121,5 | 19,6 % |
| Mousson *(n faible)* | 73 | 579,1 | 580,9 | +1,8 | **+0,3 %** | 95,5 | 16,5 % |
| Intersaison | 221 | 547,3 | 569,2 | +21,9 | +4,0 % | 79,9 | 14,6 % |

**Sanity** : sur ces mêmes heures, l'all-sky `BNI` donne **+9,0 %** ≈ `BNIc`
+9,6 % - CAMS voit bien ces heures comme claires (`BNI ≈ BNIc`), la détection
sol est cohérente avec la vue satellite.

## 5. Diagnostic - depuis la donnée

**L'hypothèse forte (« le +28 % vient du socle ciel-clair ») est réfutée.** Sur
heures claires, le socle CAMS sur-estime de **+9,6 %**, pas +28 %. Mais ce n'est
pas nul non plus. Deux faits, sans anticiper :

1. **Un vrai biais de socle existe, et il a une signature aérosol.** **+12,6 % en
   Harmattan, 0 % en mousson** : c'est la forme d'une **sous-correction de
   turbidité/poussières** en saison sèche (aérosol Harmattan). Le socle ciel-clair
   de CAMS lit trop haut quand l'air est chargé.
2. **Mais ce socle (+10 %) n'explique pas le +28 % mensuel.** Le gros du sur-biais
   all-sky mensuel vient donc de **l'autre côté - le traitement nuages** (DNI des
   heures nuageuses + bas soleil + intégration), plus fort là où il y a des nuages
   (mousson, +46 % mensuel).

**Réconciliation avec la note de calage DNI.** Cette note (§4) concluait
« **biais HAUT systématique, *pas* un défaut aérosol** », parce que l'offset
*absolu mensuel* paraissait constant (Harmattan ≈ mousson). Le test ciel-clair
**nuance ça** : le **socle, lui, *est* aérosol-shaped** (Harmattan +12,6 % vs
mousson +0,3 %). L'offset mensuel paraissait constant parce que **le sur-biais
nuageux de la mousson compense le socle plus faible** de cette saison. Il y a donc
bien un défaut aérosol dans le socle - il n'est juste **pas le moteur dominant** du
chiffre mensuel.

## 6. Bornes (ce que cette note fait - et ne fait PAS)

- **Plein soleil seulement** (élév. ≥ 10°) : +9,6 % est le socle **haut-soleil**,
  pas le socle plein-jour (les heures basses, exclues, ont un DNI et des biais
  relatifs plus dispersés).
- **Mousson n = 73** : peu d'heures claires en saison humide → le +0,3 % mousson
  est **indicatif**, pas robuste. Harmattan (598) et intersaison (221) sont solides.
- **Détection dépend du modèle clear-sky GHI** (Ineichen + Linke climatologique) ;
  un biais du modèle déplacerait à la marge l'ensemble des heures « claires » (le
  contraste saisonnier fort, lui, ne s'explique pas par ça).
- **Point vs pixel** (CHP1 ponctuel vs CAMS 3-5 km) et **une seule station** :
  l'ampleur exacte du socle reste à confronter au réseau.

## 7. Portée

- **Explique le mécanisme et l'ampleur du +28 % CAMS** : décomposition en **socle
  ciel-clair aérosol-shaped (+10 %, minoritaire)** + **traitement nuages
  (majoritaire)**.
- **Nuance le « pas un défaut aérosol »** de la note de calage DNI : le socle *est*
  aérosol-shaped ; nuance portée à cette note.
- **Ne change pas l'usage** : CAMS DNI reste **non utilisable en valeur absolue
  sans correction sol** ; n'invalide pas `ecart_relatif_dni_cams` (relatif).

## 8. Références

- Note de calage DNI : [`calage-dni-kankan-terrain-lite.md`](calage-dni-kankan-terrain-lite.md).
- Calage GHI (miroir) : [`calage-ghi-kankan-terrain-lite.md`](calage-ghi-kankan-terrain-lite.md).
- Scripts : [`preparer_artefact_cams_bnic_horaire.py`](../../scripts/preparer_artefact_cams_bnic_horaire.py),
  [`analyse_clear_sky_dni_kankan.py`](../../scripts/analyse_clear_sky_dni_kankan.py).
