# Fiche méthodologique - `kt` (Indice de clarté)

> Conventions communes (versioning, politique de complétude, identité
> métier `grandeurs_metier`) : voir fiche HEP `hep.md`.

## 1. Identification

| Champ | Valeur |
|---|---|
| Nom | Indice de clarté |
| Code métier | `kt` |
| Unité | sans dimension |
| Famille | F1 - fait stocké |
| Stratégie de calcul | `stockee` (persistée dans `grandeurs_metier`) |
| Version courante | 1 |
| Périodicités exposées | annuel + mensuel |

## 2. Définition formelle

Rapport entre l'irradiation globale horizontale reçue au sol `H` (GHI) et
l'irradiation extraterrestre sur plan horizontal `H0`, celle qui atteindrait
le même lieu en l'absence d'atmosphère :

```
kt(annee)       := sum GHI(t) / sum H0(t) sur t ∈ jours(annee)
kt(annee, mois) := sum GHI(t) / sum H0(t) sur t ∈ jours(annee, mois)
```

Les séries amont sont **mensuelles** (moyenne journalière du mois, en
kWh/m²/jour). Sur les `n` jours d'un mois, `sum GHI = GHI_moyen × n` et
`sum H0 = H0_moyen × n`, d'où :

```
kt(annee, mois) = GHI_moyen / H0_moyen
kt(annee)       = sum_m GHI_m × n_m / sum_m H0_m × n_m
```

L'indice annuel est un **rapport de sommes**, pas la moyenne des indices
mensuels : les mois longs et à fort `H0` pèsent davantage.

### 2.1 Irradiation extraterrestre `H0`

Équation 1.10.3 de Duffie & Beckman (intégrale de l'éclairement
extraterrestre horizontal du lever au coucher du soleil), en kWh/m²/jour :

```
H0(n)   = (24 / π) × Gsc × E0(n) × (cos φ cos δ sin ωs + ωs sin φ sin δ) / 1000
cos ωs  = − tan φ tan δ                     (éq. 1.6.10, ωs en radians)
B       = 2π (n − 1) / 365                  (éq. 1.4.2)
δ       = 0,006918 − 0,399912 cos B + 0,070257 sin B − 0,006758 cos 2B
          + 0,000907 sin 2B − 0,002697 cos 3B + 0,00148 sin 3B      (éq. 1.6.1b)
E0      = 1,000110 + 0,034221 cos B + 0,001280 sin B
          + 0,000719 cos 2B + 0,000077 sin 2B                       (éq. 1.4.1b)
```

`φ` est la latitude de la localité, `n` le rang du jour dans l'année (1 à
366), `Gsc` la constante solaire. `H0` mensuel = **moyenne des `H0`
journaliers de tous les jours civils du mois**.

Implémentation : fonctions pures `services/grandeurs/kt.py`
(`h0_journalier`, `h0_mensuel`, `kt_mensuel`, `kt_annuel`, `calculer_kt`).

### 2.2 Choix tranchés (version 1)

| Point | Choix | Alternative écartée | Effet de l'alternative |
|---|---|---|---|
| Déclinaison | Spencer (1971), D&B éq. 1.6.1b, erreur < 0,035° | Cooper (1969), éq. 1.6.1a | jusqu'à 1,4° d'écart (début octobre) |
| Excentricité | Spencer (1971), D&B éq. 1.4.1b, ±0,01 % | `1 + 0,033 cos(360° n/365)`, éq. 1.4.1a | jusqu'à 0,26 % |
| Constante solaire | **1361 W/m²** (Kopp & Lean 2011, UAI 2015 B3) | 1367 W/m² (WRC, valeur du livre) | `kt` 0,44 % plus bas |
| `H0` mensuel | moyenne de tous les jours civils | jour moyen de Klein (1977), D&B table 1.6.1 | jusqu'à +0,46 % (février, 10,5°N) |
| Latitude | celle de la localité (référentiel) | centre de la maille de la source | jusqu'à 0,7 % en mois extrême (§ 6.3) |
| Années bissextiles | `n` de 1 à 366, `B` garde le dénominateur 365 (D&B, pvlib) | dénominateur 366 | négligeable |

Aux latitudes ivoiriennes (4,4°N à 10,5°N), le couple Cooper + éq. 1.4.1a
déplacerait `H0` mensuel de −0,3 % à +0,9 % par rapport au couple de
Spencer retenu.

La constante 1361 W/m² est la valeur mesurée par SORCE/TIM et retenue comme
valeur nominale par l'UAI ; Duffie & Beckman gardent 1367 W/m² et citent
Gueymard (2018, 1366,1 W/m²) en estimant l'écart sans effet notable. La
validation contre NASA POWER (§ 7.2) départage : 1361 W/m² donne un biais
moyen nul sur `H0`, 1367 W/m² un biais de +0,44 %.

## 3. Sources amont

`ghi` mensuel des 4 sources de l'instance, aux 142 localités (3 pilotes,
31 régions, 108 départements) :

| Source | Série amont | Période | Séries `kt` |
|---|---|---|---|
| NASA POWER (`ALLSKY_SFC_SW_DWN`) | `nasa_power_ghi_mensuel_<loc>` | 1991-2025 | `kt_nasa_power_<loc>` |
| CAMS Radiation | `cams_ghi_mensuel_<loc>` | 2005-2025 | `kt_cams_<loc>` |
| SARAH-3 (PVGIS) | `sarah3_ghi_mensuel_<loc>` | 2005-2023 | `kt_sarah3_<loc>` |
| ERA5 (PVGIS) | `era5_ghi_mensuel_<loc>` | 2005-2023 | `kt_era5_<loc>` |

`H0` est **calculé**, jamais lu chez la source : le `TOA_SW_DWN` et
l'`ALLSKY_KT` de NASA POWER servent seulement de contrôle externe (§ 7.2).
Séries calculées : source `kuma_calculs`, méthode `calcul_derive`,
confiance B (héritée de l'entrée GHI).

## 4. Politique de complétude

Stricte, au grain mensuel (les séries amont sont mensuelles) :

- une valeur mensuelle par mois présent dans la série GHI ;
- une valeur annuelle seulement si les **12 mois** de l'année existent ;
- garde-fous de la migration : séries amont complètes à la période
  attendue, GHI > 0, comptes exacts, et toute valeur dans `]0, 1[`.

Si `sum H0` ≤ 0 (nuit polaire, sans objet entre les tropiques), la valeur
n'est pas définie et le calcul est refusé.

## 5. Hypothèses physiques

- `H0` ne dépend que de la latitude et de la date : ni altitude, ni
  réfraction, ni masque d'horizon.
- Constante solaire fixe : la variabilité du cycle solaire (~0,1 %) est
  ignorée.
- `kt` ∈ ]0, 1[ : le GHI ne peut excéder `H0` à l'échelle du mois
  (l'« enhancement » nuageux n'existe qu'aux échelles infra-horaires).
- Aucune hypothèse PV, aucun paramètre utilisateur.

## 6. Limites et portée

### 6.1 `kt` hérite des biais du GHI

Pour une même localité et un même mois, `H0` est identique quelle que soit
la source : `kt_source / kt_nasa = GHI_source / GHI_nasa`. Les écarts
**relatifs** inter-sources de `kt` sont donc exactement ceux du GHI
(ADR-0009 à ADR-0011, ADR-0017) ; `kt` les exprime seulement sur une échelle
absolue commune, débarrassée de l'effet de latitude et de saison sur `H0`.
Ce n'est pas une validation : aucune source n'est une vérité sol.

### 6.2 Saut ERA5 de 2021

Les séries `kt_era5_<loc>` portent la mise en garde de la migration 0033 :
le saut du GHI ERA5 servi par PVGIS en 2021 se retrouve tel quel dans `kt`
(+3,6 % en moyenne nationale, 2021-2023 contre 2016-2020).

### 6.3 Latitude de la localité et maille de la source

`H0` est calculé à la latitude de la localité. Le `TOA_SW_DWN` de NASA
POWER se comporte comme s'il était calculé au centre de sa maille de 1°
(constat, non documenté par NASA) : pour Yamoussoukro (6,83°N, centre de
maille 6,5°N), l'écart mensuel à NASA atteint −0,7 % (−0,55 % en moyenne en
janvier) et tombe à un biais de −0,01 % si l'on calcule `H0` au centre de
maille. Le GHI d'une source maillée est lui-même une moyenne de pixel
(ADR-0015).

### 6.4 Résolution temporelle

`kt` mensuel n'est pas la moyenne des `kt` journaliers. L'`ALLSKY_KT` de
NASA POWER est publié à 2 décimales et n'est servi qu'à partir de 2001 au
pas mensuel.

## 7. Validation

### 7.1 Références publiées

Tests unitaires `tests/unit/services/grandeurs/test_kt.py` :

- dans la convention du livre (Cooper, `1 + 0,033 cos`, 1367 W/m², année
  non bissextile), la moyenne des `H0` journaliers reproduit la **table
  1.10.1 de Duffie & Beckman** (5ᵉ éd.) à 0°, 5°N, 10°N et 15°N à l'arrondi
  près (écart maximal 0,0495 MJ/m² pour un affichage au dixième), et
  l'exemple 1.10.1 (43°N, 15 avril : 33,8 MJ/m²) ;
- la convention retenue (Spencer, 1361 W/m²) s'écarte de cette table de
  −0,65 % à +0,54 % à 5°N et 10°N ;
- les formules de Spencer et de Cooper coïncident avec pvlib (écart
  relatif < 10⁻¹²).

### 7.2 Contrôle externe NASA POWER (hors dépôt)

Point mensuel NASA POWER (`TOA_SW_DWN`, `ALLSKY_KT`, `ALLSKY_SFC_SW_DWN`,
API v2.10), 5 localités de Tabou (4,42°N) à Tengréla (10,49°N), 1991-2025,
interrogé le 2026-10-15 :

| Contrôle | Mois | Biais moyen | Écart min – max |
|---|---:|---:|---:|
| `H0` (1361 W/m²) / `TOA_SW_DWN` − 1 | 2 100 | −0,01 % | −0,71 % – +0,48 % |
| `H0` (1367 W/m²) / `TOA_SW_DWN` − 1 | 2 100 | +0,43 % | −0,27 % – +0,92 % |
| `kt` NASA − `ALLSKY_KT` (2 décimales, 2001-2025) | 1 500 | +0,0002 | −0,0073 – +0,0075 |
| `kt` NASA − `ALLSKY_SFC_SW_DWN / TOA_SW_DWN` | 2 100 | +0,00005 | −0,0029 – +0,0039 |

Le GHI des seeds est identique à l'`ALLSKY_SFC_SW_DWN` servi (écart nul).
Détail par localité : ADR-0026.

## 8. Plage de valeurs typiques

### 8.1 Plage théorique attendue

`kt` ∈ ]0, 1[. Climat tropical humide : `kt` annuel de l'ordre de 0,45 à
0,6 ; minimum en saison des pluies, maximum en saison sèche.

### 8.2 Plage observée — 142 localités de Côte d'Ivoire

| Source | Période | Annuel moyen | Annuel min – max | Mensuel min – max |
|---|---|---:|---:|---:|
| NASA POWER | 1991-2025 | 0,490 | 0,439 – 0,590 | 0,307 – 0,704 |
| CAMS | 2005-2025 | 0,541 | 0,448 – 0,618 | 0,320 – 0,732 |
| SARAH-3 | 2005-2023 | 0,554 | 0,479 – 0,627 | 0,321 – 0,727 |
| ERA5 | 2005-2023 | 0,496 | 0,421 – 0,595 | 0,299 – 0,694 |

Janvier est le mois le plus clair et août le plus couvert, pour les 4
sources et dans les 3 bandes de latitude ; `kt` croît du sud au nord
(corrélation de +0,82 à +0,88 avec la latitude). Constats détaillés :
ADR-0026.

## 9. Versioning et historique

| Version | Date | Modifications |
|---|---|---|
| v1 | 2026-10 | Définition initiale : `sum GHI / sum H0` mensuel et annuel ; `H0` de Duffie & Beckman éq. 1.10.3, Spencer (1971), 1361 W/m², moyenne des jours civils ; 4 sources de GHI mensuel (ADR-0026). |

## 10. Auteurs

- v1 - 2026-10 : Siba Kalivogui (Kuma Science).

## 11. Références bibliographiques

- Duffie J.A., Beckman W.A., Blair N. 2020. *Solar Engineering of Thermal
  Processes, Photovoltaics and Wind*, 5ᵉ éd., Wiley. § 1.4, 1.6, 1.10 ;
  tables 1.6.1 et 1.10.1.
- Spencer J.W. 1971. « Fourier series representation of the position of
  the Sun ». *Search* 2(5), 172.
- Cooper P.I. 1969. « The absorption of radiation in solar stills ».
  *Solar Energy* 12(3) (cité par Duffie & Beckman).
- Klein S.A. 1977. « Calculation of monthly average insolation on tilted
  surfaces ». *Solar Energy* 19, 325-329 (jours moyens, D&B table 1.6.1).
- Kopp G., Lean J.L. 2011. « A new, lower value of total solar irradiance:
  Evidence and climate significance ». *Geophysical Research Letters* 38,
  L01706. DOI : 10.1029/2010GL045777.
- Union astronomique internationale 2015. Résolution B3 (constante solaire
  nominale 1361 W/m²).
- NASA POWER methodology - `https://power.larc.nasa.gov/docs/methodology/`
- Fiche HEP référence pour conventions communes - `docs/methodologie/grandeurs/hep.md`
