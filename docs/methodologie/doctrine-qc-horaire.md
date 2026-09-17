# Note méthodologique - doctrine de contrôle qualité algorithmique des séries horaires

> Note méthodologique sur la validation horaire (cf.
> [`limites-substrat-physique-solaire.md`](limites-substrat-physique-solaire.md)
> §4.4). Patron : [`grandeurs-F2-phase-1.md`](grandeurs-F2-phase-1.md).
>
> Objet : fixer la **doctrine versionnée** de contrôle qualité (QC)
> algorithmique qui permet de **stocker** l'horaire NASA POWER 2001->,
> d'attribuer automatiquement un statut éditorial et un niveau de
> confiance, et de **lever le statut `passe_plat_non_valide`**.
>
> **Statut des seuils numériques** : les limites de plausibilité et les
> tolérances de comparaison sont **sourcées verbatim** du document
> *BSRN Global Network recommended QC tests V2.0* (Long & Dutton, source
> officielle BSRN/AWI). Restent à acter : la valeur numérique de S₀
> (constante solaire) et les seuils des tests temporels (§4.4), hors du
> jeu BSRN canonique.
>
> **Hypothèses structurantes** :
> stockage `TIMESTAMPTZ` UTC ; 6 grandeurs `ghi, dni, dhi, t2m, rh2m,
> kt` ; lot pilote avant ingestion de masse ; discriminant de
> granularité côté `series_metadonnees`.

## 1. Contexte et objet

L'horaire est aujourd'hui exposé en `passe_plat_non_valide` : relayé en
direct depuis NASA POWER, **non stocké, non validé**. La présente
doctrine le fait passer au statut de **donnée stockée et validée
éditorialement en confiance B**.

La volumétrie interdit la relecture humaine qui validait les séries
basse fréquence : 6 villes × 25 ans × 6 variables × 24 h ≈ **8 M de
points**. La validation devient nécessairement **algorithmique**, d'où
une doctrine explicite, versionnée et traçable, qui est elle-même un
**enrichissement de la machinerie éditoriale du Core**.

Cette note fixe : les familles de tests QC, leur ordre d'application,
les pré-requis géométriques, et la règle d'attribution automatique du
statut éditorial et du niveau de confiance.

## 2. Principe directeur et plafond de confiance

- Le QC algorithmique **automatise la plausibilité physique**, il ne
  constitue **pas** une vérité terrain. Plafond de confiance **B**. Le
  niveau **A** reste réservé au calage sol (régime terrain,
  [`limites-substrat-physique-solaire.md`](limites-substrat-physique-solaire.md)
  §4.8) : aucun test QC ne produit un A.
- La donnée horaire QC-passée prend le statut DB **`valide_auto`** (déjà
  présent dans le CHECK `statut` des tables `mesures_ressource*`, aucun
  nouvel enum requis) et `niveau_confiance_derive = 'B'`. Côté surface
  API, le service horaire sert désormais la donnée stockée validée ;
  `passe_plat_non_valide` n'est plus émis pour la plage couverte.
- La doctrine est **versionnée** (`v1`, `v2`…). Toute exécution QC trace
  la version de doctrine appliquée, pour que le verdict de chaque point
  soit reproductible et auditable.

## 3. Pré-requis géométriques

Les tests radiatifs reposent sur la position solaire, d'où l'ancrage
**UTC tz-aware** de la colonne instant (arbitrage chantier). Conventions
alignées verbatim sur BSRN (Long & Dutton) :

- **Angle zénithal solaire SZA**, et **μ₀ = cos(SZA)**, calculés par
  `pvlib` (`solarposition.get_solarposition`) à partir de (latitude,
  longitude, instant **UTC**). **Convention BSRN** : si SZA > 90°, μ₀
  est forcé à **0,0** dans les formules.
- **Constante solaire ajustée distance Terre-Soleil** :
  **Sₐ = S₀ / AU²** (S₀ = constante solaire à distance moyenne Terre-
  Soleil ; AU = distance Terre-Soleil en unités astronomiques). Obtenue
  via `pvlib.irradiance.get_extra_radiation` (S₀ défaut pvlib
  1366,1 W/m², *valeur à acter*).
- **Somme SW** (pour la fermeture, §4.2) :
  **Sum SW = DHI + DNI · μ₀**.

Le QC distingue **jour** (μ₀ > 0) et **nuit** (SZA > 90° → μ₀ = 0), les
bornes radiatives différant fondamentalement entre les deux régimes.

## 4. Familles de tests QC

Quatre familles, appliquées dans l'ordre, du plus dur (rejet physique)
au plus contextuel (cohérence, aberration).

### 4.1 Plausibilité physique par variable (limites BSRN, verbatim)

Tests ponctuels, une variable à la fois, à deux niveaux BSRN :
**« physiquement possible »** (violation = donnée impossible, rejet) et
**« extrêmement rare »** (violation = donnée suspecte, flag sans rejet).
Bornes reproduites verbatim de BSRN V2.0 (Long & Dutton). Unités W/m² ;
μ₀ = 0 si SZA > 90°.

| Variable | Niveau | Min | Max |
|---|---|---|---|
| **GHI** (Global SWdn) | phys. possible | −4 | Sₐ · 1,5 · μ₀^1.2 + 100 |
| GHI | extrêm. rare | −2 | Sₐ · 1,2 · μ₀^1.2 + 50 |
| **DHI** (Diffuse SW) | phys. possible | −4 | Sₐ · 0,95 · μ₀^1.2 + 50 |
| DHI | extrêm. rare | −2 | Sₐ · 0,75 · μ₀^1.2 + 30 |
| **DNI** (Direct Normal) | phys. possible | −4 | Sₐ |
| DNI | extrêm. rare | −2 | Sₐ · 0,95 · μ₀^0.2 + 10 |

Le document BSRN définit aussi SWup et le longwave (LWdn/LWup) : **hors
périmètre**, aucun flux de pyrgéomètre ni d'albédomètre horaire n'est
ingéré (l'albédo de surface est une grandeur brute journalière, pas un
flux horaire).

- **Régime nocturne** (SZA > 90°, μ₀ = 0) : les bornes hautes se
  réduisent à l'offset additif (GHI ≤ 100, DHI ≤ 50, DNI ≤ Sₐ). Une
  sentinelle `-999` reste traitée comme **lacune** (§4.4), pas comme un
  zéro physique.
- **T2M** : la plage de validité BSRN de la température de l'air est
  **170 K < Tₐ < 350 K** ; une borne climatique guinéenne plus serrée
  peut être posée en limite **configurable**. **RH2M ∈ [0, 100] %.**
- **KT** non défini la nuit -> `null` légitime (cohérent avec le
  passe-plat).

### 4.2 Relation de fermeture radiative (comparaison Global / Somme SW)

Test BSRN « Ratio of Global over Sum SW », verbatim, avec
Sum SW = DHI + DNI · μ₀ :

> (Global) / (Sum SW) à **±8 %** de 1,0 pour **SZA < 75°**,
> Sum SW > 50 W/m².
> (Global) / (Sum SW) à **±15 %** de 1,0 pour **75° < SZA < 93°**,
> Sum SW > 50 W/m².
> Pour Sum SW < 50 W/m², **test non applicable**.

Test conditionnel : non appliqué si une composante est lacune.

### 4.3 Cohérence inter-variables (ratio diffus, BSRN verbatim)

Test BSRN « Diffuse Ratio » :

> (DHI) / (GHI) < **1,05** pour **SZA < 75°**, GHI > 50 W/m².
> (DHI) / (GHI) < **1,10** pour **75° < SZA < 93°**, GHI > 50 W/m².
> Pour GHI < 50 W/m², **test non applicable**.

- **Indice de clarté** Kt = GHI / I₀ₕ ≤ 1 (marge d'« enhancement »
  nuageux ponctuel) : réutilise `calculer_indice_ciel_clair` / paramètre
  `ALLSKY_KT` déjà présent dans `external/nasa_power.py`.

### 4.4 Détection d'aberrations temporelles (complément hors BSRN V2.0)

Ces tests ne figurent **pas** dans le jeu BSRN V2.0 (qui est ponctuel :
limites + comparaisons). Ils constituent un **complément Kuma** dont les
seuils restent à fixer (configurables, documentés) :

- **Spikes** : variation horaire physiquement improbable entre deux pas
  consécutifs *[seuil à fixer]*.
- **Valeurs gelées (persistance)** : N heures consécutives identiques en
  plein jour *[N à fixer]*.
- **Lacunes** : sentinelles `-999` et trous temporels -> marquées
  **manquantes**, **non imputées** en v1.

Note : Long & Shi 2008 (QCRad) ajoute au-dessus du socle BSRN des
**limites configurables d'après la climatologie du site** ; piste
d'enrichissement ultérieure, non requise au lot pilote.

## 5. Attribution automatique du statut et du niveau

Attribution **par point horaire** (chaque ligne porte son verdict) :

| Issue des tests | Statut DB | Niveau | Trace |
|---|---|---|---|
| Tous les tests durs passés | `valide_auto` | `B` | version doctrine |
| Échec « extrêmement rare » seul | `valide_auto` + flag | `B` ou `C` *[à arbitrer]* | test flaggé en `commentaire_editorial` |
| Échec « physiquement impossible » | **non `valide_auto`** *(statut à arbitrer : `brut` conservé vs `deprecie`)* | - | test échoué tracé |

- **Décision de conception à acter** : les points qui échouent un test
  dur sont-ils **conservés flaggés** (cohérent avec le versioning non
  destructif `valide_du`/`valide_au`) ou **exclus** ? Recommandation :
  conservation flaggée, jamais de suppression silencieuse.
- Le niveau `B` est uniforme ; le QC ne crée pas de `A`.

## 6. Versionnement et traçabilité

- La doctrine (présente note + module service `services/qualite/`) est un
  **artefact versionné**. La version (`vX`) est inscrite dans chaque
  exécution.
- Chaque batch QC produit un **rapport traçable** : version de doctrine,
  date d'exécution, répartition des verdicts (% `valide_auto`, %
  flaggés, % impossibles) par variable et par localité.

## 7. Limitations et dettes

- Le QC ne lève pas le plafond de confiance B (pas de vérité terrain ;
  A = régime terrain).
- Les lacunes ne sont pas imputées en v1 (marquées manquantes).
  L'imputation est une piste ultérieure.
- Les limites BSRN sont fixées « pour accommoder toutes les latitudes et
  tous les régimes climatiques du programme BSRN » et « peuvent être
  affinées pour une latitude/climat spécifique » (Long & Dutton). Un
  raffinement tropical guinéen (limites configurables d'après
  climatologie locale, §4.4) est une piste ultérieure, non requise au
  lot pilote. Cohérent plafond B.

**À acter** : le sourcing verbatim des coefficients BSRN est fait
(BSRN V2.0 Long & Dutton, §4.1-§4.3) ; restent la valeur de S₀ (§3) et
les seuils des tests temporels (§4.4, complément hors BSRN).

## 8. Références

- Long C.N., Dutton E.G. *BSRN Global Network recommended QC tests,
  V2.0*. Baseline Surface Radiation Network (BSRN), AWI / WCRP. **Source
  verbatim des limites §4.1-§4.3** :
  `https://bsrn.awi.de/fileadmin/user_upload/bsrn.awi.de/Publications/BSRN_recommended_QC_tests_V2.pdf`
- Long C.N., Shi Y. 2008. *An Automated Quality Assessment and Control
  Algorithm for Surface Radiation Measurements*. The Open Atmospheric
  Science Journal **2**, 23-37 (PNNL / ARM ; algorithme QCRad
  encapsulant les limites BSRN + limites configurables par climatologie).
- pvlib - `solarposition`, `irradiance.get_extra_radiation` (SZA, μ₀,
  Sₐ).
- Cohérence avec la chaîne radiative déjà documentée
  ([`grandeurs-F2-phase-1.md`](grandeurs-F2-phase-1.md) : Perez 1990,
  Erbs 1982).

## 9. Évolution du document

| Date | Modifications |
|---|---|
| 2026-06-14 | Cadre algorithmique des 4 familles de tests + attribution ; coefficients BSRN à sourcer verbatim |
| 2026-06-14 | Limites §4.1-§4.3 remplacées par les valeurs verbatim BSRN V2.0 (Long & Dutton) ; restent à acter : S₀ (§3) et tests temporels (§4.4) |
