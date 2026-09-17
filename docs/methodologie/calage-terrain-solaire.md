# Calage terrain solaire - site adaptation, stations ESMAP/WAPP et stratégie de zones-ancres

> Note méthodologique **amont**, antérieure à toute mise en oeuvre.
> Objet : poser la doctrine et la méthode du passage **régime API (confiance B) → régime terrain (confiance A)** pour le substrat physique solaire, à la lumière de la disponibilité de stations sol open-data (ESMAP/WAPP). Préciser ce que le terrain débloque, ce qu'il ne débloque pas, et le séquencement.
> Périmètre : solaire / climat des 6 villes pilotes guinéennes, avec extension possible à l'Afrique francophone. Hors périmètre : éolien, hydrologie, autres substrats.

> **Données WAPP acquises localement.** Les fichiers bruts des deux stations
> guinéennes sont en main. Consultation directe → résolutions et nuance sur le
> présent document :
> - **Classe instrumentale** : DNI sur **pyrhéliomètre CHP1 (thermopile)**,
>   GHI/DHI sur **CMP10**, anémomètre #40C, girouette #200M, baromètre CS106
>   (certificats d'étalonnage en annexe des rapports d'installation). Donc **DNI
>   haute confiance**, pas un RSR shadowband - lève la réserve instrumentale de
>   §3 et §8.
> - **Format/cadence** : CSV **pas 1 minute** (525 k lignes/an), colonnes
>   GHI/DNI/DHI/Tamb/RH/WS/WSgust/WD/BP/Cleaning/Precipitation/TModA/TModB.
>   Compatible QC horaire après agrégation.
> - **Recouvrement** : Kankan 2021-10-18 → 2023-10 (an 1 + rapport final an 2,
>   avril 2024) ; Tarambaly idem.
> - **Nuance sur le soiling** : contrairement à l'hypothèse « ESMAP =
>   irradiance/météo seules », ces stations embarquent un **sous-système
>   d'encrassement PV** - deux modules de référence (ModA/ModB, sortie W/m²),
>   leurs **températures de module (TModA/TModB)**, un indicateur de nettoyage, et
>   un **taux de salissure mensuel/annuel rapporté (IEC 61724-1)**. Cela ne
>   remplace pas une station PV instrumentée (modules de référence, pas un parc ;
>   2 ans, 2 sites), mais l'affirmation « pas de température de module / soiling
>   non mesuré » est **à nuancer** : un signal d'encrassement et de température de
>   module *mesuré* existe à Kankan/Tarambaly, exploitable comme proxy local.
> - **Licence** : **Creative Commons Attribution 4.0 (CC-BY-4.0)**
>   (energydata.info, jeu Guinée), attribution standard, aucune restriction
>   supplémentaire → **source ingérable**.
> - **Localisation Tarambaly** (header xlsx réel) : **11.35600 N, −12.13706 W,
>   altitude 860 m**, démarrage 2021-10-24. Tarambaly est donc dans le
>   **Fouta-Djalon, à 16 km du point pilote Labé**, et **non** « NW
>   soudano-guinéen hors Fouta » comme l'indique le §5 : Tarambaly **comble
>   partiellement le trou altitude** près de Labé au lieu de le laisser béant - le
>   tableau zones-ancres §5 est à réviser.
> Reste à vérifier avant seed (§11) : complétude fine / trous des séries.

## 1. Objet et principe directeur

La grille API/terrain sépare deux régimes par la nature de la source et le plafond de confiance atteignable : **régime API** (satellite/réanalyse, plafond **B**, mobilisable maintenant) et **régime terrain** (mesure sol, plafond **A**, expansion ultérieure). La couche A est aujourd'hui **volontairement vide** : aucune mesure Kuma n'est en confiance A tant qu'une vérité sol guinéenne n'est pas intégrée.

Cette note pose **comment** se franchit ce palier. Le déclencheur est un fait nouveau : des stations sol **Tier-1 en accès ouvert** existent déjà pour la Guinée (campagne ESMAP/WAPP, cf. §2), ce qui rend le premier pas terrain **immédiat et gratuit** pour certains points - sans attendre la négociation avec l'agence météo nationale. La question centrale n'est donc plus « où trouver de la mesure sol » mais « **comment une mesure sol ponctuelle se propage-t-elle en un produit territorial défendable** ».

Principe directeur retenu : **le terrain ne remplace pas le substrat satellite, il le calibre.** Une station fournit une vérité de point ; le champ satellite/réanalyse fournit la couverture spatiale et temporelle. Le produit en confiance A est le **champ satellite corrigé par la station** (site adaptation), pas la station seule. La qualité du résultat dépend donc directement de la qualité du substrat B sous-jacent - ce qui justifie a posteriori la doctrine « pousser B au maximum avant le terrain ».

## 2. Déclencheur - disponibilité de stations sol open-data

Recensement consolidé par recherche éditoriale (juin 2026) sur le portail `energydata.info` (World Bank Group / ESMAP / WAPP) et les réseaux de référence Maghreb (enerMENA, BSRN). **Les coordonnées et périodes ci-dessous sont à valider fichier par fichier sur le portail avant tout seed** (cf. §11).

- **Campagne WAPP « Solar Development in Sub-Saharan Africa » (ESMAP)** : 22 stations Tier-1 dans 8 pays d'Afrique de l'Ouest, période 2021-2024, mesurant GHI, DNI, DHI, T2M, RH, pression, vitesse/direction du vent. Fichiers point-par-point téléchargeables.
- **Guinée - deux stations** :
  - **Kankan** (10.39° N, ~−9.31° W) : **co-localisée à < 2 km du point pilote Kuma `gin_kankan`** (10.383° N, −9.300° W) - même pixel CERES. Période 2021-10-18 → 2023-10-17.
  - **Tarambaly** (**11.356° N, −12.137° W, altitude 860 m** [header xlsx réel], **Fouta-Djalon, 16 km du pilote Labé**) : **nouvelle localité** (hors des 6 pilotes actuelles). Période 2021-10-24 → 2023-10-23. *(Corrige l'ancien « 11.41 / −11.91, NW Guinée », faux de 25 km - le rapport de station fait foi.)*
- **Réseau régional** : Bénin (Parakou, Malanville), Burkina (Dédougou, Dori, Kaya, Koupéla), Côte d'Ivoire (Korhogo, Sérébou), Mali (Sikasso, Bougouni, Fana, Sanankoroba, Manantali), Niger (Lossa, Maradi, Zabori), Sénégal (Tambacounda, Ourossogui), Togo (Dapaong, Davié). Couvre le gradient climatique côte (6,4° N) → Sahel (14° N).
- **Maghreb (hors périmètre Guinée)** : enerMENA (DLR + agences nationales, Kipp & Zonen CHP1/CMP21) et **BSRN Tamanrasset / Assekrem**. Climat désertique non transférable au tropical guinéen, mais Tamanrasset BSRN est un **benchmark possible de validation de l'algorithme QC** Kuma (la doctrine QC repose sur BSRN, Long & Shi 2008), et le réseau balise une expansion Maghreb future.

## 3. Critère de tenabilité ESMAP (grille T1-T5)

Application de la grille de tenabilité à la source ESMAP/WAPP :

| Axe | Évaluation ESMAP/WAPP | Verdict |
|---|---|---|
| T1 - Pérennité institutionnelle | World Bank Group / ESMAP, mandat stable | **fort** |
| T2 - Accessibilité citable | Portail `energydata.info`, licence ouverte (CC-BY-4.0 confirmée (World Bank Group)) | fort |
| T3 - Cadence documentée | Campagnes datées 2021-2024, fin de mesure connue | fort (record clos, pas de flux continu) |
| T4 - Provenance traçable | Campagne instrumentée Tier-1, méthodologie ESMAP publiée | **fort** |
| T5 - Ingestibilité | Fichiers point-par-point téléchargeables | fort (format réel à confirmer) |

Profil de tenabilité **fort**, supérieur à la négociation avec l'agence météo nationale en termes d'accès immédiat. Niveau de confiance de la mesure : **A** (mesure sol primaire), sous réserve de la classe instrumentale réelle (cf. §9, RSR vs thermopile).

## 4. Méthode - site adaptation et transfert spatial

### 4.1 Décomposition de l'erreur satellite

Le biais du satellite en un site se décompose en deux composantes au comportement spatial opposé :

- **Erreur régionale systématique** - partagée sur une zone climatique homogène (ex. sous-correction de l'aérosol Harmattan cohérente sur toute la Haute-Guinée ; offset de calibration de la chaîne CERES/Heliosat régionalement constant). **Transférable** par analogie climatique.
- **Erreur locale** - liée au pixel (relief, effet côtier, microclimat, altitude). **Non transférable**.

La transférabilité d'une correction de station dépend donc de (a) la part régionale vs locale de l'erreur au site, et (b) l'homogénéité climatique de la zone visée.

### 4.2 Familles de méthodes de correction (taxonomie site adaptation)

Au pixel de la station, sur la période de recouvrement, la correction du satellite peut se faire par ordre de raffinement croissant :

1. **Correction de biais (scaling)** - facteur additif/multiplicatif sur le biais moyen (MBD). Simple, robuste, suffisant en première approche pour le GHI.
2. **Correction de distribution (quantile mapping)** - alignement de la fonction de répartition satellite sur le sol. Corrige la forme de la distribution, pas seulement la moyenne - important pour le **DNI** (distribution fortement asymétrique, sensible aux aérosols).
3. **Correction par régression** - régression du sol sur le satellite avec covariables physiques (indice de clarté, élévation solaire, et surtout **AOD** pour le DNI). C'est là qu'intervient CAMS : l'AOD comme prédicteur de la correction DNI.

### 4.3 Transfert spatial

- **Une seule station** : on corrige le satellite à son pixel. La correction se transfère aux localités voisines **par analogie climatique** (même régime), mais **ne peut pas être validée de l'intérieur** - pas de second point pour vérifier. C'est le verrou épistémique : transfert *défendable* mais *non validé*.
- **Réseau de stations (cas ESMAP régional)** : la disponibilité de 22 stations sur le gradient climatique lève ce verrou. On peut modéliser **comment l'erreur varie dans l'espace climatique** (latitude, AOD, altitude) et la transférer par **regression-kriging** (le champ satellite comme dérive, résidus de stations krigés) ou par **correction zonale** (une correction par zone climatique, validée par ≥ 2 stations en zone). La **validation croisée leave-one-out** sur le réseau donne le résiduel attendu de la correction transférée.

### 4.4 Confiance résultante - doctrine proposée

Le calage ne produit pas un basculement binaire A/B sur toute une zone. Proposition de doctrine graduée, fidèle au principe « honnêteté méthodologique » :

- **Confiance A** : au pixel de la station, sur la période de recouvrement (mesure directe).
- **« B calibré »** : sur la zone climatique homogène, champ satellite corrigé, avec **résiduel documenté croissant avec la distance climatique** à la station. Honnêtement au-dessus du B brut, en dessous du A.
- **B brut** : hors zone homogène (au-delà de la frontière climatique).

Cette graduation s'articule avec la dérivation existante du `niveau_confiance` (4 axes : fiabilité, couverture spatiale, couverture temporelle, traçabilité). L'arbitrage précis (un nouveau niveau intermédiaire exposé ? un champ « résiduel de calage » ? un override éditorial ?) relève de la spec, pas de cette note.

## 5. Stratégie de zones-ancres pour la Guinée

Le bon objectif terrain n'est ni 1 station (insuffisante, non validable) ni 28 (irréaliste), mais **une station-ancre par zone climatique**, chacune ancrant une zone où son erreur dominante est régionale (donc transférable). Carte de couverture des 6 pilotes au regard du réseau ESMAP disponible :

| Zone Guinée | Régime climatique | Couverture par le réseau ESMAP |
|---|---|---|
| Intérieur soudanien Est (Kankan) | plat, ciel clair, Harmattan dominant | **A - station co-localisée** |
| **Fouta-Djalon NW / altitude (Tarambaly, 860 m)** | altitude 860 m, 16 km / 165 m sous Labé ville | **A** à son pixel ; **B-calibré** pour la zone Labé-Fouta (non co-localisé) - **analogue d'altitude** (nouvelle localité) |
| Frange Sudano-Sahel Nord | savane sèche | **B calibré** par analogues transfrontaliers (Tambacounda SN, Sikasso/Bougouni ML) |
| Sud forestier (Nzérékoré) | humide, forte nébulosité | **B calibré** par analogues partiels (Korhogo/Sérébou CI, Davié TG) |
| **Fouta-Djalon plateau (Labé ville, Mamou 782 m)** | altitude 800-1000 m, nuages orographiques | **partiellement couvert** - Tarambaly (860 m) fournit un **analogue d'altitude** : Labé en **B-calibré** (16 km, non co-localisé), Mamou partiellement approché (Labé ville + Mamou restent non co-localisés) |
| **Côte Conakry** | maritime, brise de mer, pixel côtier suspect | **trou** - aucune station côtière AO dans le jeu |

Kankan est de surcroît l'emplacement **le plus stratégique** pour le problème DNI/Harmattan : le Harmattan est surtout présent en Haute-Guinée en saison sèche - la station est posée là où l'erreur dominante est précisément régionale et transférable.

## 6. Ce que le terrain ESMAP débloque - et ce qu'il ne débloque PAS

Précision essentielle pour ne pas survendre : les stations ESMAP mesurent **l'irradiance et la météo** (GHI/DNI/DHI, T2M, RH, P, vent), **pas la physique PV**.

**Débloque** (calibration du substrat d'entrée → confiance A sur les brutes irradiance) :
- GHI, DNI, DHI corrigés et validés ;
- T2M, RH, vent au sol (appui co-localisation, validation MERRA-2 sur les zones couvertes).

**Ne débloque PAS directement** (instrumentation PV-spécifique requise, hors campagne ESMAP) :
- **Faiman 2008** : la calibration des coefficients u0/u1 exige des mesures de **température de module**, que les stations météo/irradiance ESMAP ne fournissent pas. Le vent ESMAP est utile mais ne suffit pas. Ross NOCT reste le modèle thermique API tant qu'une station PV instrumentée n'est pas disponible.
- **Soiling mesuré** : exige une station de salissure dédiée. Le proxy CAMS AOD + HSU reste la seule voie API.

Autrement dit, ESMAP fait passer en A **les inputs irradiance/météo** - le plus gros levier - mais les grandeurs dépendantes de la physique module (thermique avancé, soiling réel) restent au régime terrain dédié.

## 7. Séquencement

- **Terrain-lite GHI (faisable maintenant)** : ingérer Kankan + Tarambaly, leur appliquer le QC horaire BSRN **déjà construit**, et conduire un **pilote de site-adaptation GHI contre NASA POWER déjà ingéré**. Produit : première grandeur Kuma en **confiance A**. Aucune dépendance à CAMS.
- **Calage DNI** : dépend de **CAMS** comme champ aérosol-conscient à calibrer et comme covariable AOD de la régression. Séquence : terrain-lite GHI → CAMS → calage DNI.
- **TMY bancable** : construit sur l'ossature horaire satellite longue (2001-2023) **calée** par la station. Reste l'intégrateur terrain, en aval du calage GHI/DNI.

Le calage terrain ne casse pas la doctrine « API-maximal d'abord » : il la **réordonne localement**. Un premier pas A (GHI) peut précéder l'achèvement de l'API-maximal parce que la donnée terrain est devenue gratuite et immédiate. Le DNI bancable, lui, attend toujours CAMS.

## 8. Hypothèses et risques

1. **Stationnarité temporelle du biais** : la correction dérivée du recouvrement 2021-2023 n'est appliquée au satellite long (horaire 2001-2023, climato 1991-2020) que sous hypothèse de biais temporellement stationnaire. La chaîne CERES SYN1deg / MERRA-2 a évolué → hypothèse à tester sur la fenêtre de recouvrement, à documenter sinon.
2. **Profondeur de record 2 ans** : idéale pour *calibrer* (c'est l'input attendu du site adaptation), **insuffisante** pour un P50/P90 *bancable autonome* (qui reste porté par le satellite long calé).
3. **Représentativité** : un transfert au-delà de la zone homogène introduit un résiduel non borné par construction (verrou §4.3).
4. **Classe instrumentale** : thermopile (CHP1/CMP21, DNI direct haute précision) vs **RSR** (shadowband, DNI/DHI dérivés du GHI, précision DNI moindre). La confiance DNI en dépend directement.
5. **Pixels côtiers SARAH-3** (Conakry) potentiellement dégénérés et **non couverts** par le réseau → restent un trou explicite.

## 9. Articulation architecture

- **Nouvelle source** : ESMAP/WAPP entrerait dans la table `sources` (confiance A sur le mesuré), acknowledgement formalisé.
- **Nouvelle localité** : Tarambaly (**Fouta-Djalon NW, 860 m, 16 km de Labé** ; parent `gin_labe_region`) à seeder ; Kankan déjà présente (co-localisée).
- **Négociation agence météo nationale** : contournée pour Kankan/Tarambaly (open data), reste pertinente pour densifier (Fouta, côte) et allonger les records.
- **Altitude Fouta-Djalon** : partiellement instruite - Tarambaly (860 m, 16 km de Labé) fournit un **analogue d'altitude** (A à son pixel, B-calibré vers Labé) ; Labé ville + Mamou 782 m restent non co-localisés (cf. §5).
- **Co-localisation Kindia/Mamou** : une station locale la trancherait, mais aucune des deux n'est dans le réseau ESMAP.
- **Faiman** : non débloqué par ESMAP (pas de température de module). Reste régime terrain dédié.
- **Multi-référence** : ESMAP devient une référence d'écart **A** vis-à-vis du satellite B, distincte de SARAH-3/CAMS (références B inter-source).
- **QC** : Tamanrasset BSRN comme benchmark de validation de l'algorithme QC ; les stations WAPP comme vérité Tier-1 pour valider le QC horaire sur le tropical.
- **Versioning temporel** : le produit calé s'expose en versions non destructives (`valide_du`/`valide_au`), la version B brute restant consultable.

## 10. Verdict de suffisance

Le réseau ESMAP/WAPP est **suffisant pour amorcer la couche A sur l'irradiance** aux zones couvertes (Est intérieur, NW), et pour **calibrer/valider empiriquement le substrat B** ailleurs par analogie climatique. Il est **insuffisant** pour : le Fouta-Djalon et la côte Conakry (trous de couverture), le thermique Faiman et le soiling réel (instrumentation PV absente), un P50/P90 bancable autonome (record court). Aucun de ces manques n'est un défaut : ce sont des frontières explicites, adossées à un régime de comblement (densification agence météo, campagnes PV dédiées).

## 11. Vérifications préalables

1. **Licence** ESMAP/energydata.info : CC-BY-4.0 confirmée (fournisseur World Bank Group, source energydata.info). Attribution : créditer le World Bank Group.
2. **Classe instrumentale** par station (thermopile vs RSR) - détermine la confiance DNI.
3. **Métadonnées fines** : coordonnées exactes, altitude, identifiants WIGOS éventuels, complétude réelle des séries.
4. **Format des fichiers** et cadence (horaire ? sub-horaire ?) - compatibilité avec `mesures_ressource_horaires` et le QC BSRN.
5. **Recouvrement temporel** confirmé avec le journalier (2021-2025) et l'horaire (2001-2023) Kuma.
6. **Vérification bibliographique** des références §12 (DOI, années, volumes) avant intégration en fiche méthodologique.

## 12. Références (à confirmer en passe bibliographique)

- Site adaptation / MCP : Polo J. et al., *Solar Energy*, survey des techniques de site-adaptation (satellite/réanalyse) ; Cebecauer T. & Šúri M. (méthodologie Solargis). Années/volumes à confirmer.
- Modélisation DNI / aérosols : Gueymard C.A. (travaux sur le rayonnement direct et l'AOD).
- Contrôle qualité radiatif : Long C.N. & Shi Y. 2008 (BSRN) ; Long & Dutton (procédures BSRN).
- Interpolation spatiale : géostatistique / regression-kriging (Cressie, *Statistics for Spatial Data*).
- Classes de monitoring : IEC 61724-1:2021 (déjà seedée Kuma) - distinguer de la classification « Tier 1/2/3 » propre à ESMAP.
- Données : World Bank / ESMAP via `energydata.info` (campagne « Solar Development in Sub-Saharan Africa », WAPP) ; réseaux enerMENA (DLR) et BSRN (Tamanrasset/Assekrem) pour le Maghreb.
