# ADR-0010 : triangulation GHI — 3ᵉ source ERA5 (réanalyse, via PVGIS)

Date : 2026-09-27. Statut : accepté.

## Contexte

ADR-0009 a gravé l'écart inter-source GHI SARAH-3 vs NASA POWER. Mais un écart
**à deux sources** dit *qu'il y a* désaccord (+6,6 à +16,6 %), jamais *qui*
dévie : SARAH-3 est-il trop haut, ou NASA POWER trop bas ? On ne peut pas
trancher avec deux points. Une **troisième source indépendante** le peut — si
deux sources concordent et qu'une diverge, l'aberrant est localisé.

Contrainte d'indépendance : NASA POWER (CERES, ~100 km) et SARAH-3 (Meteosat/
Heliosat CM SAF, ~5 km) sont **toutes deux satellitaires**. La 3ᵉ source doit
relever d'une **classe de méthode différente** pour que la triangulation soit
informative. Reconnaissance en lecture seule (2026-09-27) : la seule source
indépendante **joignable sans clé** pour la Côte d'Ivoire est **ERA5**
(réanalyse ECMWF), servie par l'API ouverte **PVGIS** (JRC) — même canal que
SARAH-3. CAMS (satellitaire, Heliosat-4, pertinent Harmattan) exigerait une clé
ADS ; ERA5-Land ne change pas la classe de méthode. Couverture PVGIS-ERA5
confirmée : **2005-2020** (démarre en 2005, comme SARAH-3), variable ``H(h)_m``
= irradiation mensuelle totale kWh/m²/mois, 192 mois/point.

## Décision

### Source : nouvelle `era5_pvgis`

ERA5 (réanalyse atmosphérique ECMWF / Copernicus C3S), **servie par PVGIS
(JRC)** via ``MRcalc``. Source **distincte** de `ecmwf_era5` (id 2, produit CDS
utilisé en co-localisation/météo) : on trace le **canal réel** (re.jrc.ec.europa.eu),
comme `sarah3_monthly` trace le portage PVGIS de CM SAF. `fiabilite='haute'`
(ERA5 est un produit de haute qualité) — la limite **régionale** du GHI de
réanalyse en Afrique de l'Ouest est portée en notes, pas par une dégradation de
`fiabilite` (elle ne changerait pas la confiance dérivée, cf. infra).

### Méthode : nouvelle valeur `reanalyse` de `methode_collecte`

ERA5 **n'est pas satellitaire** : c'est une **réanalyse** (modèle numérique
assimilant des observations). Aucune des 6 valeurs de `methode_collecte` ne la
décrit ; l'étiqueter `modele_satellitaire` serait faux et violerait la doctrine
« aucune donnée inventée ». On **étend l'énumération** (CHECK
`ck_series_metadonnees_methode_collecte_valide`) avec `'reanalyse'` — comblant
une lacune que la doctrine reconnaît déjà (la confiance traite « satellitaire
**ou de réanalyse** » comme une classe, cf. `confiance-et-statuts.md`, et les
sources ERA5/ERA5-Land/CAMS étaient déjà seedées). Modèle SQLAlchemy mis à jour
en miroir (`alembic check` sans drift).

**Confiance dérivée : B** — inchangée. R1-R4 : source `haute` (pas R1), pas
`expertise_humaine` (pas R2), pas `mesure_directe` (pas R3, A réservé au
terrain) → **R4 → B**. La réanalyse est B par doctrine.

### Contrat de série brute (identique à ADR-0008)

Grandeur `ghi`, unité `kwh_par_m2_jour` héritée, granularité `mensuel`,
confiance **B**, statut `brut`, **couverture 2005-2020** (fenêtre commune aux
trois sources). **Normalisation** ``H(h)_m`` (mensuel total) ÷ jours du mois →
moyenne journalière, déterministe et documentée (comme SARAH-3, ADR-0008).
Ingesteur reproductible ``scripts/ingest_pvgis_era5_mensuel.py`` → seed
``series_pvgis_era5_ghi_mensuel_civ`` ; migration 0012 le lit hors-ligne.

### Grandeur dérivée : `ecart_relatif_ghi_era5_nasa`

Deuxième écart inter-source, **même contrat qu'ADR-0009** (`stockee`, `pourcent`,
F1, matérialisée dans `grandeurs_metier`, fenêtre commune stricte par jointure
SQL, confiance B, 576 lignes, migration 0013). Formule `(era5 − nasa) / nasa ×
100` : **NASA POWER en référence commune** (dénominateur) — le même dénominateur
que `ecart_relatif_ghi_sarah3_nasa`, ce qui rend les deux écarts **directement
comparables** et permet la localisation (voir résultat).

## Résultat de triangulation (reconnaissance, GHI moyen 2005-2020)

| Point | ERA5 | NASA | SARAH-3 | ERA5 − NASA | SARAH-3 − NASA |
|---|---:|---:|---:|---:|---:|
| Abidjan | 5,00 | 4,66 | 4,97 | **+7,3 %** | +6,6 % |
| Yamoussoukro | 4,68 | 4,60 | 5,37 | **+1,8 %** | +16,6 % |
| Korhogo | 5,55 | 5,29 | 5,88 | **+4,9 %** | +11,1 % |

*(kWh/m²/jour ; écarts en rapport de moyennes de période. La grandeur stocke le
ratio par mois ; sa moyenne diffère à la marge, cf. ADR-0009.)*

**Lecture — l'aberrant change selon le point :**

- **Abidjan** : ERA5 (+7,3 %) et SARAH-3 (+6,6 %), deux **classes de méthode
  distinctes**, concordent → **NASA POWER est le point bas** ici.
- **Yamoussoukro** : ERA5 colle à NASA (+1,8 %) tandis que SARAH-3 s'envole
  (+16,6 %) → **SARAH-3 est l'aberrant haut** ici. Deux sources ne pouvaient
  pas le dire ; la troisième le tranche.
- **Korhogo** : étalement régulier, SARAH-3 le plus haut.

C'est précisément le savoir qu'une 3ᵉ source apporte : non pas « les sources
diffèrent » mais « **laquelle** diffère, et **où** ».

## Honnêteté : ERA5 est une source de comparaison, jamais une vérité

ERA5 a été **écartée comme *référentiel*** en Guinée (réanalyse de moindre
qualité que le satellite en Afrique de l'Ouest — Sawadogo et al. 2023, Yang &
Bright 2020). Cette décision n'est **pas contredite** : ici ERA5 n'est **pas**
une référence. C'est une **3ᵉ source de comparaison**, et ses limites régionales
documentées en font justement un test utile (classe de méthode réellement
indépendante), jamais le dénominateur. Le dénominateur reste NASA POWER. La
`note_publique` de la série et la description de la grandeur portent ce caveat :
un consommateur ne doit jamais lire ERA5 comme un sol.

## Conséquences

- Trois sources GHI cohabitent aux mêmes points sur 2005-2020 (deux
  satellitaires + une réanalyse), toutes en `ghi`/`kwh_par_m2_jour`/`mensuel`.
- Deux écarts partagent la référence NASA POWER → **triangulation lisible** en
  base : positionner les trois sources et localiser l'aberrant par (localité,
  mois).
- `methode_collecte` porte désormais `reanalyse` : première donnée de réanalyse
  gravée dans l'instance CIV, classe reconnue par le schéma.
- 3ᵉ écart symétrique (SARAH-3 vs ERA5) trivialement ajoutable si utile ; non
  gravé (les deux écarts vs NASA suffisent à localiser).
- Étendre à CAMS (satellitaire, Harmattan) reste ouvert dès qu'un accès ADS est
  disponible — 4ᵉ source, même contrat.
