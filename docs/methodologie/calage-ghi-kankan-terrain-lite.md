# Calage GHI Kankan - caractérisation du biais satellite

> Note de calage (analyse seule - aucune migration, aucune écriture en base).
> Caractérise le **biais du GHI satellite** (NASA POWER) vs la **mesure sol**
> (ESMAP/WAPP, confiance A) au **pixel co-localisé de Kankan**, sur le
> recouvrement 2021-10 → 2023-10.
> Chiffres reproductibles par
> [`scripts/analyse_calage_ghi_kankan.py`](../../scripts/analyse_calage_ghi_kankan.py)
> (déterministe : lit les 2 séries, recalcule tout).

## 1. Données et méthode

- **Sol (vérité)** : `gin_kankan_ghi_esmap_wapp_2021_2023` (CMP10, confiance A,
  17 520 h).
- **Satellite** : `gin_kankan_ghi_nasa_power_2001_2023` (ALLSKY_SFC_SW_DWN,
  confiance B, plein record 2001-2023).
- **Appariement** : inner join sur l'instant → **17 520 paires** (recouvrement
  intégral, alignement diurne vérifié, pic GHI à 12 h UTC des deux côtés).
- **Heures de jour** : élévation solaire **≥ 5°** (pvlib, UTC) → **8 346 paires**
  retenues pour les métriques (la nuit, GHI ≈ 0, n'informe pas le biais).
- **Convention** : **biais = satellite − sol** (erreur du produit satellite ;
  positif = sur-estimation). **Relatif (%) = biais / moyenne_sol × 100**
  (comparable à l'écart inter-source). **MBD** = biais moyen, **RMSD** =
  écart-type quadratique des résidus horaires.
- **Saisons (mois UTC, définitions explicites)** : **Harmattan / saison sèche** =
  nov-déc-jan-fév-mar `{11,12,1,2,3}` ; **mousson / saison humide** = juin-sept
  `{6,7,8,9}` ; **intersaison** (transition) = `{4,5,10}`, rapportée à part (rien
  de masqué).

## 2. Résultats - biais (heures de jour)

| Sous-ensemble | n | sol (W/m²) | sat (W/m²) | **MBD** | **MBD %** | **RMSD** | **RMSD %** |
|---|---|---|---|---|---|---|---|
| **Global jour** | 8 346 | 470.9 | 484.0 | **+13.1** | **+2.8 %** | 88.3 | 18.8 % |
| Harmattan (11-3) | 3 256 | 512.8 | 535.0 | **+22.2** | **+4.3 %** | 60.4 | 11.8 % |
| Mousson (6-9) | 2 928 | 417.3 | 423.4 | **+6.1** | **+1.5 %** | 108.9 | 26.1 % |
| Intersaison (4,5,10) | 2 162 | 480.3 | 489.4 | +9.1 | +1.9 % | 92.5 | 19.3 % |

**Lecture physique.** Le satellite NASA POWER **sur-estime** le GHI au sol de
**+2.8 % en moyenne**. Le contraste saisonnier est net et cohérent avec l'enjeu
Harmattan :

- **Harmattan** : biais systématique **plus fort (+4.3 %)** mais **scatter faible
  (RMSD 11.8 %)** - ciel sec et stable, mais le satellite **sous-corrige
  l'atténuation par les poussières** (aérosol Harmattan) → sur-estimation
  systématique du GHI. C'est le signal attendu.
- **Mousson** : biais **faible (+1.5 %)** mais **scatter élevé (RMSD 26.1 %)** -
  la nébulosité convective décale les nuages entre pixel satellite et sol
  (erreur aléatoire de timing), pas un biais systématique.

## 3. Robustesse aux heures « rare » (QC)

| Sous-ensemble | n | MBD | RMSD |
|---|---|---|---|
| avec heures « rare » | 8 346 | +13.1 | 88.3 |
| sans heures « rare » | 8 341 | +13.2 | 88.3 |

Les 53 heures flaggées « extrêmement rare » par le QC (dont **5 seulement** en
heures de jour) **ne faussent pas** les métriques : MBD et RMSD inchangés à
0.1 W/m² près. Le RMSD n'est donc **pas** porté par des valeurs aberrantes.

## 4. Stationnarité - an 1 vs an 2

| Année de campagne | n | MBD | MBD % | RMSD | RMSD % |
|---|---|---|---|---|---|
| an 1 (2021-10 → 2022-10) | 4 173 | +12.1 | +2.6 % | 86.7 | 18.4 % |
| an 2 (2022-10 → 2023-10) | 4 173 | +14.2 | +3.0 % | 89.9 | 19.1 % |

Le biais est **stable entre les deux années** (MBD +2.6 % → +3.0 %, variation
0.4 point ; RMSD quasi identique) : **pas de dérive interannuelle marquée** sur
la fenêtre.

> **Honnêteté méthodologique.** Un contrôle sur **2 ans détecte une
> variation interannuelle mais ne VALIDE PAS la stationnarité du biais sur le
> record long** (climato 1991-2020, horaire 2001-2023). La chaîne CERES
> SYN1deg / MERRA-2 a évolué dans le temps. L'application future de cette
> correction au record long (régime « B-calibré ») **reste sous hypothèse de
> stationnarité**.

## 5. Bornes (ce que cette note fait - et ne fait PAS)

- **Confiance A** : au **pixel Kankan**, sur la période 2021-2023 (mesure sol
  directe). Le présent calage **caractérise** le biais satellite à ce pixel.
- **B-calibré zonal non câblé** : aucun nouveau niveau de confiance
  exposé, aucun champ « résiduel de calage ». La doctrine de confiance graduée
  reste à spécifier.
- **Aucune propagation** : la correction **n'est appliquée** ni au record long
  satellite, ni aux autres localités. C'est une **caractérisation**, pas une
  correction de production.
- Le terme d'incertitude **absolu** est désormais **mesuré** pour le GHI au pixel
  Kankan (+2.8 %, signal Harmattan +4.3 %). Restent hors de cette note : le **DNI**
  (aval, calage CAMS) et les **zones-trous** (Conakry côtier ; Mamou - Labé
  partiellement couvert par Tarambaly, en suivi).
- Stationnarité du biais sur le record long non validée (§4).

## 6. Suites possibles (hors de cette note)

- **Transfert spatial zonal** (« B-calibré ») + exposition d'un **résiduel de
  calage** - dépend d'un réseau d'analogues et d'un arbitrage schéma.
- **Calage DNI** (aval, CAMS) ; **Tarambaly** (dès métadonnées admin confirmées).

## 7. Références

- Doctrine : [`calage-terrain-solaire.md`](calage-terrain-solaire.md) (site-adaptation, confiance graduée).
- Script reproductible : [`scripts/analyse_calage_ghi_kankan.py`](../../scripts/analyse_calage_ghi_kankan.py).
