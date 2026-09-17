# Calage DNI Kankan - biais satellite vs sol, 2 volets

> Note de calage (analyse seule - aucune migration, aucune écriture en base).
> Caractérise le biais du DNI satellite vs la mesure sol (ESMAP/WAPP,
> pyrhéliomètre CHP1, confiance A, migration 077) au pixel co-localisé de Kankan,
> sur deux produits satellite distincts : NASA POWER horaire et CAMS mensuel.
> Chiffres reproductibles par
> [`scripts/analyse_calage_dni_kankan.py`](../../scripts/analyse_calage_dni_kankan.py).

## 1. Données et méthode

- **Sol** : `gin_kankan_dni_esmap_wapp_2021_2023` (CHP1, confiance A, 17 520 h).
- **NASA POWER horaire** : `gin_kankan_dni_nasa_power_2001_2023` (ALLSKY DNI
  horaire, B). 17 520 paires en inner join sur l'instant ; **heures de jour
  élévation ≥ 5°** (8 346) ; convention **biais = NASA − sol** ; MBD/RMSD, par
  saison, avec/sans « rare », stationnarité an 1/an 2.
- **CAMS mensuel** : `gin_kankan_dni_cams_2021_2023` (CAMS DNI aérosol-corrigé,
  mensuel, kWh/m²/jour, B). Sol agrégé **mensuel kWh/m²/jour** (Σ Wh/m² ÷ 1000 ÷
  jours), **mois pleins n_jours ≥ 28** ; **23 mois** appariés (oct-2021 et
  oct-2023 partiels exclus) ; convention **offset = CAMS − sol**.
- **Saisons (mois UTC)** : Harmattan `{11,12,1,2,3}`, mousson `{6,7,8,9}`,
  intersaison `{4,5,10}`.

## 2. DNI sol vs NASA POWER (horaire, heures de jour)

| Sous-ensemble | n | sol (W/m²) | NASA | **MBD** | **%** | RMSD | % |
|---|---|---|---|---|---|---|---|
| **Global jour** | 8 346 | 331.2 | 317.2 | **−14.0** | **−4.2 %** | 136.9 | 41.3 % |
| Harmattan (11-3) | 3 256 | 438.5 | 436.5 | −2.0 | −0.5 % | 116.2 | 26.5 % |
| Mousson (6-9) | 2 928 | 229.2 | 208.0 | −21.2 | −9.3 % | 155.0 | 67.6 % |
| Intersaison (4,5,10) | 2 162 | 307.6 | 285.4 | −22.2 | −7.2 % | 139.4 | 45.3 % |
| sans « rare » | 8 346 | 331.2 | 317.2 | −14.0 | −4.2 % | 136.9 | 41.3 % |
| an 1 | 4 173 | 329.4 | 312.0 | −17.4 | −5.3 % | 138.3 | 42.0 % |
| an 2 | 4 173 | 333.0 | 322.4 | −10.6 | −3.2 % | 135.4 | 40.7 % |

**Lecture.** NASA POWER **sous-estime** le DNI sol de **−4.2 %** en moyenne, mais
le biais moyen est **proche de zéro en Harmattan (−0.5 %)** et plus marqué en
mousson (−9.3 %). Le **RMSD est très élevé** (41 % global, **68 % en mousson**) :
le DNI horaire est extrêmement sensible aux nuages (un passage nuageux annule le
faisceau direct) - la dispersion instantanée domine, le biais *moyen* reste
exploitable. Les 85 h « rare » sont toutes hors heures de jour → aucun effet.
Stationnarité : −5.3 % (an 1) → −3.2 % (an 2), même signe, variation 2 points.

## 3. DNI sol vs CAMS (mensuel, kWh/m²/jour)

| Sous-ensemble | n mois | sol | CAMS | **offset** | **%** | sd | se |
|---|---|---|---|---|---|---|---|
| **Global** | 23 | 3.84 | 4.93 | **+1.09** | **+28.4 %** | 0.38 | 0.08 |
| Harmattan (11-3) | 10 | 4.78 | 5.95 | +1.17 | +24.6 % | 0.38 | 0.12 |
| Mousson (6-9) | 8 | 2.76 | 4.03 | +1.27 | +46.1 % | 0.23 | 0.08 |
| Intersaison (4,5,10) | 5 | 3.69 | 4.32 | +0.63 | +17.0 % | 0.18 | 0.08 |

**Lecture.** CAMS **sur-estime** le DNI sol de **+28 %** en moyenne (+25 % en
Harmattan, +46 % en mousson). L'erreur-type est **petite** (se 0.08-0.12) : l'offset
est **robuste** malgré n = 23. C'est un **contrôle d'offset systématique à
résolution mensuelle, PAS une validation haute-résolution** de la correction
aérosol CAMS.

## 4. Lecture croisée - un biais HAUT systématique de CAMS, pas un défaut aérosol

Constat central, **sans anticiper le signe** : les deux satellites racontent des
histoires **opposées** - **NASA POWER ≈ sol** (−4 %, quasi nul en Harmattan) ;
**CAMS très au-dessus** (+28 %). Recoupement de cohérence : le DNI NASA mensuel
reconstitué (≈ 331 W/m² × 11,6 h ≈ **3,7 kWh/m²/jour**) ≈ sol (3,84) **≪ CAMS
(4,93)** → CAMS est au-dessus du sol **ET** de NASA POWER, pas l'artefact d'un seul
produit.

**L'offset CAMS−sol est un biais ABSOLU ~constant, pas un défaut saisonnier.** En
valeur absolue : Harmattan **+1,17**, mousson **+1,27**, intersaison +0,63 (n=5),
global **+1,09 kWh/m²/jour**. **Il n'est PAS plus fort en Harmattan** (≈ mousson) :
si l'écart venait de la **correction aérosol** de CAMS, il **culminerait en saison
de poussière** - ce n'est pas le cas. Les pourcentages varient (+24,6 % Harmattan
vs +46,1 % mousson) **seulement** parce que la baseline DNI sol chute en mousson
(2,76 vs 4,78 kWh/m²/jour) : **même offset absolu, % mécaniquement plus haut**.
**Diagnostic : un biais HAUT de fond de CAMS, indépendant de la saison aérosol -
pas un échec de sa correction Harmattan.**

> **Nuance par le test ciel-clair.** Le test du socle
> ([`clear-sky-dni-kankan-socle.md`](clear-sky-dni-kankan-socle.md)) raffine ce
> diagnostic. Sur les **heures détectées claires** (DNI sol vs CAMS BNIc, n=892),
> le socle ciel-clair sur-estime de **+9,6 %**, et il **EST aérosol-shaped** :
> **+12,6 % en Harmattan, 0 % en mousson**. La conclusion « pas un défaut
> aérosol » ci-dessus portait sur l'**offset absolu mensuel** (qui paraît
> constant) - mais il paraît constant parce que le **sur-biais nuageux de la
> mousson compense le socle plus faible** de cette saison. Donc : il **y a** un
> défaut aérosol dans le socle (+10-13 % en Harmattan), simplement **minoritaire**
> dans le +28 % mensuel, dont le gros vient du **traitement nuages**. Le constat
> « CAMS DNI inutilisable en absolu sans correction sol » est **inchangé**.

## 5. Le DNI sol est fiable - réfutation de l'hypothèse soiling

Le DNI sol n'est **pas** tiré bas par l'encrassement, sur la foi du **rapport de
station** (donnée primaire) :

- **Le CHP1 est nettoyé et maintenu.** « Local subcontracted staff **in charge of
  the maintenance and sensor cleaning of the solar irradiation sensors** », **tests
  qualité quotidiens** (« daily data quality tests »), journal de nettoyage à
  bouton-poussoir horodaté. Le pyrhéliomètre n'est **pas un capteur soillé**.
- **Le « soiling » mesuré par la station, c'est les modules PV** (ModA/ModB,
  « reference PV module for the soiling measurement ») - un **instrument
  différent**, déployé pour quantifier la salissure des **panneaux**, pas pour
  corriger le CHP1. **Corriger le DNI sol du soiling serait une erreur de
  catégorie.**
- **Le CHP1 est calibré** (certificats ch. 10, étalonnage à l'installation + an 2).
- **Le motif est anti-soiling** : le soiling s'**accumulerait entre nettoyages**
  (biais **croissant/variable**), pas l'offset **plat et stable en absolu** observé.

→ **Le DNI sol est la référence fiable** ; l'offset est donc, très probablement, un
**sur-biais réel de CAMS** (corroboré par NASA POWER ≈ sol ≪ CAMS).

## 6. Caveats résiduels honnêtes

Ce qui **tempère** (sans renverser) le constat :

- **Point vs pixel** : le CHP1 est une **mesure ponctuelle** ; CAMS une moyenne de
  **pixel (3-5 km)**. Une part de l'écart peut être de la représentativité
  spatiale (faible pour le DNI en terrain plat, non nulle).
- **n = 23 mois, résolution mensuelle** : offset systématique **robuste** (se
  0,08-0,12), **pas** une validation fine de l'algorithme CAMS.
- **Désalignement matinal du traqueur** [rapport] : pour les timestamps du matin
  avant alignement, le DNI sol est **calculé depuis GHI/DHI** (fermeture), non
  mesuré direct - fraction faible, soleil bas, **immatériel** sur l'offset (dominé
  par les heures de plein midi à forte énergie).

## 7. Portée

- **CAMS DNI (référence aérosol-corrigée) sur-estime systématiquement le
  DNI sol** (+1,1 kWh/m²/jour, +28 %) au pixel Kankan.
- Ça **n'invalide PAS** l'écart inter-source `ecart_relatif_dni_cams` :
  mesure **relative** (NASA−CAMS), insensible à un offset absolu commun.
- Ça **recadre l'usage de CAMS comme « vérité » DNI absolue** : tout futur
  **B-calibré** ou usage de CAMS DNI en valeur absolue doit **intégrer cet offset**.
- Terme d'incertitude absolu désormais **mesuré** au pixel Kankan pour le DNI :
  **NASA −4 %, CAMS +28 % vs sol**.

## 8. Bornes

- **Confiance A** : au **pixel Kankan**, 2021-2023 (mesure sol). Ce calage
  **caractérise** le biais DNI des deux satellites à ce pixel.
- **B-calibré zonal non câblé** ; **aucune propagation** au record long
  ni aux autres localités.
- Stationnarité sur le record long non validée (NASA POWER : 2 points de
  variation interannuelle).

## 9. Suites possibles (hors de cette note)

- Comparaison **clear-sky ciblée** (heures sans nuage) pour isoler la composante
  aérosol vs le biais de fond et **expliquer** la cause du +28 % CAMS.
- Confrontation **point/pixel** (autres stations du réseau) pour borner la
  représentativité spatiale.
- Transfert **B-calibré zonal** (doit intégrer l'offset CAMS) ; **Tarambaly**
  (dès métadonnées admin confirmées).

## 10. Références

- Calage GHI (miroir) : [`calage-ghi-kankan-terrain-lite.md`](calage-ghi-kankan-terrain-lite.md).
- Doctrine : [`calage-terrain-solaire.md`](calage-terrain-solaire.md).
- Rapport station (donnée primaire) : `csps-yls_wapp_stationmeasurementreport_guinea-kankan_2023-10-18-final_fr_en.pdf` (nettoyage capteurs, calibration, désalignement matinal).
- Script : [`scripts/analyse_calage_dni_kankan.py`](../../scripts/analyse_calage_dni_kankan.py).
