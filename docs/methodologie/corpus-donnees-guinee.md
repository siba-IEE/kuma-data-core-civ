# Corpus de données externes Guinée - inventaire et classement par substrat

> Statut : **inventaire** (état au 2026-06-17). Les données sont **locales et
> git-ignorées** (`data/guinee/`, 4,7 Go) ; ce document en est la **trace
> versionnée**, pas les données elles-mêmes.
> Objet : recenser le corpus externe Guinée rassemblé localement, le classer
> selon les **5 substrats Kuma**, et en tirer une lecture de **valeur** et de
> **périmètre**.
> Portée : inventaire et classement. **N'engage aucune ingestion ni migration.**
> L'exploitation solaire (passage confiance A terrain) relève de
> [`calage-terrain-solaire.md`](calage-terrain-solaire.md).

## 1. Provenance et volumétrie

Corpus déposé dans `data/guinee/` (dossier couvert par `data/` dans
`.gitignore` - local, non versionné). Après ménage du 2026-06-17
(suppression de 2 doublons octet-à-octet et d'un téléchargement Chrome
incomplet de 2,59 Go) : **50 documents** + un `README.md` de navigation,
**4,7 Go**.

Sources principales identifiées par consultation directe : campagne **ESMAP/WAPP
« Solar Development in Sub-Saharan Africa »** (Banque mondiale), **Global Solar
Atlas / Solargis**, **Global Electrification Platform (GEP/OnSSET)**,
**Renewables.ninja** (MERRA-2), **Africa Infrastructure Country Diagnostic /
WEPP** (réseaux, centrales), **RISE** (indicateurs de gouvernance), et un corpus
institutionnel guinéen (EDG, DNE/MEH, AGER, lois, tarifs, plans directeurs).

## 2. Grille des 5 substrats

Rappel de l'ossature (source : [`docs/architecture/01-vision.md`](../architecture/01-vision.md)
§ « substrats ») :

1. **Physique** - irradiation (GHI/DNI/DHI), température, humidité, vent. Moteur primaire.
2. **Infrastructure** - réseaux électriques, capacités installées, tarifs nationaux.
3. **Technologique** - caractéristiques réelles des équipements (modules, onduleurs, batteries).
4. **Économique** - coûts (LCOE), change, inflation, indicateurs macro.
5. **Usages** - profils de consommation et de charge par localité et par usage.

## 3. Classement par substrat

Chaque fichier est rangé sous son **substrat dominant** ; les bundles cohérents
(campagne WAPP, plateforme GEP) restent groupés. Sous-dossiers de `data/guinee/`.

| Sous-dossier | Substrat | Contenu (consulté) |
|---|---|---|
| `00-institutionnel-reglementaire/` (5) | *hors grille* | Loi L/2013/061 électrification rurale ; présentation secteur énergie (2012) ; piliers **RISE** accès/efficacité/renouvelable (gouvernance, scores pays par année) |
| `01-physique/` (16) | 1 Physique | **Campagne WAPP Kankan + Tarambaly** : 6 rapports (installation + mesures an 1 + rapport final an 2) + 4 CSV QC **pas 1 min** + 2 en-têtes ; **Global Solar Atlas** (PVOUT, température LTAy) ; **Solargis** classement potentiel PV pays |
| `02-infrastructure/` (12) | 2 Infrastructure | Sous-stations (17 pts), lignes **225 kV** ECREEE (66) et ECOWAS (1373) ; centrales (WEPP >10 MW, `SUM_MW`, `GEN_TYPE`) ; **plan directeur PREREC-2** ; rapports annuels **EDG** 2021 & 2024 (SAIDI/SAIFI) ; mini-réseaux **AGER/SEFA/BAD** ; **PAD** accès électricité (IDA, 25 M USD crédit + 25 M subvention) |
| `03-technologique/` (2) | 3 Technologique | `lcoe-database.xlsx` (LCOE par technologie PV/CSP/WON/WOF) ; « Demystifying the Costs » (World Bank PRWP 9303, 4000+ LCOE, 11 technos) |
| `04-economique/` (1) | 4 Économique | Tarifs électricité Guinée |
| `05-usages/` (14) | 5 Usages | **Plateforme GEP/OnSSET** (settlements, scénarios gn-2/gn-3, demande Santé/Éducation/Agri/Commerce par **Tier 1-5**, specs, descriptions de colonnes, styles) ; **Renewables.ninja** météo + vent (inputs GEP) ; rapport **gestion de la demande / efficacité énergétique** (PAESE) |

## 4. Recoupements multi-substrats

Le corpus **touche les 5 substrats** ; beaucoup de fichiers en croisent
plusieurs. Constats issus de la consultation :

- **`01-physique/` porte aussi du 3 technologique** : les rapports de station
  WAPP incluent un **sous-système d'encrassement PV** (modules de référence
  ModA/ModB, températures de module TModA/TModB, taux de salissure IEC 61724-1).
  Cf. l'addendum 2026-06-17 de [`calage-terrain-solaire.md`](calage-terrain-solaire.md).
- **`02-infrastructure/` porte du 3 et du 4** : `GEN_TYPE` (hydro/thermique) des
  centrales ; finances et investissements (EDG, mini-réseaux, PAD).
- **`05-usages/` porte du 1, 2 et 4** : les inputs GEP embarquent GHI, météo et
  vent (physique), distances réseau MV/HV (infrastructure), et LCOE
  mini-réseaux / investissements (économique). Le schéma GEP
  (`Description-of-output-columns_GEP_V2.docx`) est à lui seul transversal aux
  cinq substrats.
- **3 technologique sans source autonome** : aucun catalogue d'équipements
  (modules/onduleurs/batteries du marché africain). Les signaux technologiques
  sont **embarqués** ailleurs (soiling en `01`, `GEN_TYPE` en `02`, technos
  hybrides GEP en `05`) ; `03` ne contient que des **benchmarks de coût par
  technologie**, à la frontière techno↔économique.
- **4 économique presque vide en données *guinéennes*** : hormis les tarifs, le
  matériau économique est du **benchmark global** (LCOE génériques), pas des
  indicateurs macro guinéens.

## 5. Valeur pour le projet

Lecture désagrégée - « riche » ne signifie pas « exploitable maintenant » :

- **À l'échelle de la vision Kuma (long terme) : corpus très riche.** Couvrir les
  5 substrats avec de la mesure sol, du GIS réseau régional, un modèle
  d'électrification spatialisé et de l'économie est rare. Le **GEP/OnSSET**
  (`05-usages/`) est notable : *usages* est le substrat où Kuma n'a **rien**, et
  la demande sectorielle par localité ne se trouve pas aisément ailleurs.
- **Une seule pièce est décisive à court terme.** Les
  **mesures sol WAPP Kankan/Tarambaly** (`01-physique/`) sont probablement la plus
  précieuse acquisition externe pour l'objectif actuel : la couche **confiance A
  est volontairement vide** ([`calage-terrain-solaire.md`](calage-terrain-solaire.md)
  §1), et ces données en sont le premier chemin réaliste. DNI sur **pyrhéliomètre
  CHP1 thermopile** (qualité recherche) cale la correction aérosol CAMS ;
  pas 1 min, 2 ans, 2 stations, certificats d'étalonnage ; **open data
  Banque mondiale** qui contourne la négociation ANM.
- **Limites, à dire franchement** : 2 ans suffisent à **caler/bias-corriger**,
  pas à fonder un P50/P90 *bancable autonome* (porté par l'ossature satellite
  longue 2001-2023). Deux stations (Kankan Est, Tarambaly NW) ne couvrent ni le
  **Fouta-Djalon** (Labé/Mamou, biais altitude) ni la **côte Conakry** :
  calage par analogie, pas partout. Licence CC-BY-4.0 (World Bank Group, energydata.info).

## 6. Périmètre et discipline

**Un seul substrat est dans le périmètre courant** (`Kuma Solar Data`) :
le **1 physique**. Les substrats 2 à 5 sont différés jusqu'au
« solaire API-maximal » et à la validation terrain. **Ce corpus est une réserve
pour substrats futurs, pas du carburant immédiat** : aucune donnée
non-solaire n'est seedée avant arbitrage explicite. La richesse même du dossier
est un **risque de dispersion** à tenir : la discipline est de n'exploiter que la
tranche physique tant que le critère d'arrêt solaire n'est pas atteint.

## 7. Exploitation et suites

- **Solaire (1 physique)** : l'exploitation des stations WAPP (site-adaptation,
  zones-ancres, séquençage du lot terrain-lite GHI puis calage DNI) est déjà
  cadrée dans [`calage-terrain-solaire.md`](calage-terrain-solaire.md).
- **Licence** ESMAP/energydata.info : CC-BY-4.0 (World Bank Group)
  ; créditer le World Bank Group. Complétude fine des séries à vérifier.
- **Substrats 2 à 5** : laissés en réserve. Le jour où un substrat s'ouvrira
  (post-arbitrage), ce corpus fournit un point de départ documenté.

## 8. Références

- Données locales : `data/guinee/` (git-ignoré) et son `README.md` de navigation.
- [`calage-terrain-solaire.md`](calage-terrain-solaire.md) - doctrine terrain,
  zones-ancres, séquençage (exploitation du `01-physique/`).
- [`limites-substrat-physique-solaire.md`](limites-substrat-physique-solaire.md) -
  manques solaires et grille API/terrain.
- [`docs/architecture/01-vision.md`](../architecture/01-vision.md) - grille des
  substrats.
