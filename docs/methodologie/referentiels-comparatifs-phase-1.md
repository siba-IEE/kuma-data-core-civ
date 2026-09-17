# Référentiels comparatifs - note méthodologique

> Note méthodologique sur la sélection des atlas
> comparatifs et les méthodologies de comparaison. Elle fixe les
> références scientifiques mobilisables pour les 3 grandeurs F1
> `calculee_volee` (`ecart_relatif_referentiel`, `rang_referentiel`
> temporel et spatial). Périmètre : 6 villes pilotes guinéennes
> (Conakry-Kaloum, Kindia, Mamou, Labé, Kankan, Nzérékoré).

---

## Résumé exécutif

L'architecture multi-référence repose
sur trois choix complémentaires : (A) `ecart_relatif_referentiel` mesure
la divergence inter-source contemporaine NASA POWER 2021-2025 vs
PVGIS-SARAH3 ICDR 2021-présent, sur la base d'une validation empirique
ouest-africaine (Sawadogo et al. 2023, Kakou et al. 2025). (B)
`rang_referentiel_temporel` mesure la position climatologique de la
donnée dans la propre climatologie NASA POWER 1991-2020,
préservant la cohérence intra-source via le quantile mapping interne
POWER (Khadka et al. 2023, avec caveat documenté en limitation §5
ligne 15 sur la validation publique limitée au longwave). (C)
`rang_referentiel_spatial` mesure le rang ordinal 1-6 d'une localité
parmi les 6 villes guinéennes au même mois. CAMS-Rad écarté
avec cadre de référence quantitatif documenté pour une décision
de basculement éventuel après validation sol Guinée. Global
Solar Atlas conservé comme option utilisateur statique. NREL NSRDB et
ERA5 écartés. Quinze limitations méthodologiques documentées en §5,
adressées via mitigations ou trajectoire ultérieure.

---

## 1. Contexte

Kuma Data Core est un noyau de données pour l'ingénierie énergétique
appliquée à l'Afrique. Le socle couvre le
substrat physique guinéen, pilote sur six localités (Conakry-Kaloum,
Kankan, Kindia, Labé, Mamou, Nzérékoré) et six grandeurs ressource (GHI, DNI,
DHI, T2M, RH2M, KT) sur la plage 2021-01-01 → 2025-12-31, soit 65 718
mesures `mesures_ressource` et 1 614 dérivées `grandeurs_metier` au
moment de la rédaction. La source primaire de l'ingestion est NASA
POWER NRT (climat-quality 2021-2024, NRT pour 2025).

Trois grandeurs F1 `calculee_volee`
nécessitent l'introduction d'au moins une seconde source de référence
pour exister sémantiquement : `ecart_relatif_referentiel`,
`rang_referentiel` temporel et `rang_referentiel` spatial. Elles marquent
le passage du mono-source au **multi-référence** :
NASA POWER reste la source primaire
ingérée, mais une seconde source de référence (PVGIS-SARAH3) et une
fenêtre temporelle climatologique étendue (NASA POWER 1991-2020) sont
mobilisées pour la comparaison.

Le marché cible est l'Afrique francophone. La validation empirique
des atlas et la trajectoire de levée des limitations s'appuient sur les
publications peer-reviewed du domaine ouest-africain ; les références
US (NSRDB, SURFRAD) servent de cadre de référence quantitatif indicatif
hors zone, lu avec les caveats de §6.

---

## 2. Atlas de référence retenus

### 2.1 Architecture en trois décisions

| Calcul | Atlas / source retenu | Justification principale |
|---|---|---|
| `ecart_relatif_referentiel` | **PVGIS-SARAH3 ICDR 2021-présent** | Validation empirique Sawadogo et al. 2023 (Burkina Faso/Ghana, 37 stations) + Kakou et al. 2025 (Côte d'Ivoire, 52 stations) ; cohérence architecturale ; reproductibilité opérationnelle figée |
| `rang_referentiel` temporel | **NASA POWER 1991-2020** (rangement intra-source) | Sémantique propre : position de la donnée Kuma dans sa propre climatologie. Élimine biais inter-source CMSAF/CERES. Cohérence longitudinale assurée par quantile mapping interne POWER (Khadka et al. 2023) avec caveat GHI/LW documenté (cf. §5 ligne 15) |
| `rang_referentiel` spatial | **NASA POWER intra-périmètre Kuma 2021-2025** | Cohérence interne, classement relatif intra-source 6 villes, limite n=6 documentée |

### 2.2 Niveau de confiance sur les sources retenues

Application de la convention de séparation source / niveau de
confiance :

| Source | Méthode (fait) | Niveau de confiance |
|---|---|---|
| PVGIS-SARAH3 ICDR | Chaîne MAGICSOL CM SAF peer-reviewed (Urraca et al. 2017, 2018 ; Mueller et al. 2009, 2012), validation Afrique de l'Ouest (Sawadogo 2023, Kakou 2025) | `haute` |
| NASA POWER 1991-2020 | Fusion GEWEX SRB R4-IP + CERES SYN1deg Ed4.2 avec quantile mapping interne POWER (Khadka et al. 2023), validation peer-reviewed (Yang & Bright 2020, Quansah et al. 2022) | `haute` avec caveat §5 ligne 15 |

### 2.3 Tableau comparatif des cinq atlas examinés

| Critère | PVGIS-SARAH3 (retenu écart) | NASA POWER (retenu rang temporel + spatial) | CAMS-Rad (écarté) | Global Solar Atlas (option utilisateur statique) | NREL NSRDB (écarté) |
|---|---|---|---|---|---|
| Institution | Commission européenne, JRC, basé CM SAF / EUMETSAT | NASA Langley Research Center | ECMWF Copernicus, opéré par consortium DLR + ARMINES (MINES ParisTech) + Transvalor | World Bank / ESMAP / Solargis | DOE US, NREL |
| Méthode | Chaîne MAGICSOL CM SAF : Heliosat modifié (Hammer et al. 2003) + gnu-MAGIC broadband (Mueller et al. 2009, *Remote Sensing of Environment* 113(5):1012-1024) + SPECMAGIC spectral (Mueller et al. 2012, *Remote Sensing* 4(3):622-647) | GEWEX SRB R4-IP (1984 → 21 décembre 2009) + CERES SYN1deg Ed4.2 (2001-présent) + MERRA-2 météo ; quantile mapping interne POWER pour cohérence longitudinale via CDF matching par grid box 1°×1° sur fenêtre overlap 2001-2009 (Khadka et al. 2023, NTRS 20230017320) | Heliosat-4 (Qu et al. 2017) + McClear (Lefèvre et al. 2013) ; nuages via APOLLO_NG depuis CRS v4.5 (2022) | Solargis propriétaire multi-satellites | Physical Solar Model v4 (FARMS, REST2) sur GOES + Meteosat-1 |
| Résolution spatiale | 5 km (0.05°) | 100 km solaire (1° CERES) ; 55-69 km météo (0.5°×0.625° MERRA-2) | 11 km (0.1°) selon Kakou et al. 2025 | Jusqu'à 250 m | 4 km (Afrique via Meteosat-1) |
| Plage temporelle | CDR 1983-2020 + ICDR 2021-présent | 1984-présent (avec quantile mapping GEWEX SRB↔CERES SYN1deg sur overlap 2001-2009) | 2004-présent (service à la volée) | Meteosat Prime 1994, GOES/IODC 1999, MTSAT/Himawari 2007 | 2017-2019 Afrique (Meteosat-1) |
| Accès | API libre intégrale | API libre intégrale | Libre via Copernicus ADS | Cartes annuelles libres ; time-series payant | API libre avec clé obligatoire (inscription) |
| Validation peer-reviewed | Urraca et al. 2017, 2018 ; Mueller et al. 2009, 2012 | Yang & Bright 2020 ; Khadka et al. 2023 ; Quansah et al. 2022 | Qu et al. 2017 ; Lefèvre et al. 2013 | Rapport ESMAP/Solargis 29 novembre 2019 | Habte et al. 2017 (NREL/TP-5D00-67722, NREL/CP-5D00-70165) ; Sengupta et al. 2018 |

### 2.4 Justification des évictions

| Option | Raison d'éviction | Déclencheur de reconsidération |
|---|---|---|
| CAMS-Rad comme `ecart_relatif_referentiel` | Avantage théorique aérosols dynamiques non confirmé empiriquement comme supériorité sur SARAH-3 (Kakou 2025, Sawadogo 2023). Reproductibilité opérationnelle non figée. Plage 2004-présent insuffisante pour climatologie 1991-2020 | Cadre de référence - voir §6 |
| Global Solar Atlas | Time-series payantes incompatibles calcul à la volée | Évolution offre commerciale partenariale Banque Mondiale |
| NREL NSRDB | Plage Afrique 2017-2019 insuffisante (couverture Meteosat-1 limitée) | Couverture Meteosat-1 étendue NREL |
| NASA POWER comme atlas écart | Circulaire (NASA POWER vs lui-même) | Sans objet |
| SARAH-3 CDR 1991-2020 pour rang temporel | Glissement sémantique gênant entre source primaire (NASA POWER) et référentiel de rang (SARAH-3) ; biais inter-source CMSAF/CERES propagé dans le rang | Ré-ingestion éventuelle si exploration empirique de la divergence inter-source long-terme devient utile |
| ERA5 / ERA5-Land comme référentiel | Réanalyse (qualité moindre que satellite en Afrique de l'Ouest, cf. Sawadogo 2023) | Sans objet |
| Stratégie multi-atlas consensus | Plus robuste mais alourdit le socle | Validation locale sol |

---

## 3. Formules de calcul

### 3.1 `ecart_relatif_referentiel`

| Paramètre | Décision |
|---|---|
| Sémantique | Divergence inter-source contemporaine (NASA POWER vs SARAH-3 ICDR sur même fenêtre temporelle) |
| Formule | `(Kuma − SARAH-3_ICDR) / SARAH-3_ICDR × 100` (standard signée) |
| Pas temporel | Mensuel |
| Composante | GHI uniquement (couvre PV plan/trackers dominants Afrique Ouest ; DNI/DHI différés pour applications CSP marginales) |
| Décomposition saisonnière | Pas explicite ; le pas mensuel expose la saisonnalité par lecture du tableau |
| Sortie attendue | 6 villes × 60 mois = **360 lignes** |

### 3.2 `rang_referentiel` temporel

| Paramètre | Décision |
|---|---|
| Sémantique | Position de la donnée Kuma (NASA POWER) dans sa propre climatologie NASA POWER 1991-2020 |
| Distribution de référence | NASA POWER GHI 1991-2020 par localité, par mois calendrier |
| Justification fenêtre 1991-2020 | Convention climatologique OMM standard (intelligibilité bailleurs francophones AFD/CIRAD, comparabilité internationale) |
| Stratification | Mensuelle pure par mois calendrier (n=30 par mois) |
| Formule percentile | Type 7 numpy/R : `p = (rang − 1) / (n − 1) × 100` |
| Traitement hors plage | Capping 0/100 |
| Sortie attendue | 6 villes × 60 mois = **360 lignes** |

### 3.3 `rang_referentiel` spatial

| Paramètre | Décision |
|---|---|
| Périmètre | Intra-Kuma 6 villes guinéennes (NASA POWER) |
| Formule | Rang ordinal entier 1-6 |
| Pas temporel | Mensuel |
| Sortie attendue | 6 villes × 60 mois = **360 lignes** |

### 3.4 Cohérence inter-grandeurs F1

Les trois grandeurs externes ne partagent pas la même source de
référence par choix architectural :

- `ecart_relatif_referentiel` : référentiel = SARAH-3 ICDR (source extérieure).
- `rang_referentiel_temporel` : référentiel = NASA POWER 1991-2020 (cohérence intra-source).
- `rang_referentiel_spatial` : référentiel = pool NASA POWER 6 villes 2021-2025 (cohérence intra-source intra-périmètre).

Cette asymétrie est intentionnelle. Elle reflète la sémantique distincte
de chaque grandeur : la mesure d'une divergence inter-source pour
l'écart ; la lecture d'une position climatologique intra-source pour le
rang temporel ; le classement relatif intra-périmètre pour le rang
spatial. Le caveat est documenté en fiche méthodologique de chacune
des trois grandeurs.

---

## 4. Validation empirique en Afrique de l'Ouest

**Sawadogo et al. 2023** (*Renewable Energy* 216, 119066, DOI
10.1016/j.renene.2023.119066) évalue la performance hourly GHI de ERA5,
MERRA-2, CAMS et SARAH-2 sur 37 stations quality-controlled en Burkina
Faso et Ghana (publication finale ; le preprint SSRN 4152712 antérieur
portait sur 51 stations, révision du nombre entre preprint et version
publiée). SARAH-2 sort meilleur produit avec RMSE 15.18 % all-sky et
10.65 % clear-sky. L'étude évalue SARAH-2 et non SARAH-3 ;
l'extrapolation au successeur direct SARAH-3 est implicite mais
raisonnable au regard de la continuité méthodologique MAGICSOL et des
améliorations sur les inputs aérosols et vapeur d'eau.

**Kakou et al. 2025** (*Remote Sensing* 17(6), 998, DOI
10.3390/rs17060998) - auteurs P.-C.K. Kakou (Pierre-Claver Konin Kakou,
WASCAL Niamey), D. Laouali, B. Aka, J.A. Osei, N.F.K. Ette (SODEXAM),
G. Frey (Saarland University) - réalise une validation sur 52 stations
SODEXAM en Côte d'Ivoire (84 initiales → outlier removal → filtrage
missing days → 52 finales). CAMS et SARAH-3 sont comparables sous ciel
clair (rRMSD CAMS 11.4-33.3 %, SARAH-3 11.4-22.4 %). Sous ciel
nuageux : tous les produits surestiment fortement, jusqu'à rMBD 39.7 %
pour SARAH-3 et 35.9 % pour CAMS.

**Ouhechou et al. 2023** (*Atmospheric Research* 287, 106711) documente
une divergence systématique CMSAF (SARAH-2/3) vs CERES (NASA POWER) en
Afrique centrale, CMSAF étant systématiquement plus haut. La divergence
constatée est une propriété intrinsèque du choix de référentiel
SARAH-3 vs NASA POWER, et non un défaut isolé d'une des deux sources.

**Quansah et al. 2022** (*Scientific Reports* 12, 10684) valide NASA
POWER sur 22 stations synoptiques au Ghana et documente une
saisonnalité marquée de l'erreur, forte en saison sèche et plus faible
en saison humide.

**Yang & Bright 2020** (*Solar Energy* 210, 3-19) compare 8 produits
satellites et réanalyses à 57 stations BSRN sur 27 ans, à l'échelle
mondiale, et conclut à la supériorité du satellite sur la réanalyse
sous squared loss. L'étude évalue SARAH-2 ; aucune station BSRN n'est
située dans la bande latitudinale Guinée, ce qui limite la portée
directe pour le périmètre Kuma.

---

## 5. Limitations méthodologiques

Quinze limitations sont documentées (énumération exhaustive). Chaque
limitation est appariée à une mitigation ou à un déclencheur ultérieur.

| # | Limite | Mitigation |
|---|---|---|
| 1 | Biais aérosols Harmattan (déc-mars) - SARAH-3 ICDR (climatologie aérosols mensuelle CM SAF) et NASA POWER (variabilité dust faiblement résolue) | Déclencheur : basculement CAMS-Rad ou multi-atlas si la validation locale sol Guinée révèle un biais significatif |
| 2 | Biais d'altitude - paramétrisation Heliosat et résolution 100 km NASA POWER qui masque la topographie (Fouta-Djalon : Labé 1000 m, Mamou 750 m) | Levée avec validation sol |
| 3 | Biais sous ciel nuageux et couvert - Kakou et al. 2025 documente rMBD jusqu'à 39.7 % SARAH-3 sous cloudy-sky | Documenter par saison. Période sèche (déc-mai) plus fiable que humide pour la lecture du score |
| 4 | Statut ICDR vs CDR de SARAH-3 - consistance des inputs (ERA5 stable côté CDR vs IFS opérationnel côté ICDR) et latence 5 j de l'ICDR. Affecte uniquement `ecart_relatif_referentiel` | Documenter l'inhomogénéité d'inputs ICDR en fiche méthodologique |
| 5 | Hétérogénéité des résolutions et downscaling implicite - NASA POWER 100 km vs SARAH-3 5 km, facteur 20. L'écart relatif mesure partiellement une vraie divergence inter-source et partiellement l'inadéquation des résolutions | Documenter en fiche. Pas de downscaling explicite |
| 6 | Divergence systématique CMSAF (SARAH-3) vs CERES (NASA POWER) - Ouhechou et al. 2023 | Propriété du choix de référentiel. Latente dans `ecart_relatif_referentiel` ; éliminée dans `rang_referentiel_temporel` par cohérence intra-source NASA POWER |
| 7 | Saisonnalité de l'erreur NASA POWER - Quansah et al. 2022 | Documenter par saison en fiche |
| 8 | Choix de composante (GHI / DHI / DNI) - DHI biais positif et DNI biais négatif dans CERES | GHI retenu. DNI/DHI différés |
| 9 | Validation locale sol Guinée différée | Levée ultérieure |
| 10 | Nuance Yang & Bright 2020 - l'étude évalue SARAH-2 et conclut satellite > réanalyse uniquement sous squared loss | Documenter en fiche |
| 11 | Absence de validation BSRN spécifique à la Guinée - performance SARAH-3 extrapolée depuis Sawadogo 2023 et Kakou 2025 | Levée avec validation sol directe |
| 12 | Biais d'urbanisation / albédo local / végétation - écart entre stations BSRN/synoptiques (sites agricoles/semi-urbains) et pixels SARAH-3 5 km. Critique pour Conakry-Kaloum (urbain dense côtier) | Documenter avec mention spéciale Conakry-Kaloum |
| 13 | Extrapolation climatique Fouta-Djalon non couverte - Sawadogo 2023 (Burkina/Ghana soudanien sec), Kakou 2025 (Côte d'Ivoire tropical humide plaine). Aucune validation publiée pour zone montagneuse 700-1100 m (Labé, Mamou) | Levée avec validation sol Guinée Labé/Mamou |
| 14 | Cohérence longitudinale NASA POWER 1991-2020 via quantile mapping + mises à jour rétroactives - fusion GEWEX SRB R4-IP (couverture 1984 → 21 décembre 2009) + CERES SYN1deg Ed4.2 (2001-présent) avec quantile mapping interne POWER assuré par CDF matching grid box 1°×1° sur fenêtre overlap 2001-2009 (Khadka et al. 2023, poster AGU NTRS 20230017320). Cohérence assurée mais résiduelle. Par ailleurs, NASA POWER est mis à jour rétroactivement (passage Ed4.1 → Ed4.2 sur CERES SYN1deg) - les valeurs ingérées 2021-2025 pourraient avoir évolué depuis ingestion | Documenter le quantile mapping ; recommandation de snapshot timestampé pour ingestions critiques |
| 15 | Validation publique du quantile mapping NASA POWER limitée au longwave - la cohérence longitudinale NASA POWER 1991-2009 (GEWEX SRB R4-IP) / 2001-2020 (CERES SYN1deg Ed4.2) sur laquelle s'appuie `rang_referentiel_temporel` est documentée par Khadka et al. 2023 ; la validation publique de cette homogénéisation porte exclusivement sur le longwave (figures publiques, validations BSRN, tableaux RMSE). L'application au shortwave/GHI est affirmée par les auteurs (« the results are similar… although not shown ») mais non illustrée publiquement | Mitigation : vérification empirique de la cohérence GHI sur la fenêtre overlap 2001-2009 sur les 6 villes ; si cohérence dégradée, options de repli (restreindre la climatologie à CERES seul 2001-2020 hors convention OMM 1991-2020, ou ré-explorer SARAH-3 CDR avec note d'interprétation sémantique de l'asymétrie de source vs `ecart_relatif_referentiel`) |

---

## 6. Trajectoire ultérieure

### 6.1 Validation locale et bascule potentielle

- **Validation locale sol Guinée** - proxy d'étalonnage de la
  performance des atlas en zone guinéenne. Permet de trancher
  empiriquement le besoin de basculement CAMS-Rad ou multi-atlas, et
  particulièrement la levée des limitations §5 #1, #2, #9, #11, #13,
  #15, et mention spéciale Conakry-Kaloum (#12).
- **Validation indépendante via stations TAHMO** (Trans-African
  Hydro-Meteorological Observatory) - couverture ouest-africaine
  partielle, à explorer avant l'arrivée des données sol Guinée.
- **Vérification empirique de la cohérence GHI quantile mapping NASA
  POWER** sur la fenêtre overlap 2001-2009 sur les six villes (cf.
  §5 ligne 15).

### 6.2 Cadre de référence pour décision quantitative

Pas de seuil de bascule chiffré fixé ex-ante. Cadre de
référence indicatif construit à partir des publications NREL/IEA et lu
avec caveat :

- **Sengupta M., Xie Y., Lopez A., Habte A., Maclaurin G., Shelby J. 2018**
  (*Renewable & Sustainable Energy Reviews* 89, 51-60, DOI
  10.1016/j.rser.2018.03.003) documente pour le NSRDB un biais MBE GHI
  within 5 % annuel et MBE DNI < 10 % sur 9 stations (7 SURFRAD +
  SRRL + SGP) couvrant 7 régions climatiques US.
- **Habte A., Sengupta M., Lopez A. 2017** (NREL/TP-5D00-67722, avril
  2017, *Evaluation of the National Solar Radiation Database (NSRDB
  Version 2): 1998-2015*, Technical Report) - chiffres MBE/RMSE.
- **Habte A., Sengupta M. 2017** (NREL/CP-5D00-70165, *Best Practices of
  Uncertainty Estimation for the NSRDB (1998-2015)*, Conference Paper
  EU PVSEC Amsterdam 25-29 septembre 2017, rapport NREL publié
  décembre 2017) rapporte des incertitudes étendues NSRDB de 5-8 %
  annuel et 17-29 % horaire par méthode GUM U95 %.
- **IEA PVPS Task 16 / NREL / SolarPACES Task V 2024** (*Best Practices
  Handbook for the Collection and Use of Solar Resource Data for Solar
  Energy Applications*, 4ᵉ édition septembre 2024, NREL/TP-5D00-88300 +
  IEA-PVPS T16-6:2024, 570 pages, ISBN 978-3-907281-66-6, DOI
  10.2172/2448063) organise des benchmarks comparatifs internationaux
  selon une approche méthodologique GUM/ISO sans seuil universel
  normatif.
- **Caveat critique** : **Yang D. 2018** (*A correct validation of the
  National Solar Radiation Data Base (NSRDB)*, *Renewable and
  Sustainable Energy Reviews* 97, 152-155) signale que les validations
  Sengupta 2018 et Habte 2017 « appear to be incorrect, most likely
  due to a data-aggregation issue » et que l'incertitude réelle serait
  plus faible que celle publiée. Le cadre de référence ±5 % annuel /
  ±10 % mensuel est donc à lire comme **ordre de grandeur indicatif et
  non comme seuil normatif**.

Décision finale prise au moment de la disponibilité des premières
données sol Guinée, en confrontant le rMBD constaté à ces ordres de
grandeur documentés et à la pratique réelle.

### 6.3 Évolutions ultérieures

- Stratégie multi-atlas consensus (médiane SARAH-3 + CAMS-Rad ± NSRDB).
- Intégration Global Solar Atlas time-series via partenariat commercial Solargis.
- Extension géographique au-delà de l'Afrique de l'Ouest (réévaluer
  SARAH-3 pour Afrique centrale, cf. Ouhechou et al. 2023).
- Composantes DNI / DHI au-delà de GHI.
- Décomposition saisonnière formelle de l'erreur (sec / humide).
- Ré-ingestion éventuelle SARAH-3 CDR 1991-2020 si exploration
  empirique de la divergence inter-source long-terme devient utile.

---

## 7. Bibliographie consolidée

Énumération exhaustive - 17 références
peer-reviewed ou rapports officiels institutionnels.

1. Habte A., Sengupta M., Lopez A. 2017. *Evaluation of the National
   Solar Radiation Database (NSRDB Version 2): 1998-2015*. NREL
   Technical Report NREL/TP-5D00-67722, avril 2017.
2. Habte A., Sengupta M. 2017. *Best Practices of Uncertainty
   Estimation for the National Solar Radiation Database (NSRDB)
   (1998-2015)*. NREL Conference Paper NREL/CP-5D00-70165, EU PVSEC
   Amsterdam 25-29 septembre 2017 ; rapport NREL publié décembre 2017.
3. Hammer A. et al. 2003. Solar energy assessment using remote sensing
   technologies. *Remote Sensing of Environment* 86, 423-432.
4. IEA PVPS Task 16 / NREL / SolarPACES Task V 2024. *Best Practices
   Handbook for the Collection and Use of Solar Resource Data for
   Solar Energy Applications*, 4ᵉ édition septembre 2024,
   NREL/TP-5D00-88300 + IEA-PVPS T16-6:2024, 570 pages, ISBN
   978-3-907281-66-6, DOI 10.2172/2448063.
5. Kakou P.-C.K., Laouali D., Aka B., Osei J.A., Ette N.F.K., Frey G.
   2025. *Multi-Timescale Validation of Satellite-Derived Global
   Horizontal Irradiance in Côte d'Ivoire*. *Remote Sensing* 17(6),
   998. DOI 10.3390/rs17060998.
6. Khadka N., Stackhouse P., Patadia F., Mikovitz J.C., Zhang T.,
   Macpherson B. 2023. *Creating A Consistent Historical NASA POWER
   Solar Radiation Dataset to Support Renewable Energy, Building Energy
   Efficiency and Agro-Climatology Decisions*. Poster AGU Annual
   Meeting 2023, San Francisco, 11-15 décembre 2023, NTRS 20230017320.
7. Lefèvre M. et al. 2013. McClear: a new model estimating downwelling
   solar radiation at ground level in clear-sky conditions.
   *Atmospheric Measurement Techniques* 6, 2403-2418.
8. Mueller R., Matsoukas C., Gratzki A., Behr H.D., Hollmann R. 2009.
   *The CM-SAF operational scheme for the satellite based retrieval of
   solar surface irradiance - A LUT based eigenvector hybrid approach*.
   *Remote Sensing of Environment* 113(5), 1012-1024. DOI
   10.1016/j.rse.2009.01.012.
9. Mueller R., Behrendt T., Hammer A., Kemper A. 2012. *A New
   Algorithm for the Satellite-Based Retrieval of Solar Surface
   Irradiance in Spectral Bands*. *Remote Sensing* 4(3), 622-647. DOI
   10.3390/rs4030622.
10. Ouhechou A., Philippon N., Morel B., Trentmann J., Graillet A.,
    Mariscal A., Nouvellon Y. 2023. Inter-comparison and validation
    against in-situ measurements of satellite estimates of incoming
    solar radiation for Central Africa. *Atmospheric Research* 287,
    106711.
11. Qu Z. et al. 2017. Fast radiative transfer parameterisation for
    assessing the surface solar irradiance: The Heliosat-4 method.
    *Meteorologische Zeitschrift* 26, 33-57.
12. Quansah J.E. et al. 2022. Assessment of solar radiation resource
    from the NASA-POWER reanalysis products for tropical climates in
    Ghana. *Scientific Reports* 12, 10684. DOI 10.1038/s41598-022-14126-9.
13. Sawadogo W., Bliefernicht J., Fersch B., Salack S., Guug S., Diallo
    B., Ogunjobi K.O., Nakoulma G., Tanu M., Meilinger S., Kunstmann H.
    2023. Hourly global horizontal irradiance over West Africa: A case
    study of one-year satellite- and reanalysis-derived estimates vs.
    in situ measurements. *Renewable Energy* 216, 119066. DOI
    10.1016/j.renene.2023.119066. (37 stations dans la publication
    finale ; preprint SSRN antérieur portait sur 51 stations ; évalue
    SARAH-2.)
14. Sengupta M., Xie Y., Lopez A., Habte A., Maclaurin G., Shelby J.
    2018. The National Solar Radiation Data Base (NSRDB). *Renewable
    and Sustainable Energy Reviews* 89, 51-60. DOI
    10.1016/j.rser.2018.03.003.
15. Urraca R. et al. 2017. Extensive validation of CM SAF surface
    radiation products over Europe. *Remote Sensing of Environment*
    199, 171-186.
16. Urraca R. et al. 2018. Evaluation of global horizontal irradiance
    estimates from ERA5 and COSMO-REA6 reanalyses using ground and
    satellite-based data. *Solar Energy* 164, 339-354.
17. Yang D. 2018. *A correct validation of the National Solar Radiation
    Data Base (NSRDB)*. *Renewable and Sustainable Energy Reviews* 97,
    152-155.

Une 18ᵉ référence non comptabilisée dans la consolidation mais citée
ponctuellement : Yang D. & Bright J.M. 2020, *Worldwide validation of
8 satellite-derived and reanalysis solar radiation products*, *Solar
Energy* 210, 3-19.

---

## Annexe A - Conventions de naming pour les nouvelles séries

Les séries de référence respectent la
convention de naming `series_metadonnees.code`, pattern général
`<localite_alias>_<grandeur>_<source>_<plage>` :

- Extension temporelle NASA POWER 1991-2020 : 6 codes
  `gin_<ville>_ghi_power_1991_2020` (les 6 alias localité correspondent
  aux 6 villes pilotes, exception `gin_conakry` pour
  Conakry-Kaloum).
- Ingestion SARAH-3 ICDR 2021-2025 : 6 codes
  `gin_<ville>_ghi_sarah3_2021_2025`.

La nouvelle source ajoutée au référentiel `sources` porte le code
`sarah3_monthly` avec acknowledgement éditorial propagé dans le
`commentaire_editorial` des 6 séries SARAH-3.

---

## Annexe B - Composants introduits

| Composant | Périmètre | Sortie attendue |
|---|---|---|
| Ingestion étendue | Extension temporelle NASA POWER 1991-2020 mensuel GHI : 30 ans × 12 mois × 6 villes = 2 160 valeurs. Nouvelle source `sarah3_monthly` dans `sources`. Ingestion SARAH-3 ICDR 2021-2025 mensuel GHI : 60 mois × 6 villes = 360 valeurs | `mesures_ressource` +2 520 lignes, `series_metadonnees` +12 séries, `sources` +1 entrée |
| Calcul grandeurs métier externes | 3 grandeurs (`ecart_relatif_referentiel`, `rang_referentiel_temporel`, `rang_referentiel_spatial`) × 6 villes × 60 mois | `grandeurs_metier` +1 080 lignes, `grandeurs_referentiel` +3 entrées, `series_metadonnees` +18 séries calculées |
| Endpoints API FastAPI | `GET /series` listing + `GET /series/{code}` détail | listing + détail |

---

## Annexe C - Endpoints

L'orientation API est brute
générique, sans composite éditorial pré-mâché :

- `GET /series` - listing/découverte des séries disponibles avec
  métadonnées (code naming, libellé, localité, grandeur, source,
  période couverte, méthode de collecte, niveau de confiance).
- `GET /series/{code_serie}` - détail des mesures d'une série
  identifiée par son code naming (corps de mesures + métadonnées
  série + métadonnées source).
