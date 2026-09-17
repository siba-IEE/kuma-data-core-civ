# Substrat physique solaire - limites et grille de comblement

> Note méthodologique amont.
> Objet : qualifier ce que le substrat physique solaire couvre, ce qui lui manque, et comment chaque manque se comble.
> Périmètre : solaire / climat des 6 villes pilotes guinéennes (Conakry-Kaloum, Kindia, Mamou, Labé, Kankan, Nzérékoré). Hors périmètre : éolien, hydrologie, biomasse. Aucune valeur n'est ingérée par ce document.

## 1. Principe directeur - deux voies de comblement

Le substrat physique solaire s'enrichit par deux voies distinctes, séparées par la nature de la source et le plafond de confiance atteignable.

- **Voie API** : tout enrichissement par tirage d'API ou de réanalyse publique. Mobilisable sans dépendance terrain, plafond de confiance **B** (satellite / réanalyse / modèle).
- **Voie terrain** : tout enrichissement nécessitant une mesure sol (calage, vérité terrain), plafond de confiance **A**. Relève d'une enquête terrain documentée, hors flux web.

La quasi-totalité du registre de comblement ci-dessous relève de la voie API ; seuls le calage sol et la mesure réelle de salissure relèvent du terrain.

## 2. Verdict de suffisance

Le substrat physique solaire est **suffisant pour l'éditorial et le dimensionnement consultatif (premier et second ordre)**, et **insuffisant en l'état pour une étude engageante / bancable**.

Suffisant pour : caractérisation comparative de la ressource des 6 villes ; articles et notes méthodologiques ; dimensionnement PV de premier/second ordre via la chaîne livrée (GHI/DNI/DHI → POA Perez 1990 → correction thermique Ross NOCT 1980 → productible PR) ; solaire thermique ECS et degrés-jours de climatisation ; moyennes de ressource long terme et variabilité inter-annuelle au pas mensuel (base 30 ans 1991-2020 déjà ingérée comme série mensuelle).

Insuffisant, à ce stade, pour : une étude bancable (P50/P90 exposés, TMY horaire, calage sol) ; le bifacial (albédo + irradiance arrière) ; un PR réaliste saisonnier (salissure Harmattan) ; un modèle thermique dépendant du vent (Faiman 2008) ; la simulation horaire engageante (l'horaire reste `passe_plat_non_valide`).

Aucun de ces manques n'est un défaut de conception : ce sont des limites explicites, traçables et adossées à une voie de comblement.

## 3. Critère de tenabilité des sources (T1-T5)

Une source n'est seedable que si elle satisfait les cinq axes. L'échec sur un seul la renvoie en cross-check ou en exclusion.

| Axe | Question |
|---|---|
| T1 - Pérennité institutionnelle | Émetteur stable à 5-10 ans, mandat constant ? |
| T2 - Accessibilité citable | URL/DOI stable, archivable, licence claire, sans paywall bloquant ? |
| T3 - Cadence documentée | Fréquence de mise à jour connue et régulière ? |
| T4 - Provenance traçable | Méthode de collecte / d'estimation explicitée et publiée ? |
| T5 - Ingestibilité | API / format réingérable (au pire saisie manuelle tracée) ? |

Niveaux de confiance : **A** mesure sol primaire validée · **B** satellite / réanalyse / modèle · **C** presse / non-vérifié (jamais source citée).

## 4. Les manques, classés par voie de comblement

### 4.1 P50/P90 - voie API

L'exceedance probabiliste (P50, P90) n'est pas exposée ; une étude engageante raisonne en P90, pas en moyenne. Comblement par **voie interne** : dérivation directe depuis les 30 années mensuelles NASA POWER 1991-2020 déjà ingérées (série mensuelle, 360 points), par statistique inter-annuelle. Nouvelle grandeur F1 (`stockée` ou `calculee_volee`), coût marginal quasi nul. Ancrage externe possible : Global Solar Atlas (moyenne long terme ≈ P50). Limite à documenter : la voie interne ne propage que la composante inter-annuelle, pas l'incertitude de modèle ; ne pas présenter un P90 inter-annuel comme un P90 bancable.

> Vigilance : distinguer la **série mensuelle 1991-2020** (360 points, ingérée, base du P50/P90) de la **climatologie OMM 1991-2020** (12 normales mensuelles, non ingérée). Le P50/P90 s'appuie sur la série.

### 4.2 Vent + albédo - voie API

Le vent (refroidissement module ; soiling ; futur hybride) et l'albédo de sol (composante réfléchie POA ; futur bifacial) sont absents à ce stade. Comblement par **NASA POWER, même client `external.nasa_power`** : paramètres `WS2M`/`WS10M` et albédo de surface, mêmes granularités, radiation depuis 1984. Le levier est réel mais limité : la disponibilité du vent en API (confiance B) **ne suffit pas** à faire passer la grandeur F2 `productible_correction_thermique` de Ross NOCT à Faiman 2008 en API - les coefficients u0/u1 par défaut sont calibrés en climat désertique et leur transposition au tropical sans calibration locale produirait une fausse confiance B. Le calcul Faiman calibré est donc renvoyé à la voie terrain (§4.8), tandis que les données vent/albédo restent utiles pour la calibration future et pour préparer le bifacial.

### 4.3 Profondeur de la série journalière - voie API

Le journalier validé couvre ≈ 5 ans (2021-2025) alors que NASA POWER offre la radiation depuis 1984. Une base journalière courte fragilise les statistiques de variabilité au pas journalier. Comblement : réingestion historique NASA POWER `daily` sur fenêtre étendue (même client). Arbitrage profondeur vs coût de réingestion et latence NRT → climat-quality. Le P50/P90 mensuel (§ 4.1) reste, lui, déjà adossé à 30 ans.

### 4.4 Validation horaire + QC algorithmique - voie API (déverrouillage transverse)

L'horaire est `passe_plat_non_valide`. Le valider impose un **paradigme de validation algorithmique** (la volumétrie - 6 villes × 25 ans × plusieurs variables - rend impossible la relecture humaine des séries basse fréquence). Doctrine QC : contrôles de plausibilité physique (GHI borné par l'irradiance extraterrestre, valeurs nocturnes nulles, relation de fermeture GHI ≈ DHI + DNI·cos θz), tests de cohérence inter-variables type BSRN (Long & Shi 2008, Long & Dutton), détection d'aberrations, attribution automatique du niveau et du statut. L'horaire QC-passé reste en **confiance B** (statut dédié remplaçant `passe_plat_non_valide`) ; le A reste réservé au calage terrain. Déverrouille la grandeur DJC horaire, la simulation horaire consultative, et l'ossature temporelle du futur TMY terrain.

### 4.5 Aérosol / DNI Harmattan - voie API

Le DNI est très sensible aux aérosols ; le Harmattan (poussière sahélienne, surtout Haute-Guinée en saison sèche) déprime fortement le DNI. NASA POWER seul ne tranche pas l'incertitude aérosol. Comblement par **CAMS Radiation Service (Copernicus/ECMWF, Heliosat-4)** : GHI/DNI/DHI 2004→présent, prise en compte explicite des aérosols, couverture champ Meteosat incluant la Guinée, accès ADS/SoDa (quotas). Devient une **3ᵉ source de référence** dans la logique multi-référence (NASA POWER primaire ingéré, SARAH-3 puis CAMS en référence d'écart inter-source), particulièrement pour l'écart sur le DNI en saison Harmattan.

### 4.6 Incertitude documentée - voie API

Toutes les sources API sont satellite/modèle (confiance B). Sans station sol, l'incertitude systématique reste implicite. Comblement **sans terrain** : **AERONET** (sites ouest-africains régionaux - Dakar, Cinzana, Banizoumbou, Ilorin) caractérise/valide l'aérosol Harmattan en appui de CAMS. Conséquence : plafonner la confiance solaire à B et exposer une incertitude (via l'écart inter-source NASA/SARAH-3/CAMS).

### 4.7 ERA5-Land - voie API

Réanalyse Copernicus (9 km), contribue à la co-localisation Kindia/Mamou et à la correction d'altitude Fouta-Djalon avec une résolution intermédiaire entre NASA POWER (50 km) et SARAH-3/CAMS (5 km).

### 4.8 Voie terrain - TMY, calage sol, soiling mesuré

Restent explicitement en voie terrain (confiance A) :

- **TMY construit par ville, calé sol** : produit calculé (méthode ISO 15927-4 ou variante documentée), construit sur l'ossature horaire satellite longue (§ 4.4), calé par la mesure sol de chaque ville. Le calage sol règle au point de mesure réel ce que la résolution satellite ne capture pas (altitude Fouta, pixels côtiers Conakry, co-localisation Kindia/Mamou). Décision : ne pas produire de TMY satellite intermédiaire de qualité dégradée qu'il faudrait reconstruire. PVGIS TMY (5 km SARAH-3) peut servir de cross-check externe au moment du terrain.
- **Calage sol général** : stations sol nationales (accès à négocier), campagnes haute précision.
- **Soiling mesuré** : station de salissure / relevés terrain, seule voie primaire fiable pour le PR réaliste. Une voie API partielle existe (proxy EAC4 PM2.5/PM10 + pluie NASA POWER + modèle HSU Coello & Boyle 2019, confiance B ; le HSU consomme les PM de surface, pas l'AOD), mais la mesure réelle reste terrain.
- **Calcul thermique Faiman 2008 avec coefficients u0/u1 calibrés localement** : les défauts pvlib (`u0 = 25.0`, `u1 = 6.84`) sont calibrés sur des modules au Néguev désertique. Une calibration locale (mesures de température de module en Guinée, typiquement campagne dédiée ou adossée à des stations instrumentées) est nécessaire pour défendre un calcul Faiman en confiance A. Les données vent (`vent_2m`, `vent_10m`) sont ingérées et disponibles pour cette calibration future. Ross NOCT reste le modèle thermique exposé en API tant que la calibration n'est pas faite.

## 5. Tableau consolidé des sources

| Source | Rôle | Composantes | Voie | Confiance |
|---|---|---|---|---|
| NASA POWER | primaire ingérée (+ vent, albédo, profondeur) | GHI, DNI, DHI, T2M, RH2M, KT, WS2M/WS10M, albédo | API | B |
| PVGIS (SARAH-3) | référence + cross-check TMY terrain | GHI/DNI/DHI, TMY ISO 15927-4 | API | B |
| CAMS Radiation | 3ᵉ référence, DNI/aérosol | GHI, DNI, DHI | API | B |
| Global Solar Atlas | ancrage P50 long terme | GHI, DNI, PVOUT | API | B |
| ERA5-Land | co-localisation/altitude, vent/T d'appui | vent, T, etc. | API | B |
| AERONET | validation aérosol régionale | AOD | API | A (aérosol) |
| Stations sol nationales | mesure sol primaire (calage) | selon stations | **terrain** | A |
| Solargis / Solcast / Meteonorm | option bancable (P90, incertitude faible) | GHI/DNI/PVOUT + incertitude | commercial | B (bancable) |

## 6. Articulation avec l'architecture existante

- **Multi-référence** : NASA POWER unique source primaire ingérée ; SARAH-3 puis CAMS en référence d'écart inter-source. Aucune rupture.
- **Familles de grandeurs** : P50/P90 et soiling sont des F1 ; vent et albédo des brutes ; bifacial et Faiman des F2.
- **Convention endpoint** : toute nouvelle grandeur exposée par un endpoint le sera avec un `response_model` Pydantic typé.
- **Naming des séries** : `gin_<localite>_<grandeur>_<source>_<an_debut>_<an_fin>`.
- **Sources** : exposées côté catalogue, neutralisées côté surface consommateur.
- **Versioning temporel non destructif** : `valide_du` / `valide_au`.

## 7. Risques, limitations

1. **Confiance plafonnée B** sur tout le solaire tant qu'aucune mesure sol guinéenne n'est intégrée - à exposer explicitement (écart inter-source). Arbitrage de positionnement : consultatif premium B assumé (voie API) vs investissement terrain pour le bancable A (voie terrain).
2. **Pixels côtiers SARAH-3** (Conakry) potentiellement dégénérés → stratégie de fallback explicite requise pour la ville pilote n°1.
3. **Quotas CAMS/ADS** → batch et retry transverse à prévoir.
4. **P90 bancable** : la voie interne ne propage pas l'incertitude de modèle.
5. **Soiling** : pas de source libre tenable → proxy API confiance B puis mesure terrain.

## 8. Références

- NASA POWER - API & paramètres (DNI, albédo). Licence CC BY 4.0.
- PVGIS (JRC) - TMY ISO 15927-4 ; Huld et al., *Atmosphere* 2018, 9, 53.
- CAMS Radiation Service - Heliosat-4 (Qu et al., *Meteorol. Z.* 2017) ; accès ADS Copernicus / SoDa.
- Global Solar Atlas - ESMAP 2019, *Global Solar Atlas 2.0 Technical Report*, World Bank. CC BY 4.0.
- ERA5 - Hersbach et al. 2020 ; CDS Copernicus.
- QC radiatif - Long & Shi 2008 (BSRN), Long & Dutton.
- Modèles en place : Perez 1990, Liu-Jordan 1963, Ross 1980. Différés : Faiman 2008, Hay-Davies/HDKR. Soiling : Coello & Boyle 2019 (HSU).
