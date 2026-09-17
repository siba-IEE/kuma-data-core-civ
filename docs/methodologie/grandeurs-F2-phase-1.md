# Note méthodologique - grandeurs F2 paramétrables

> Note méthodologique sur les 5 grandeurs F2
> paramétrables : POA, productible avec correction thermique,
> productible avec PR fourni, énergie utile ECS, degrés-jours de
> climatisation. Elle fixe les arbitrages scientifiques et éditoriaux.

## 1. Contexte

Kuma Data Core : noyau de données pour l'ingénierie énergétique.
Pilote Guinée, marché cible Afrique francophone. Stack Python 3.12 +
PostgreSQL 16 + SQLAlchemy 2.x +
Alembic + FastAPI.

Les 5 grandeurs F2
paramétrables sont exposées par l'API FastAPI. Elles étendent
l'API au-delà du modèle « consultation de séries pré-calculées » en
introduisant le **calcul à la volée à partir de paramètres techniques
fournis par l'appelant** (inclinaison panneau, coefficient de
température, base degrés-jours, etc.).

**Familles de grandeurs** :

- **F1** : grandeurs calculées à partir des séries ressources
  (HEP, fraction diffuse, humidex, productible spécifique théorique,
  variabilité, indicateur de qualité, écart relatif au référentiel,
  rang temporel, rang spatial). Soit stockées en base, soit calculées
  à la volée.
- **F2** : grandeurs paramétrables - calcul à la volée à partir de
  paramètres techniques fournis par l'appelant, sur les **composants**
  énergétiques (bord-panneau, bord-capteur, climat-bâtiment).
- **F3** : grandeurs nécessitant une **modélisation système** au-delà
  du bord-composant (stockage, charge, fraction solaire annuelle,
  etc.).

**Posture éditoriale** : références scientifiques peer-reviewed
et rapports publics privilégiés comme **références primaires** dans la
présente note. Les normes industrielles payantes (IEC 61853, IEC 61724,
ISO 9806, ASHRAE Handbook, ISO 15927-6) peuvent être mentionnées à
titre informatif (« compatible IEC X / ISO Y ») mais ne constituent
pas la référence primaire. Justification : (a) accessibilité pour les
consommateurs, notamment acteurs africains,
(b) transparence éditoriale - un
consommateur doit pouvoir auditer la méthode sans devoir acheter
de la documentation normative coûteuse.

## 2. Architecture des 5 grandeurs F2 paramétrables

| # | Grandeur | Famille métier | Modèle retenu v1 | Référence primaire |
|---|---|---|---|---|
| 10 | POA paramétrable | F2 solaire | Perez 1990 + Liu-Jordan isotrope fallback | Perez et al. 1990 |
| 11 | Productible avec correction thermique | F2 solaire | NOCT simple | Ross 1980 |
| 12 | Productible avec PR fourni | F2 solaire | PR brut + PR_T via endpoint paramétré | Marion et al. 2005 + Dierauf et al. 2013 |
| 13 | Énergie utile ECS | F2 solaire | Bord-capteur (Hottel-Whillier-Bliss) | Hottel & Whillier 1958 + Duffie & Beckman 2020 |
| 14 | Degrés-jours de climatisation | F2 climat | Moyenne journalière, T_b paramètre utilisateur | Erbs et al. 1983 + Schoenau & Kehrig 1990 |

**Stratégie de calcul commune** : `calculee_volee`, après les modules
F1 `hep` / `fraction_diffuse` / `humidex` /
`productible_specifique_theorique` / `variabilite_journaliere` /
`indicateur_qualite_donnees` / `referentiels`. Un module dédié par
grandeur F2, selon le pattern « 1 grandeur = 1 module ».

Aucune persistance des résultats des 5 grandeurs F2 - le calcul est
effectué à chaque appel API à partir des séries existantes
(`mesures_ressource`, `mesures_ressource_mensuelles`, `grandeurs_metier`)
et des paramètres techniques fournis.

**Niveau de confiance dérivé** : `'B'` uniforme sur les 5
grandeurs F2 en v1. Justification : la valeur produite dépend (a) de
la fiabilité de la série F1 source ingérée depuis une source `'haute'`
(typiquement NASA POWER NRT, SARAH-3 ICDR) et (b) de la qualité des
paramètres techniques fournis par l'appelant (NOCT déclaré, η₀ déclaré,
T_b déclaré, etc.) dont on ne peut pas vérifier l'exactitude. Le
niveau `'B'` reflète cette indépendance partielle vis-à-vis du contrôle
producteur.

Le niveau `'B'` uniforme est un **choix éditorial pragmatique** v1.
Une différenciation par grandeur (par exemple `'A'` pour POA dont les
paramètres sont géométriques aisément vérifiables, `'C'` pour DJC dont
la méthode présente un biais documenté en climat tropical) pourra
être étudiée ultérieurement.

## 3. Fiche POA paramétrable

### 3.1 Définition

Irradiance dans le plan du panneau (Plane-of-Array) calculée à partir
des composantes GHI / DNI / DHI mesurées en plan horizontal, par
transposition géométrique selon l'inclinaison β et l'orientation γ du
plan.

### 3.2 Modèle retenu - Perez 1990

Le modèle de Perez et al. 1990 [^1] est retenu comme **modèle
primaire**. Décompose le diffus du ciel en trois composantes :
isotropique de fond, circumsolaire et horizon. Coefficients calibrés
sur 14 sites Nord US / Europe. Considéré comme le standard industriel
actuel - adopté par PVsyst, pvlib, NREL SAM.

Le modèle de **Liu & Jordan 1963** [^2] isotrope simple est retenu
comme **fallback** lorsque les composantes F1 DNI et DHI nécessaires au
calcul Perez ne sont pas disponibles dans les séries Kuma pour la
requête (cas de séries où seul le GHI est ingéré). Le fallback ne se
déclenche pas sur omission d'un paramètre utilisateur - les paramètres
utilisateur (β, γ, ρ) sont obligatoires pour les deux modèles.

Les modèles anisotropes **intermédiaires Hay-Davies 1980 et HDKR
(Reindl et al. 1990)** sont reconnus dans la littérature comme
alternatives entre Liu-Jordan isotrope et Perez. Ces deux modèles ne
sont pas retenus en v1 - le choix « Perez primaire + Liu-Jordan
fallback » couvre la plage précision / disponibilité avec deux niveaux
discrets jugés suffisants. Hay-Davies et HDKR
pourraient être ajoutés comme options paramétrables ultérieurement si la
demande consommateur le justifie.

### 3.3 Paramètres d'entrée utilisateur

| Paramètre | Unité | Plage validée | Obligatoire |
|---|---|---|---|
| Inclinaison β | degrés | [0, 90] | Oui |
| Orientation γ | degrés (azimut, 0 = nord, 180 = sud) | [0, 360] | Oui |
| Albédo de sol ρ | sans unité | [0, 1] | Non (défaut 0.2 typique sol végétalisé) |

### 3.4 Hypothèses et domaine de validité

- Hypothèses Perez : décomposition diffus en 3 zones (isotropique,
  circumsolaire, horizon). Validité pour ciel partiellement couvert
  (typique mousson Guinée).
- Coefficients Perez calibrés majoritairement Nord US / Europe.
  Validation tropicale spécifique limitée.
- Plan unique non ombré, surface plane (pas de surface concentratrice
  ni trackers complexes ; tracker éventuel ultérieurement).

### 3.5 Limitations documentées

- **L-POA-1** : coefficients Perez non recalibrés Afrique de l'Ouest.
  Biais résiduel possible en ciel mixte mousson (juin-octobre Guinée).
- **L-POA-2** : lorsque le fallback Liu-Jordan est déclenché (DNI /
  DHI F1 indisponibles dans les séries Kuma), la précision se dégrade
  de 10-15% sous ciel partiellement couvert selon Perez et al. 1990
  [^1].
- **L-POA-3** : pas de prise en compte d'ombrage local (bâtiments,
  végétation, relief proche). Le calcul suppose une exposition idéale.

### 3.6 Références

[^1]: Perez R., Ineichen P., Seals R., Michalsky J., Stewart R. 1990.
*Modeling daylight availability and irradiance components from direct
and global irradiance*. Solar Energy 44(5), 271-289. DOI :
10.1016/0038-092X(90)90055-H. (Version publiée open access :
archive-ouverte.unige.ch/unige:17206)

[^2]: Liu B.Y.H., Jordan R.C. 1963. *The long-term average performance
of flat-plate solar-energy collectors: With design data for the U.S.,
its outlying possessions and Canada*. Solar Energy 7, 53-74. DOI :
10.1016/0038-092X(63)90006-9.

## 4. Fiche Productible avec correction thermique

### 4.1 Définition

Productible PV ajusté en fonction de la température opérationnelle du
module, qui dégrade la puissance par rapport aux conditions de test
standard (STC : 1000 W/m², 25 °C, AM1.5).

### 4.2 Modèle retenu - NOCT simple

Le **modèle NOCT** (Nominal Operating Cell Temperature) est retenu
comme **modèle v1**. Formule originale Ross 1980 [^3] :

```
T_cell = T_amb + (NOCT - 20) × G / 800
```

Avec :

- T_cell : température cellule modulée (°C)
- T_amb : température ambiante (°C, T2M NASA POWER)
- NOCT : température nominale d'opération de cellule, fiche produit
  module (°C)
- G : irradiance reçue par le module (W/m², GHI ou POA selon
  configuration)

Production électrique corrigée :

```
P_AC = P_STC × (G / 1000) × [1 + γ_Pmax × (T_cell - 25)]
```

Avec γ_Pmax coefficient de température (en %/°C, fiche produit,
typiquement négatif).

### 4.3 Paramètres d'entrée utilisateur

| Paramètre | Unité | Plage validée | Obligatoire |
|---|---|---|---|
| NOCT | °C | [40, 50] (typique 45) | Oui |
| Coefficient température γ_Pmax | %/°C | [-0.6, -0.1] | Oui |
| Puissance nominale STC P_STC | Wc | > 0 | Oui (sortie par Wc unitaire) |

### 4.4 Hypothèses et domaine de validité

- Modèle thermique linéaire simplifié (1 paramètre NOCT, pas de prise
  en compte vent / convection).
- Coefficient température linéaire dans la plage de température
  opérationnelle réaliste (-20 à +80 °C température cellule).
- Hypothèse d'ombrage nul et de bon refroidissement (montage standard
  en toiture inclinée ou champ libre).

### 4.5 Limitations documentées

- **L-THERM-1** : modèle NOCT simple ne prend pas en compte le
  **vent (WS2M)** qui peut significativement refroidir le module. Le
  modèle Faiman 2008 [^4] avec coefficients U₀ et U₁ corrige cette
  limitation. WS2M est ingéré, mais le calcul Faiman lui-même relève de
  la **voie terrain** : ses coefficients par
  défaut sont calibrés en climat désertique et leur transposition au
  climat guinéen tropical sans calibration locale produirait une
  fausse confiance B.
- **L-THERM-2** : modèle Sandia SAPM (King et al. 2004 [^5]) et modèle
  PVsyst plus précis disponibles dans la littérature mais nécessitent
  plus de paramètres entrée (PVsyst) ou calibrations site (SAPM).
  Différés.
- **L-THERM-3** : T_amb = T2M MERRA-2 NASA POWER avec biais d'altitude
  documenté : sous-estimation possible en zone
  Fouta-Djalon (Labé, Mamou). Biais répercuté directement sur T_cell
  calculée.

### 4.6 Références

[^3]: Ross R.G. Jr. 1980. *Flat-plate photovoltaic array design
optimization*. Conference Record of the 14th IEEE Photovoltaic
Specialists Conference, San Diego, CA, 7-10 janvier 1980, p. 1126-1132.
JPL/NASA open access (PDF disponible).

[^4]: Faiman D. 2008. *Assessing the outdoor operating temperature of
photovoltaic modules*. Progress in Photovoltaics: Research and
Applications 16(4), 307-315. DOI : 10.1002/pip.813.

[^5]: King D.L., Boyson W.E., Kratochvil J.A. 2004. *Photovoltaic Array
Performance Model*. Sandia National Laboratories Report SAND2004-3535,
open OSTI (ID 919131).

## 5. Fiche Productible avec PR fourni

### 5.1 Définition

Productible PV calculé en appliquant un Performance Ratio (PR) fourni
par l'appelant à la production théorique « plaque » du système. Le PR
quantifie l'ensemble des pertes par rapport au cas idéal.

### 5.2 Modèles retenus - PR brut + PR_T via endpoint paramétré

**Deux variantes exposées** via un seul endpoint paramétré par
`correction='aucune'|'temperature'`.

**PR brut** [^6] (Marion et al. 2005) :

```
PR = E_AC_kWh / (P_STC_kWc × H_POA_kWh/m² / 1)
```

**PR_T** [^7] (Dierauf et al. 2013, NREL/TP-5200-57991) -
temperature-corrected :

```
PR_T = E_AC_kWh / (P_STC_kWc × H_POA_kWh/m² × ratio_correction_temperature)
```

Avec `ratio_correction_temperature` une fonction du delta de
température cellule vs STC, formule détaillée dans Dierauf et al. 2013.

### 5.3 Paramètres d'entrée utilisateur

| Paramètre | Unité | Plage validée | Obligatoire |
|---|---|---|---|
| PR fourni | sans unité | [0, 1] | Oui |
| Type correction | enum `aucune` \| `temperature` | - | Oui (défaut `aucune`) |
| Puissance nominale STC P_STC | Wc | > 0 | Oui |

Si `correction='temperature'`, paramètres supplémentaires requis :
NOCT, γ_Pmax (cf. section 4.3). Dans ce cas, le biais d'altitude T2M est
également répercuté par effet du calcul thermique sur T_cell (cf. § 8
L-TR-1).

### 5.4 Hypothèses et domaine de validité

- Le PR fourni est supposé représentatif de l'ensemble des pertes
  (ohmiques, conversion, salissure, indisponibilité, etc.) sauf la
  température si `correction='temperature'`.
- Validité pour systèmes connectés réseau monoclasse-modules sans
  tracker. Trackers et systèmes hybrides : différés.

### 5.5 Limitations documentées

- **L-PR-1** : variantes PR weather-corrected (PR_W) et PR
  climate-corrected (PR_C) différées (nécessitent un TMY Guinée, cf. § 9.1).
- **L-PR-2** : Reich et al. 2012 [^8] documente que des PR > 90% sont
  réalistes pour systèmes optimisés (médiane mesurée 84% sur des
  systèmes allemands en 2010). La validation de la plage [0, 1] côté
  API ne signale pas les PR irréalistement bas (< 0.5) ni élevés
  (> 0.95) - la responsabilité du choix repose sur l'appelant.

### 5.6 Références

[^6]: Marion B., Adelstein J., Boyle K., Hayden H., Hammond B.,
Fletcher T., Canada B., Narang D., Shugar D., Wenger H., Kimber A.,
Mitchell L., Rich G., Townsend T. 2005. *Performance parameters for
grid-connected PV systems*. NREL Conference Paper NREL/CP-520-37358,
31st IEEE PVSC, Lake Buena Vista FL, 3-7 janvier 2005. Open access
(https://docs.nrel.gov/docs/fy05osti/37358.pdf).

[^7]: Dierauf T., Growitz A., Kurtz S., Cruz J.L.B., Riley E., Hansen
C. 2013. *Weather-Corrected Performance Ratio*. NREL Technical Report
NREL/TP-5200-57991, avril 2013. DOI : 10.2172/1078057. Open NREL.

[^8]: Reich N.H., Müller B., Armbruster A., van Sark W.G.J.H.M., Kiefer
K., Reise C. 2012. *Performance ratio revisited: is PR > 90%
realistic?*. Progress in Photovoltaics 20(6), 717-726. DOI :
10.1002/pip.1219.

Référence complémentaire IEA PVPS Task 13 [^9] mentionnée à titre
informatif :

[^9]: IEA PVPS Task 13. 2014. *Analytical Monitoring of Grid-connected
Photovoltaic Systems: Good Practices for Monitoring and Performance
Analysis*. IEA-PVPS T13-03:2014. Open IEA-PVPS.

## 6. Fiche Énergie utile ECS

### 6.1 Définition

Énergie thermique utile produite par un capteur solaire eau-chaude-
sanitaire au bord du capteur, fonction des conditions d'irradiance, de
la température entrée fluide caloporteur, et des caractéristiques
optiques et thermiques du capteur fournies par l'appelant.

### 6.2 Modèle retenu - Hottel-Whillier-Bliss bord-capteur

Le modèle de **Hottel & Whillier 1958** [^10] est retenu comme
**modèle v1**. Équation d'efficacité instantanée au bord du capteur
(forme polynôme 2ᵉ ordre) :

```
η = η₀ - a₁ × ΔT / G - a₂ × (ΔT)² / G
```

Avec :

- η : rendement instantané du capteur (sans unité)
- η₀ : rendement optique nul-perte (sans unité, fiche capteur Solar
  Keymark)
- a₁ : coefficient de pertes linéaires (W/(m²·K), fiche capteur)
- a₂ : coefficient de pertes quadratiques (W/(m²·K²), fiche capteur)
- ΔT : différence T_fluide_moyenne − T_amb (K), où T_amb = T2M NASA
  POWER
- G : irradiance globale plan du capteur (W/m², GHI ou POA selon
  configuration)

Énergie utile par m² par pas de temps :

```
Q_utile = η × G × Δt
```

### 6.3 Paramètres d'entrée utilisateur

| Paramètre | Unité | Plage validée | Obligatoire |
|---|---|---|---|
| Rendement optique η₀ | sans unité | [0.5, 0.9] (typique 0.8) | Oui |
| Coefficient pertes linéaires a₁ | W/(m²·K) | [1, 8] (typique 3.5) | Oui |
| Coefficient pertes quadratiques a₂ | W/(m²·K²) | [0, 0.05] (typique 0.01) | Oui |
| Température fluide entrée T_in | °C | [10, 90] | Oui |
| Débit massique m_dot | kg/(s·m²) | > 0 | Non (impact température sortie, pas v1) |

### 6.4 Hypothèses et domaine de validité

- Modèle instantané au bord du capteur. Pas de prise en compte de la
  dynamique du système (capacité thermique, tubes, ballon).
- Hypothèse d'ombrage nul et d'incidence solaire normale au plan
  capteur (validité décroissante pour angles d'incidence élevés - IAM
  Incidence Angle Modifier non modélisé v1).
- Coefficients η₀, a₁, a₂ supposés stables sur la plage de température
  opérationnelle utile (10-90 °C pour ECS résidentiel).

### 6.5 Limitations documentées

- **L-ECS-1** : pas de calcul de la production système complet
  (production utile annuelle prenant en compte stockage, charge,
  fraction solaire). La méthode **f-chart de Klein et al. 1976** [^11]
  est dans la littérature mais hors périmètre F2 strict - pourrait
  devenir une **grandeur F3 « production système »** ultérieure.
  Définition F2 vs F3 rappelée § 1 : F2 = bord-composant à paramètres
  techniques fournis par l'appelant, F3 = modélisation système au-delà
  du bord-composant.
- **L-ECS-2** : pas de modulation IAM (Incidence Angle Modifier) pour
  les angles d'incidence élevés. Biais d'efficacité sur les périodes
  matin/soir et solstice d'hiver.
- **L-ECS-3** : le calcul suppose les coefficients η₀, a₁, a₂
  disponibles via fiche Solar Keymark ou équivalent. Si le capteur
  n'est pas testé selon une norme (test maison artisanal), la qualité
  du résultat dépend de la fiabilité des coefficients déclarés.
- **L-ECS-4** : T_amb = T2M MERRA-2 NASA POWER avec biais d'altitude
  documenté : sous-estimation possible en zone
  Fouta-Djalon (Labé, Mamou). Biais répercuté directement sur ΔT, donc
  sur η et Q_utile calculés à ces villes.

### 6.6 Références

[^10]: Hottel H.C., Whillier A. 1958. *Evaluation of flat-plate solar
collector performance*. Transactions of the Conference on the Use of
Solar Energy, vol. 2, part 1, p. 74. University of Arizona Press,
Tucson, AZ. Référence fondatrice.

[^11]: Klein S.A., Beckman W.A., Duffie J.A. 1976. *A design procedure
for solar heating systems*. Solar Energy 18(2), 113-127. DOI :
10.1016/0038-092X(76)90044-X. (Cité pour information F3 future.)

[^12]: Duffie J.A., Beckman W.A., Blair N. 2020. *Solar Engineering of
Thermal Processes, Photovoltaics and Wind*. 5ᵉ édition, Wiley. ISBN
978-1-119-54028-1. DOI éditeur : 10.1002/9781119540328. Référence
académique standard.

## 7. Fiche Degrés-jours de climatisation (DJC)

### 7.1 Définition

Indicateur climatique mensuel quantifiant les besoins de refroidissement
d'un bâtiment selon une base de référence T_b en °C définie par
l'appelant. Représente l'intégrale au-dessus de la base sur la période
considérée.

### 7.2 Modèle retenu - moyenne journalière

La **méthode de la moyenne journalière** (Erbs et al. 1983 [^13],
Schoenau & Kehrig 1990 [^14]) est retenue comme **modèle v1**.

Formule :

```
DJC_mois = Σ max(0, T_moy_jour - T_b)
```

Avec :

- T_moy_jour : température moyenne quotidienne (°C, T2M NASA POWER
  agrégée jour)
- T_b : base de référence (°C, entrée utilisateur)

### 7.3 Paramètres d'entrée utilisateur

| Paramètre | Unité | Plage validée | Obligatoire |
|---|---|---|---|
| Base T_b | °C | [10, 35] | Oui |

**Valeurs typiques documentées** (à titre informatif dans la fiche) :

- 18.3 °C : base ASHRAE historique Amérique du Nord (heating-oriented,
  peu pertinent contexte Guinée)
- 24 °C : base utilisée par la Réglementation Thermique, Acoustique et
  Aération des départements d'Outre-Mer (RTAA DOM) [^17] (climat
  tropical Antilles, Réunion, Guyane)
- 24-26 °C : Directive régionale CEDEAO sur l'efficacité énergétique
  des bâtiments [^18] (consignes climatisation zone CEDEAO)
- 26 °C : base souvent retenue pour climat tropical chaud humide
  (Butera et al. 2014 [^15])

### 7.4 Hypothèses et domaine de validité

- Méthode mathématiquement définie sans hypothèse intrinsèque sur le
  climat - applicable partout.
- Précision dépend de la représentativité de T_moy_jour pour la
  variabilité diurne réelle.

### 7.5 Limitations documentées

- **L-DJC-1** : la méthode de la moyenne journalière sous-estime le
  DJC en climat à fort cycle diurne. Krese et al. 2012 [^16] documente
  cette limite et propose des améliorations méthodologiques (wet-bulb
  cooling degree days notamment). En climat tropical humide à fort
  cycle diurne (variabilité diurne pouvant dépasser 15 °C), le biais
  résiduel de la méthode standard est estimé dans la littérature
  entre -5 et -15 % selon les conditions. L'intégration horaire
  (Erbs et al. 1983 [^13]) est plus précise mais nécessite des données
  horaires. La méthode `integration_horaire`
  est désormais exposée (paramètre `methode` de l'endpoint DJC),
  consommant le T2M horaire stocké et validé ; la méthode
  journalière reste le défaut (rétro-compatible).
- **L-DJC-2** : pas de norme de base T_b consolidée pour la Guinée
  spécifiquement. Les valeurs typiques documentées (section 7.3) sont
  des références régionales ou normatives partiellement transposables.
  Le choix relève de la responsabilité de l'appelant.
- **L-DJC-3** : T_amb = T2M MERRA-2 NASA POWER. Le biais d'altitude est
  répercuté : sous-estimation pour Labé / Mamou
  (Fouta-Djalon) sous-estime le DJC à ces villes.
- **L-DJC-4** : la méthode dite Balanced Point Method (BPM, ASHRAE
  Handbook 2021) qui ajuste T_b par bâtiment est hors périmètre F2.
  L'endpoint calcule un DJC à T_b utilisateur fixe.

### 7.6 Références

[^13]: Erbs D.G., Klein S.A., Beckman W.A. 1983. *Estimation of
degree-days and ambient temperature bin data from monthly-average
temperatures*. ASHRAE Journal 25(6), 60-65.

[^14]: Schoenau G.J., Kehrig R.A. 1990. *Method for calculating
degree-days to any base temperature*. Energy and Buildings 14(4),
299-302. DOI : 10.1016/0378-7788(90)90092-W.

[^15]: Butera F.M., Adhikari R., Aste N. 2014. *Sustainable Building
Design for Tropical Climates: Principles and Applications for Eastern
Africa*. UN-Habitat. ISBN 978-92-1-132599-7. Open access
(https://unhabitat.org).

[^16]: Krese G., Prek M., Butala V. 2012. *Analysis of building
electric energy consumption data using an improved cooling degree day
method*. Strojniški vestnik - Journal of Mechanical Engineering 58(2),
107-114. DOI : 10.5545/sv-jme.2011.160. Open access (CC-BY 4.0).

[^17]: France. *Réglementation Thermique, Acoustique et Aération des
départements d'Outre-Mer (RTAA DOM)*. Décret n° 2009-424 du 17 avril
2009 ; Arrêté du 17 avril 2009 modifié ; Décret n° 2016-13 du
11 janvier 2016. Ministère chargé du Logement / Ministère de la
Transition écologique. Accès Légifrance et ecologie.gouv.fr.

[^18]: ECOWAS Centre for Renewable Energy and Energy Efficiency
(ECREEE). *Directive régionale CEDEAO sur l'efficacité énergétique des
bâtiments*. Open access ECREEE (https://www.ecreee.org). Cité à titre
informatif pour les consignes climatisation 24-26 °C en zone CEDEAO.

## 8. Limitations transverses

| # | Limitation | Grandeurs F2 touchées | Mitigation |
|---|---|---|---|
| L-TR-1 | Biais d'altitude T2M MERRA-2 (Fouta-Djalon) répercuté sur grandeurs avec T_amb | F2-#11 (thermique), F2-#12 (PR si correction='temperature'), F2-#13 (ECS), F2-#14 (DJC) | Documenter par localité. Lever avec validation sol Guinée. |
| L-TR-2 | Pas de propagation d'incertitude probabiliste sur les paramètres utilisateur | Toutes (#10-#14) | Le niveau de confiance dérivé `'B'` reflète l'incertitude qualitative. Mitigation ultérieure : intervalle d'incertitude calculé selon plage paramètres. |
| L-TR-3 | Pas de prise en compte d'ombrage local (bâtiments, végétation, relief proche) | F2-#10 (POA), F2-#11 (thermique), F2-#13 (ECS) | Hors périmètre F2 strict. Modélisation 3D site = module dédié ultérieur. |
| L-TR-4 | Validation locale sol Guinée différée | Toutes (#10-#14) | Lever avec stations sol. |
| L-TR-5 | Sensibilité aux réingestions NRT : les résultats F2 sont sensibles aux réingestions des séries F1 source | Toutes (#10-#14) | Cohérent avec la stratégie `calculee_volee` : deux appels identiques à deux dates différentes peuvent retourner des valeurs différentes si une réingestion NRT → ICDR (ou correction rétroactive) est intervenue entre temps. À documenter dans la doc consommateur. |
| L-TR-6 | Biais de moyennage à granularité journalière : les modèles F2 sont historiquement formulés et validés à granularité horaire ou sub-horaire (notamment Perez 1990, NOCT, Hottel-Whillier-Bliss). Leur application à granularité journalière introduit un biais de moyennage | Toutes (#10-#14), avec impact différent selon le modèle | **DJC, POA et thermique levés** par intégration horaire (`methode=integration_horaire`). Biais mesurés : POA **+16 %** (surestimation, §9.2), thermique **surestimation** (la moyenne 24 h sous-estime le pic de midi → sous-estime T_cell). **PR / ECS** : restent journaliers (GHI-based, même biais) - extension ultérieure, même patron. |

## 9. Extensions ultérieures

### 9.1 Variantes différées

**Intégration horaire DJC** (livrée).
La méthode de la moyenne journalière retenue v1 sous-estime le DJC en
climat à fort cycle diurne (biais -5 à -15 % documenté dans la
littérature climat tropical). Résolution : la méthode d'intégration
horaire (Erbs et al. 1983 [^13], `DJC = Σ_heures max(0, T_h − T_b) / 24`)
est implémentée et exposée via le paramètre `methode=integration_horaire`
de l'endpoint DJC, consommant le T2M horaire stocké et validé. La
méthode journalière reste le défaut.

**Modèle thermique Faiman U₀/U₁ et intégration vent WS2M**. Le
modèle NOCT simple retenu v1 ne prend pas en compte le vent qui peut
significativement refroidir le module PV. Le modèle Faiman 2008 [^4]
avec coefficients U₀ et U₁ corrige cette limitation. Le vent (WS2M) est
ingéré ; l'activation du modèle Faiman comme option utilisateur suppose
une calibration locale des coefficients (voie terrain, cf.
`limites-substrat-physique-solaire.md`).

**PR weather-corrected (PR_W) et PR climate-corrected (PR_C)**.
Les variantes PR_W et PR_C documentées par Dierauf et al. 2013 [^7]
nécessitent un TMY (Typical Meteorological Year) Guinée actuellement
non disponible publiquement (NREL TMY3 ne couvre pas l'Afrique).
Deux voies : (a) attendre publication d'un TMY Guinée par
institution tierce, ou (b) construire un TMY interne à partir des
données SARAH-3 ICDR multi-décennie + NASA POWER, avec couverture
multi-décennie minimum (≥ 10 ans), méthode TMY référencée (type
Hall-Sandia ou équivalent) et validation croisée vs source externe.

### 9.2 Autres extensions

- Module **ombrage local 3D** pour POA / thermique / ECS (module dédié
  ultérieur)
- **f-chart Klein 1976** comme grandeur F3 « production système ECS »
  (si demande consommateur)
- **Bifacial** PV : grandeur `poa_bifacial`,
  modèle infinite-sheds row-aware, distinct du POA mono-plan. Limitations
  documentées : **L-BFAC-1** géométrie/bifacialité non recalibrées Guinée
  (confiance B) ; **L-BFAC-2** rangées infinies uniformes (effets de bord de
  champ ignorés) ; **L-BFAC-3** albédo journalier broadcast aux heures en mode
  horaire ; **L-BFAC-4** biais L-TR-6 sur la méthode journalière (levé par
  l'intégration horaire).
- **Trackers** PV : monoaxe, biaxe - élargissement périmètre paramétrage POA,
  à scoper selon retours consommateurs
- **Intervalles d'incertitude probabilistes** propagés sur les
  paramètres utilisateur (mitigation L-TR-2)
- Validation **stations sol Guinée** dès leur ouverture publique
  (mitigation L-TR-4)
- **Soiling et dégradation modules PV** : effets documentés en zone
  sahélienne / sub-saharienne (perte annuelle 1-5 % selon poussière
  et fréquence de lavage). Candidat naturel d'extension sur F2-#11
  (thermique) et F2-#12 (PR).
- **IAM (Incidence Angle Modifier) ECS** : modulation du rendement aux
  angles d'incidence élevés (L-ECS-2), si demande consommateur.
- **Modèles POA intermédiaires** : Hay-Davies 1980 et HDKR (Reindl et
  al. 1990) entre Liu-Jordan isotrope et Perez 1990, si
  l'écart de précision avec Perez justifie la complexité.
- **Quantification empirique du biais de moyennage journalier**
  (L-TR-6) - **réalisée pour le POA et le thermique** ;
  l'intégration horaire est désormais étendue à **PR et ECS**
  (**L-TR-6 levée intégralement**) - gain sur PR_T (T_cell non-linéaire) et ECS
  (rendement HWB non-linéaire), **nul sur PR brut** (linéaire en G, exposé pour
  cohérence d'interface).
  L'étude `scripts/etude_l_tr_6_biais_poa_horaire.py` compare, sur le
  GHI/DNI/DHI horaire stocké (6 villes, 2022), le POA calculé à entrées
  journalières (Perez au midi solaire) vs à entrées horaires (Perez par
  heure, intégré). Résultat : la méthode journalière **surestime le POA de
  +14 à +17 %** pour un plan incliné 10° plein sud (Conakry +16,6 %,
  Nzérékoré +13,8 %). Cause : à 9-11°N le soleil passe au nord du site
  d'avril à août et le matin/soir il est bas - heures où un plan sud capte
  moins ; appliquer la géométrie du midi à toute l'énergie du jour
  surestime. Pour le **thermique** (GHI-based, pas POA), la méthode
  journalière calcule T_cell sur l'irradiance moyennée 24 h ; ce lissage
  sous-estime le pic de midi, donc T_cell et la perte thermique →
  **surestime le productible** (test : horaire < journalier, Conakry juin
  2022). POA et thermique sont désormais exposés en
  `methode=integration_horaire`. **PR / ECS** (GHI-based) héritent du même
  biais - extension ultérieure, même patron.

## 10. Cohérence inter-grandeurs F1 → F2

Les 5 grandeurs F2 paramétrables s'appuient sur des grandeurs F1 Kuma
(GHI, DNI, DHI, T2M selon le cas) ingérées NASA POWER. La propagation
des niveaux de confiance est la suivante :

| Grandeur F2 | Grandeur F1 source principale | Niveau confiance source F1 | Niveau dérivé F2 v1 |
|---|---|---|---|
| F2-#10 POA | GHI, DNI, DHI | haute | B |
| F2-#11 Thermique | T2M, GHI ou POA | haute | B |
| F2-#12 PR | GHI ou POA, T2M (si correction) | haute | B |
| F2-#13 ECS | T2M, GHI ou POA | haute | B |
| F2-#14 DJC | T2M | haute | B |

Le niveau `'B'` uniforme reflète que la qualité de la valeur F2 dépend
non seulement de la source F1 (`'haute'`) mais aussi des **paramètres
techniques fournis par l'appelant** dont le producteur ne contrôle pas
l'exactitude (NOCT, γ_Pmax, η₀, a₁, a₂, T_b, etc.). Le niveau `'B'`
est donc un dénominateur commun pragmatique reflétant cette double
dépendance.

**Choix éditorial v1** : le niveau `'B'` uniforme est délibérément
choisi comme pragmatique pour la première itération.
Une différenciation par grandeur (par exemple `'A'` pour POA aux
paramètres géométriques aisément vérifiables, `'C'` pour DJC dont la
méthode présente un biais documenté en climat tropical) pourra être
étudiée ultérieurement une fois les premiers retours d'usage obtenus.

À documenter en fiche : la responsabilité de la qualité des paramètres
utilisateur relève de l'appelant.

## 11. Bibliographie consolidée (18 références)

- Butera F.M., Adhikari R., Aste N. 2014. *Sustainable Building Design
  for Tropical Climates: Principles and Applications for Eastern
  Africa*. UN-Habitat. ISBN 978-92-1-132599-7.
- Dierauf T., Growitz A., Kurtz S., Cruz J.L.B., Riley E., Hansen C.
  2013. *Weather-Corrected Performance Ratio*. NREL Technical Report
  NREL/TP-5200-57991, avril 2013. DOI : 10.2172/1078057.
- Duffie J.A., Beckman W.A., Blair N. 2020. *Solar Engineering of
  Thermal Processes, Photovoltaics and Wind*. 5ᵉ édition, Wiley.
  ISBN 978-1-119-54028-1.
- ECREEE. *Directive régionale CEDEAO sur l'efficacité énergétique des
  bâtiments*. Open access ECREEE.
- Erbs D.G., Klein S.A., Beckman W.A. 1983. *Estimation of degree-days
  and ambient temperature bin data from monthly-average temperatures*.
  ASHRAE Journal 25(6), 60-65.
- Faiman D. 2008. *Assessing the outdoor operating temperature of
  photovoltaic modules*. Progress in Photovoltaics 16(4), 307-315.
  DOI : 10.1002/pip.813.
- France. *Réglementation Thermique, Acoustique et Aération des
  départements d'Outre-Mer (RTAA DOM)*. Décret n° 2009-424 du 17 avril
  2009 + Arrêté du 17 avril 2009 modifié + Décret n° 2016-13 du
  11 janvier 2016. Ministère chargé du Logement / Transition écologique.
- Hottel H.C., Whillier A. 1958. *Evaluation of flat-plate solar
  collector performance*. Transactions of the Conference on the Use of
  Solar Energy, vol. 2, part 1, p. 74. University of Arizona Press.
- IEA PVPS Task 13. 2014. *Analytical Monitoring of Grid-connected
  Photovoltaic Systems: Good Practices for Monitoring and Performance
  Analysis*. IEA-PVPS T13-03:2014.
- King D.L., Boyson W.E., Kratochvil J.A. 2004. *Photovoltaic Array
  Performance Model*. SAND2004-3535, open OSTI (ID 919131).
- Klein S.A., Beckman W.A., Duffie J.A. 1976. *A design procedure for
  solar heating systems*. Solar Energy 18(2), 113-127. DOI :
  10.1016/0038-092X(76)90044-X.
- Krese G., Prek M., Butala V. 2012. *Analysis of building electric
  energy consumption data using an improved cooling degree day method*.
  Strojniški vestnik 58(2), 107-114. DOI : 10.5545/sv-jme.2011.160.
- Liu B.Y.H., Jordan R.C. 1963. *The long-term average performance of
  flat-plate solar-energy collectors: With design data for the U.S.,
  its outlying possessions and Canada*. Solar Energy 7, 53-74. DOI :
  10.1016/0038-092X(63)90006-9.
- Marion B. et al. 2005. *Performance parameters for grid-connected PV
  systems*. NREL Conference Paper NREL/CP-520-37358, 31st IEEE PVSC.
- Perez R., Ineichen P., Seals R., Michalsky J., Stewart R. 1990.
  *Modeling daylight availability and irradiance components from
  direct and global irradiance*. Solar Energy 44(5), 271-289. DOI :
  10.1016/0038-092X(90)90055-H.
- Reich N.H., Müller B., Armbruster A., van Sark W.G.J.H.M., Kiefer K.,
  Reise C. 2012. *Performance ratio revisited: is PR > 90% realistic?*.
  Progress in Photovoltaics 20(6), 717-726. DOI : 10.1002/pip.1219.
- Ross R.G. Jr. 1980. *Flat-plate photovoltaic array design
  optimization*. 14th IEEE PVSC, p. 1126-1132. JPL/NASA open access.
- Schoenau G.J., Kehrig R.A. 1990. *Method for calculating degree-days
  to any base temperature*. Energy and Buildings 14(4), 299-302. DOI :
  10.1016/0378-7788(90)90092-W.

## 12. Synthèse en un paragraphe

Cinq grandeurs F2 paramétrables (POA, productible avec correction
thermique, productible avec PR fourni, énergie utile ECS, degrés-jours
de climatisation) étendent l'API au-delà de la consultation de
séries pré-calculées vers le calcul à la volée à partir de paramètres
techniques fournis par l'appelant. Définition des familles : F1
(séries calculées et stockées ou à la volée), F2 (composants
paramétrables), F3 (modélisation système). Stratégie de calcul
`calculee_volee` uniforme, après les modules F1 ; un module dédié
par grandeur F2, pattern « 1 grandeur = 1 module ». Modèles retenus
en v1 : (10) **Perez 1990** pour POA avec fallback isotrope Liu-Jordan
lorsque DNI / DHI F1 sont indisponibles, modèles intermédiaires
HDKR / Hay-Davies différés, (11) **NOCT simple Ross 1980**
pour le productible thermique, Faiman + WS2M différés, (12) **PR brut
Marion et al. 2005 + PR_T temperature-corrected
Dierauf et al. 2013** via endpoint paramétré, PR_W et PR_C différés,
(13) **Hottel-Whillier-Bliss bord-capteur** pour
ECS avec f-chart Klein 1976 différée comme grandeur F3 future, (14)
**méthode moyenne journalière Erbs et al. 1983 + Schoenau & Kehrig
1990** pour DJC avec T_b utilisateur obligatoire, intégration horaire
livrée. Niveau de confiance dérivé `'B'` uniforme
comme choix éditorial pragmatique v1 reflétant la double dépendance
source F1 + paramètres utilisateur. Références primaires scientifiques
peer-reviewed et rapports publics privilégiées, contre les normes
payantes IEC / ISO / ASHRAE. Six
limitations transverses documentées (L-TR-1 à L-TR-6) dont les
répercussions du biais d'altitude (Fouta-Djalon) sur grandeurs avec T_amb
(#11, #12 en mode `correction='temperature'`, #13, #14), de la
réingestion NRT sur la stabilité temporelle des résultats F2, et du
biais de moyennage induit par la granularité journalière.
