# ADR-0012 : Triangulation DNI — SARAH-3 et ERA5 via PVGIS (`mr_dni`)

Date : 2026-09-28. Statut : accepté — **gravé** (migrations 0017-0020, 2026-09-28).

## Contexte

Le DNI n'avait que deux sources : NASA POWER (ADR-0007, migration 0009) et CAMS
Radiation (ADR-0011, migration 0014). Avec deux sources, un écart dit qu'il y a
désaccord, jamais **qui** dévie (même raisonnement qu'ADR-0010 pour le GHI). Or
l'écart CAMS − NASA est énorme (+31 à +78 %) : il faut savoir si c'est NASA qui
est bas ou CAMS qui est haut.

L'API PVGIS `MRcalc` (v5_3), déjà utilisée pour le GHI SARAH-3 (ADR-0008) et le
GHI ERA5 (ADR-0010), sert aussi le DNI mensuel : avec l'option **`mr_dni=1`**,
chaque mois porte le champ **`Hb(n)_m`** — « *Monthly beam (direct) irradiation
on a plane always normal to sun rays* », en **kWh/m²/mois** (métadonnées de la
réponse). Sondage du 2026-09-27, repris à la gravure du 2026-09-28 : 192 mois
2005-2020 sans trou, aux 3 points, pour `PVGIS-SARAH3` **et** `PVGIS-ERA5`.

## Décision

### Sources : `sarah3_monthly` (id 11) et `era5_pvgis` (id 16), réutilisées

`Hb(n)_m` vient **du même produit et de la même requête** que le GHI déjà gravé
de chaque source : la réponse porte `H(h)_m` et `Hb(n)_m`. On réutilise donc les
sources existantes, **sans nouvelle source ni nouvelle valeur d'énumération**.
Méthode `modele_satellitaire` pour SARAH-3, `reanalyse` pour ERA5 (valeur ajoutée
par la migration 0012).

**Preuve de continuité** : les ingesteurs, désormais paramétrés par grandeur
(GHI + DNI en une requête par point), régénèrent les seeds GHI SARAH-3 et ERA5
**identiques à l'octet** aux seeds gravés en 0010/0012 (`git diff` vide).

### Contrat de série brute (identique à ADR-0007/0008)

Grandeur `dni`, unité `kwh_par_m2_jour` héritée, granularité `mensuel`,
confiance **B**, statut `brut`, **couverture 2005-2020** (fenêtre commune des
sources DNI). **Conversion** : `Hb(n)_m` (kWh/m²/mois) ÷ jours du mois →
moyenne journalière (convention ADR-0008). Garde-fou 0 < DNI ≤ 9 kWh/m²/jour.

Résultat : **6 séries** brutes (2 sources × 3 points) × 192 mesures = **1152
mesures** (migrations 0017 SARAH-3, 0018 ERA5, 576 chacune).

### Deux grandeurs d'écart dérivées — NASA POWER au dénominateur commun

Même contrat qu'ADR-0009/0011 (`stockee`, `pourcent`, F1, matérialisées dans
`grandeurs_metier`, fenêtre commune stricte par jointure SQL, confiance B, 576
lignes chacune) :

1. **`ecart_relatif_dni_sarah3_nasa`** (id 39, migration 0019) —
   `(sarah3 − nasa) / nasa × 100` ;
2. **`ecart_relatif_dni_era5_nasa`** (id 40, migration 0020) —
   `(era5 − nasa) / nasa × 100`.

Avec `ecart_relatif_dni_cams_nasa` (0016), les **trois écarts DNI** partagent la
référence NASA POWER, comme les trois écarts GHI : un seul cadre de lecture.

### Caveats gravés

- **ERA5 est une source de comparaison, jamais une référence** (ADR-0010) : la
  réanalyse représente mal nuages et aérosols en Afrique de l'Ouest (Sawadogo et
  al. 2023). Elle reste la **seule classe de méthode indépendante de l'imagerie
  Meteosat**, d'où son intérêt pour la triangulation.
- **SARAH-3 et CAMS partagent l'imagerie Meteosat** : leur accord ne vaut pas deux
  avis indépendants (ADR-0011).

## Résultat de la gravure (2005-2020)

**DNI moyen** (kWh/m²/jour) et écart à NASA en **rapport des moyennes** de
période (`moy(source)/moy(nasa) − 1`) :

| Point | NASA | CAMS | SARAH-3 | ERA5 | CAMS − NASA | SARAH-3 − NASA | ERA5 − NASA |
|---|---:|---:|---:|---:|---:|---:|---:|
| Abidjan | 2,13 | 2,74 | 3,48 | 4,54 | +29,1 % | +63,9 % | +113,6 % |
| Yamoussoukro | 2,05 | 3,58 | 3,95 | 3,91 | +74,7 % | +93,2 % | +91,1 % |
| Korhogo | 3,07 | 4,55 | 5,06 | 5,58 | +48,2 % | +64,8 % | +81,9 % |

**Moyenne des ratios mensuels gravés** (ce que stockent les grandeurs), avec
DJF (décembre-février, Harmattan) et JJA (juin-août, mousson) :

| Point | Source | Moyenne | DJF | JJA | Minimum mensuel |
|---|---|---:|---:|---:|---:|
| Abidjan | CAMS | +31,5 % | +25,2 % | +38,2 % | −8,9 % |
| Abidjan | SARAH-3 | +66,7 % | **+90,8 %** | +57,0 % | +3,7 % |
| Abidjan | ERA5 | +124,6 % | +118,9 % | +151,1 % | +44,7 % |
| Yamoussoukro | CAMS | +78,1 % | +64,1 % | +85,3 % | +17,3 % |
| Yamoussoukro | SARAH-3 | +96,2 % | **+107,8 %** | +89,4 % | +41,4 % |
| Yamoussoukro | ERA5 | +97,7 % | +103,0 % | +105,1 % | +22,4 % |
| Korhogo | CAMS | +51,8 % | +45,6 % | +69,3 % | +18,4 % |
| Korhogo | SARAH-3 | +67,7 % | +74,5 % | +69,2 % | +27,2 % |
| Korhogo | ERA5 | +87,5 % | +80,2 % | +94,3 % | +35,2 % |

*Les deux statistiques diffèrent de quelques points (le DNI varie beaucoup d'un
mois à l'autre, cf. ADR-0009) ; seule la seconde est stockée en base.*

**Lecture (honnête, sans sur-interprétation) :**

- **Sur le DNI, NASA POWER est l'aberrant bas.** Les trois autres sources, dont
  deux classes de méthode distinctes (satellite Meteosat, réanalyse), sont au-dessus
  de NASA aux 3 points. SARAH-3 et ERA5 le sont **chaque mois** de 2005-2020
  (minimum mensuel positif partout) ; CAMS l'est sauf 3 mois sur 192 à Abidjan.
  C'est la question que 2 sources ne pouvaient pas trancher (ADR-0011).
- **Ce n'est pas pour autant que les trois autres sont justes** : entre elles,
  l'étalement reste large (à Abidjan, de +29 % pour CAMS à +114 % pour ERA5). CAMS
  est la plus basse des trois partout ; ERA5 la plus haute à Abidjan et Korhogo.
- **Le motif saisonnier dépend de la source.** L'écart culmine en saison sèche
  (DJF, Harmattan) pour SARAH-3 à Abidjan et Yamoussoukro, mais en mousson (JJA)
  pour CAMS partout et pour ERA5 à Abidjan et Korhogo. La lecture « l'écart DNI
  signe le Harmattan » n'est **ni confirmée ni infirmée** : elle dépend de la
  source comparée, donc de son traitement des aérosols et des nuages. Question
  ouverte.
- Seule une **mesure DNI au sol** (Jalon 4, confiance A) dira quelle source est
  juste en valeur absolue.

## Reproductibilité et accès

`scripts/ingest_pvgis_sarah3_mensuel.py` et `scripts/ingest_pvgis_era5_mensuel.py`
interrogent `MRcalc` avec `horirrad=1` et `mr_dni=1` (aucune clé), extraient
`H(h)_m` et `Hb(n)_m`, convertissent et régénèrent chacun deux seeds committés
(`series_pvgis_<source>_ghi_mensuel_civ`, `series_pvgis_<source>_dni_mensuel_civ`).
Les migrations lisent ces seeds **hors-ligne**.

## Conséquences

- **DNI à 4 sources** (NASA, CAMS, SARAH-3, ERA5), comme le GHI : la
  triangulation couvre les deux grandeurs solaires principales.
- **6 grandeurs d'écart** au total, toutes référées à NASA POWER.
- NASA POWER reste le **dénominateur conventionnel** de tous les écarts, même
  maintenant qu'il ressort comme aberrant bas sur le DNI : le dénominateur est une
  convention de lecture, pas un jugement de justesse. Changer de référence serait
  une nouvelle décision (nouvelles grandeurs), pas une correction de celles-ci.
- Pas de nouvelle source ni d'extension d'énumération.
