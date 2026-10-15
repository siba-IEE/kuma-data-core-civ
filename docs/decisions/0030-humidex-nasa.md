# ADR-0030 : Humidex NASA POWER (34 localités)

Date : 2026-10-15. Statut : accepté — **gravé** (migration 0045, 2026-10-15).

## Contexte

La grandeur `humidex` (id 15, F1 `stockee`, `degree_celsius` : °C apparents)
est seedée depuis 0002 avec sa fiche méthodologique
(`docs/methodologie/grandeurs/humidex.md`) et son service
(`services/grandeurs/humidex.py`), hérités du moteur. Elle croise la
**température** et l'**humidité relative** journalières, gravées par NASA POWER
(réanalyse MERRA-2) aux 34 localités du lot « pilotes + régions » sur 1991-2025
(ADR-0020). C'est la première grandeur métier calculée à partir des valeurs
météo de l'instance (la dégénérescence de pixel, ADR-0027, ne fait que
comparer les séries entre elles).

## Décision

### Définition héritée, reproduite à l'identique (version 1)

```
e = (RH/100) · 6,112 · exp(17,67 · T / (T + 243,5))      (hPa)
H = T + 5/9 · (e − 10)                                   (°C apparents)
```

Masterton & Richardson (1979), constantes de Magnus de la fiche, avec `T` et
`RH` les **moyennes du jour** (`t2m`, `rh2m`). Points lus dans le service, qui
fait foi, et vérifiés contre la fiche :

- **Humidex jour par jour**, puis **moyenne arithmétique** des humidex
  journaliers par mois et par année. L'annuel est la moyenne des jours de
  l'année, pas celle des 12 mois (écart jusqu'à 0,04 °C, mois inégaux).
- **Ce qui est stocké** : l'humidex moyen, **annuel et mensuel** (fiche § 1 et
  § 3 ; aucune valeur journalière). Le compteur de jours d'inconfort
  (`H ≥ 40`) est calculé par le service mais **pas persisté** : il n'a pas
  d'entrée au référentiel (fiche § 4). Ses valeurs sont données plus bas.
- **Complétude stricte des jours civils, sur l'intersection T2M ∩ RH2M** : un
  mois (une année) n'est gravé que si tous ses jours ont les deux mesures.
  Mesures courantes seulement (`valide_au IS NULL`, statut non `deprecie`).
- **Version de formule 1** au référentiel comme dans la fiche (§ 8, v1
  2026-05) : aucun changement de définition, donc pas de nouvelle version.
- Référence numérique : `H(30 °C, 70 %) = 40,955` ; la fiche l'arrondit à
  40,95, la docstring du service à 40,96.

### Périmètre et gravure (migration 0045)

- 34 séries `humidex_nasa_power_<localité>`, source `kuma_calculs`, méthode
  `calcul_derive`, période 1991-2025 ;
- **14 280 lignes mensuelles** (420 mois × 34) et **1 190 annuelles** (35 ans ×
  34), confiance **B** (entrées de réanalyse B). Les 434 656 jours-localités
  ont T2M et RH2M : aucun mois ni aucune année n'est écarté.
- Calcul **hors-ligne, en base**, par agrégation SQL sur `mesures_ressource`.
  Humidex journalier et moyennes en `numeric` (`exp` et quotients
  déterministes, somme exacte, donc indépendante de l'ordre d'agrégation),
  moyenne convertie en `float8` (patron ADR-0017) ; mensuel et annuel en un
  seul passage (`ROLLUP`), environ 16 s.
- Garde-fous : grandeur conforme (id, famille, stratégie, version, unité),
  entrées en °C et en %, aucune série ni ligne préexistante, 34 séries T2M et
  34 séries RH2M journalières NASA sur 1991-2025 en amont, 420 mois et 35 ans
  par série, comptes totaux exacts, toute valeur dans `]10, 50[` °C apparents
  (borne de sanité). `ANALYZE grandeurs_metier` en fin de migration. Le
  `downgrade` supprime lignes et séries ; la grandeur (seed 0002) est
  conservée.
- La **note publique** des 34 séries décrit le calcul et porte la **mise en
  garde 2024-2025** (voir « Tendance »), chiffres vérifiés par test contre la
  base.

### Vérifications

| Contrôle | Résultat |
|---|---|
| Recalcul indépendant depuis les CSV journaliers committés (formule réécrite dans le test, `statistics.fmean`) | 15 470 valeurs, tolérance relative 10⁻¹² |
| Fonction pure du service hérité (`_agreger_humidex`) sur les mêmes données | identique (10⁻¹²), aucun mois ni année écarté |
| Contre-épreuve : annuel = moyenne des 12 mois | rejetée (Abidjan 2005 : −0,029 °C) |
| Contre-épreuve : humidex des moyennes mensuelles de T et RH | rejetée (Korhogo, janvier 2005 : −0,29 °C) |
| Lecture par `/v1/series/{code}` (Abidjan, 2024) | 12 mois et l'année, valeurs de la base |
| Aller-retour `downgrade 0044` / `upgrade head` | état 0044 restauré, puis empreintes md5 des séries et des lignes identiques |

## Résultat (1991-2025)

Plages gravées : annuel **31,07** (Folon, 1999) à **38,02** (Grands-Ponts,
2024), entièrement dans la plage théorique de la fiche (`[27, 40]`) ; mensuel
21,64 (Folon, janvier 1995) à 41,01 (Grands-Ponts, avril 2024). Moyenne
nationale 1991-2020 : **34,54 °C apparents** ; humidex journalier médian 35,25,
90 % des jours-localités à 30 ou plus.

### Gradient nord-sud, côte, ouest

Normale 1991-2020, moyenne des localités par bande de latitude (bandes de
l'ADR-0024) :

| Bande | Localités | Humidex | T2M (°C) | RH2M (%) | Jours ≥ 40 par an et localité |
|---|---:|---:|---:|---:|---:|
| < 6° N | 7 | **35,80** | 25,88 | 83,4 | 4,83 |
| 6 – 7,5° N | 14 | 34,98 | 26,02 | 78,0 | 2,80 |
| 7,5 – 9° N | 6 | 33,83 | 26,12 | 71,0 | 1,07 |
| ≥ 9° N | 7 | **33,01** | 26,67 | 61,7 | 1,53 |

| Localité | Lat. | Humidex 1991-2020 | Min (année) | Max (année) | Amplitude saisonnière | Jours ≥ 40, 1991-2025 (dont 2024) | Maximum journalier |
|---|---:|---:|---|---|---:|---:|---|
| Grands-Ponts | 5,32 | **36,57** | 35,74 (1992) | 38,02 (2024) | 5,3 | **435** (93) | 42,23 (2024-04-19) |
| Abidjan | 5,42 | 36,47 | 35,67 (1992) | 37,86 (2024) | 5,3 | 387 (84) | 42,04 (2024-02-15) |
| San-Pédro | 4,75 | 35,40 | 34,50 (1992) | 36,98 (2024) | 4,9 | 55 (23) | 41,11 (2024-04-19) |
| Nawa | 5,78 | 34,83 | 33,93 (2000) | 36,11 (2024) | 4,0 | 13 (3) | 41,19 (1998-02-05) |
| Yamoussoukro | 6,83 | 35,43 | 34,67 (1999) | 36,92 (2024) | 5,8 | 187 (43) | 42,72 (1998-02-05) |
| Bounkani | 9,27 | 33,56 | 32,49 (1992) | 34,98 (2025) | 12,0 | 207 (62) | **43,09 (2024-04-02)** |
| Korhogo | 9,42 | 33,16 | 32,33 (1992) | 34,51 (2023) | 11,7 | 87 (38) | 41,84 (2024-04-03) |
| Folon | 10,00 | 32,21 | 31,07 (1999) | 33,62 (2005) | **12,6** | 20 (14) | 41,85 (2024-04-03) |
| Tonkpi | 7,40 | **32,13** | 31,24 (1999) | 33,23 (2004) | 7,7 | **0** (0) | 38,24 (2003-04-02) |

*(Amplitude saisonnière : écart entre le mois le plus et le moins
inconfortable de la climatologie mensuelle 1991-2020.)*

**Lecture (constats, pas validation) :**

- **L'humidex décroît vers le nord** : corrélation avec la latitude −0,85,
  −0,72 °C par degré, de 35,80 (< 6° N) à 33,01 (≥ 9° N). La température ne
  l'explique pas (elle croît vers le nord, +0,8 °C) : c'est l'**humidité** qui
  le porte (RH2M de 83 à 62 %).
- **La côte domine.** Les 5 localités à 5,5° N ou moins (Grands-Ponts,
  Abidjan, Sud-Comoé, Gbôklé, San-Pédro) vont de 35,40 à 36,57, contre 34,83
  et 35,00 pour la Nawa et le Lôh-Djiboua, à 5,8° N mais dans l'intérieur :
  1,2 à 1,7 hPa de vapeur d'eau de plus sur la côte. San-Pédro, la plus humide
  (RH2M 86,7 %) mais la plus fraîche de la côte (25,36 °C), est la plus basse
  des cinq.
- **L'ouest est moins inconfortable que l'est** à latitude égale
  (corrélation avec la longitude +0,58) : Guémon et Cavally 34,24 contre
  Moronou 35,86 ; Folon et Kabadougou 32,2 à 32,5 contre Bounkani 33,56. Le
  minimum national est le **Tonkpi** (32,13), pourtant humide (RH2M 77,6 %)
  mais localité la plus fraîche (T2M 24,49 °C, ADR-0020) : c'est l'analogue
  ivoirien du Fouta-Djalon de la fiche (§ 6.1), sans altitude en base pour le
  quantifier.
- **Maille MERRA-2** : 29 séries distinctes pour 34 localités (La Mé ≡
  Agnéby-Tiassa, Yamoussoukro ≡ Bélier, Lôh-Djiboua ≡ Gôh, Guémon ≡ Cavally,
  Korhogo ≡ Poro), comme la T2M et la RH2M (ADR-0020).

### Saisons : Harmattan sec contre mousson humide

Climatologie mensuelle 1991-2020 des valeurs gravées (moyenne des localités) :

| | J | F | M | A | M | J | J | A | S | O | N | D |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| National | *30,97* | 34,09 | 36,63 | **37,50** | 37,02 | 35,38 | 33,63 | 33,31 | 34,18 | 35,08 | 34,79 | 31,99 |
| < 6° N | 35,5 | 37,3 | **37,8** | 37,8 | 37,3 | 35,4 | 33,4 | *33,0* | 34,1 | 35,5 | 36,5 | 36,0 |
| 6 – 7,5° N | *32,4* | 35,6 | 37,2 | **37,4** | 36,8 | 35,2 | 33,4 | 33,3 | 34,3 | 35,2 | 35,5 | 33,4 |
| 7,5 – 9° N | *28,4* | 32,5 | 36,3 | **37,4** | 36,8 | 35,2 | 33,6 | 33,3 | 34,0 | 34,7 | 33,9 | 29,9 |
| ≥ 9° N | *25,6* | 29,2 | 34,5 | **37,5** | 37,3 | 35,9 | 34,2 | 33,6 | 34,1 | 34,8 | 32,4 | 26,9 |

L'humidex est **linéaire en T et en pression de vapeur** `e`
(`H = T + 5/9 · (e − 10)`) : la moyenne d'une période se décompose exactement.
Moyennes des jours de la saison, 1991-2020 :

| Bande | DJF : T | DJF : e (hPa) | DJF : H | MAM : H | JJA : T | JJA : e (hPa) | JJA : H |
|---|---:|---:|---:|---:|---:|---:|---:|
| < 6° N | 26,80 | 27,0 | **36,25** | 37,64 | 24,60 | 26,8 | 33,94 |
| 6 – 7,5° N | 26,84 | 22,5 | 33,78 | 37,15 | 24,74 | 26,6 | 33,96 |
| 7,5 – 9° N | 26,44 | 16,8 | 30,19 | 36,82 | 24,94 | 26,4 | 34,03 |
| ≥ 9° N | 26,05 | **12,0** | **27,16** | 36,43 | 25,73 | 25,9 | 34,57 |

**Lecture (constats, pas validation) :**

- **L'Harmattan efface l'humidex au nord.** En décembre-février, la
  température est la même partout (26,0 à 26,8 °C) mais la vapeur d'eau tombe
  de 27 hPa au sud à 12 hPa au nord (RH2M 32 % en janvier) : l'humidex du
  nord (27,2) dépasse à peine sa température, celui du sud (36,3) la dépasse
  de 9,5 °C. Le gradient nord-sud est pour l'essentiel un fait de saison
  sèche : −9,1 °C entre bandes extrêmes en DJF, −1,2 en MAM, +0,6 en JJA.
- **La mousson l'aplanit et le renverse.** En juin-août, la vapeur d'eau est
  uniforme (26 à 27 hPa) et le nord, un peu plus chaud, passe devant (34,57
  contre 33,94). Au sud, la mousson est la saison la **moins** inconfortable
  (minimum en août, 33,0 : la plus fraîche, T2M 24,2 °C), malgré une humidité
  de 85 %.
- **Le pic est partout en mars-avril**, à la transition : chaleur de fin de
  saison sèche et retour de l'humidité. En avril, le pays est presque uniforme
  (37,4 à 37,8 selon la bande). L'amplitude saisonnière va de 4 °C (Nawa) à
  12,6 °C (Folon).

### Jours d'inconfort (seuils de la fiche, non stockés)

Humidex **journalier** (T et RH moyennes du jour), seuils de la fiche
(Environnement Canada : 40 = inconfort modéré, 45 = élevé, 54 = danger),
comparaison `≥` comme le service :

- **3 998 jours-localités à 40 ou plus** sur 434 656 (0,92 %), dans **33
  localités sur 34** (aucun dans le Tonkpi, maximum 38,24). **Aucun à 45 ou
  plus** : le maximum est 43,09 (Bounkani, 2024-04-02 ; 34,8 °C et 44,75 %).
- **98 % entre février et mai** (avril 1 393, mars 1 157, février 894, mai
  488 ; janvier 60, juin 6, aucun de juillet à décembre).
- **Le sud-est en tête** : Grands-Ponts 435 jours (11,0 par an en
  1991-2020) et Abidjan 387 (9,9), puis Moronou 244 et Sud-Comoé 238 ; le
  nord-est suit (Bounkani 207). L'ouest n'en a presque pas (Guémon et Cavally
  6, Bafing 8).
- **Concentrés sur quelques années** : 2024 (1 130), 1998 (965), 2016 (468),
  2010 (367), 2020 (215) font 79 % du total. 1998, 2010, 2016 et 2024 suivent
  des épisodes El Niño marqués ; lien non testé ici.
- **Portée limitée** : les seuils d'Environnement Canada visent des valeurs
  horaires. Si la vapeur d'eau varie peu dans la journée, l'humidex de
  l'après-midi dépasse celui de la journée moyenne d'environ
  `T_max − T_moyenne` ; ces comptes sont donc des minorants de l'inconfort de
  mi-journée (non mesuré : `T2M_MAX` n'est pas gravée).

### Tendance : à ne pas lire comme un réchauffement

Moyennes nationales des 34 localités (humidex gravé ; T2M, RH2M et `e` des
jours) :

| Période | Humidex | T2M (°C) | e (hPa) | RH2M (%) |
|---|---:|---:|---:|---:|
| 1991-2000 | 34,28 | 26,03 | 24,85 | 74,2 |
| 2001-2010 | 34,73 | 26,43 | 24,95 | 73,0 |
| 2011-2020 | 34,61 | 25,97 | 25,55 | 76,4 |
| 2021-2025 | 35,26 | 26,34 | 26,06 | 76,4 |
| 2016-2023 | 34,88 | 26,05 | 25,88 | 77,1 |
| **2024-2025** | **35,69** | **26,92** | 25,78 | 73,0 |

| Pente par décennie | Humidex | T2M | 5/9 · e | RH2M |
|---|---:|---:|---:|---:|
| 1991-2025 | +0,27 °C (r² 0,32) | +0,02 °C (r² 0,00) | +0,25 °C | +1,1 point |
| 1991-2023 | +0,20 °C (r² 0,20) | −0,06 °C (r² 0,03) | +0,26 °C | +1,6 point |
| 2001-2020 | +0,00 °C (r² 0,00) | −0,38 °C (r² 0,42) | +0,38 °C | +3,4 points |

**Lecture (constats, pas validation) :**

- **Jusqu'en 2023, la hausse vient de l'humidité, pas de la chaleur.** Sur
  1991-2023, l'humidex NASA monte de +0,20 °C par décennie avec une T2M plate
  (−0,06) : toute la pente est dans la vapeur d'eau (+0,47 hPa par
  décennie). Sur 2001-2020, la T2M NASA baisse (−0,38 °C par décennie, comme
  le refroidissement NASA relevé contre ERA5 par l'ADR-0021) et la vapeur
  d'eau compense exactement : humidex plat. Aucune autre source d'humidité
  n'est gravée (ERA5 : abstention de l'ADR-0021) ; cette hausse de l'humidité
  MERRA-2 n'est donc **pas recoupée**.
- **2024-2025 : un saut de température que ERA5 ne voit pas.** L'humidex
  2024-2025 dépasse 2016-2023 de **+0,81 °C** (2,5 écarts types
  interannuels 2005-2020), aux 34 localités sans exception (+0,43 au
  Sud-Comoé à +1,07 dans la Marahoué) ; 2024 est l'année la plus
  inconfortable (35,82, maximum de 21 localités sur 34). La décomposition est
  sans ambiguïté : **+0,87 °C de T2M** et −0,06 °C de vapeur d'eau (RH2M
  −4,0 points). Or, sur 142 localités, la T2M NASA monte de +0,85 °C quand
  celle d'ERA5 ne monte que de +0,21 °C (ADR-0021, recalculé en base), et NASA
  POWER signale que sa météo combine MERRA-2 et GEOS-IT en déconseillant les
  tendances à cheval sur un changement de source. À humidité relative
  constante, chaque 0,1 °C de T2M ajoute environ 0,18 °C d'humidex.
- **Conclusion : on ne conclut pas à un réchauffement.** La pente 1991-2025
  (+0,27 °C par décennie) additionne une hausse d'humidité non recoupée et un
  saut de température 2024-2025 contredit par ERA5. D'où la mise en garde des
  notes publiques ; aucune valeur n'est corrigée.

## Conséquences

- Première grandeur métier calculée depuis la **météo** : l'humidex moyen
  mensuel et annuel est lisible aux 34 localités par `/v1/series/{code}`
  (séries `kuma_calculs`, ADR-0029).
- Le calcul exige le **journalier** : l'humidex des moyennes mensuelles de T
  et RH s'écarte de la moyenne des humidex journaliers de −0,34 à +0,48 °C
  selon le mois (moyenne −0,004). La météo mensuelle NASA des 142 localités
  (ADR-0019) ne suffit donc pas à étendre l'humidex aux départements sans ce
  biais ; il faudrait leur journalier (ADR-0020, environ 7,9 M lignes).
- Les valeurs 2024-2025 suivront toute correction ou recoupement de la T2M
  NASA (lot de vigilance de l'ADR-0021).

## Points ouverts

- **Constantes et formule de référence.** Les constantes 6,112 / 17,67 /
  243,5, attribuées par la fiche à Masterton & Richardson et à Environnement
  Canada, sont celles de Bolton (1980). La formule publiée par Environnement
  Canada part du point de rosée (`e = 6,11 · exp(5417,7530 · (1/273,16 −
  1/T_rosée))`, en kelvins) : avec le point de rosée tiré de T et RH (Magnus
  inversé), elle donnerait des humidex supérieurs de 0,18 °C en moyenne sur
  nos jours (au plus 0,35 ; 41,21 au lieu de 40,955 à 30 °C et 70 %). Changer de formule serait une version 2
  de la fiche ; la version 1 est reproduite telle quelle.
- **Révision éditoriale de la fiche** : `e` y est appelée « pression de vapeur
  saturante » alors que c'est la pression de vapeur (saturante × RH) ; les § 4
  (migration 032), § 6 et § 7.2 décrivent l'instance guinéenne (Fouta-Djalon,
  6 villes pilotes). La plage théorique (`[27, 40]`) reste valable ici.
- **Jours d'inconfort** : non stockés, faute d'entrée au référentiel
  (`humidex_nb_jours_inconfort`, fiche § 4). Un humidex de mi-journée
  demanderait `T2M_MAX` (et l'humidité associée), non gravés.
- **Deuxième source** : un humidex ERA5 suppose son humidité relative, non
  gravée (biais des moyennes mensuelles, voie horaire ouverte, ADR-0021).
