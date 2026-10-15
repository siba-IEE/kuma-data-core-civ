# Fiche méthodologique - `variabilite_journaliere` (Indice de variabilité journalière)

> Conventions communes : voir fiche HEP `hep.md`.
>
> Les §§ 7.1 et 8.2 décrivent le périmètre de l'instance d'origine
> (Guinée). L'application à la Côte d'Ivoire est au § 9.

## 1. Identification

| Champ | Valeur |
|---|---|
| Nom | Indice de variabilité journalière (coefficient de variation) |
| Code métier | `variabilite_journaliere` |
| Unité | sans dimension |
| Famille | F1 - fait stocké |
| Stratégie de calcul | `stockee` (persistée dans `grandeurs_metier`) |
| Version courante | 1 |
| Périodicités exposées | **annuel uniquement** (cf. § 4) |

## 2. Définition formelle

Coefficient de variation (CoV) du GHI journalier sur une année :

```
CoV(annee) := sigma(GHI_jour sur annee) / mu(GHI_jour sur annee)
```

Avec sigma = écart-type de population (`ddof=0`, divisé par N), mu =
moyenne arithmétique. Indicateur statistique standard sans dimension.

## 3. Source amont

`ghi` journalier NASA POWER (paramètre `ALLSKY_SFC_SW_DWN`).

## 4. Périodicité annuelle uniquement

Pas de calcul mensuel. Justification : un mois (28-31 jours) est
statistiquement peu robuste pour un coefficient de variation qui
demande typiquement N ≥ 30 observations. Année (365-366 jours)
satisfait cette condition.

## 5. Politique de complétude

Stricte 100% jours civils v1 (héritée fiche `hep.md` § 4). Si une
année manque un jour de GHI, l'année est skipped.

Garde-fou supplémentaire : si `mean(GHI)` ≤ 0 sur la période (cas
pathologique non observable), l'année est skipped (CoV non défini).

## 6. Interprétation

- CoV 0.15 - climat très stable (équatorial humide, irradiation
  régulière toute l'année).
- CoV 0.25 - climat à transition saisonnière marquée (côtier tropical).
- CoV 0.40+ - climat à forte variabilité (latitudes moyennes,
  transitions été/hiver).

Utilité éditoriale principale : **dimensionnement de systèmes avec
stockage** (CoV élevé → besoin de stockage plus grand pour lisser la
production).

## 7. Limites et portée

### 7.1 Co-localisation Kindia / Mamou

`variabilite_journaliere` consomme GHI directement. Kindia et Mamou
partagent le même pixel CERES SYN1deg → CoV identique à la décimale
près (constat factuel : Kindia 0.190 ≡ Mamou 0.190).

### 7.2 Sensibilité au choix `ddof`

`ddof=0` (écart-type de population, variance divisée par N) retenu.
Alternative `ddof=1` (écart-type d'échantillon, variance divisée par
N-1) donnerait des valeurs supérieures d'un facteur √(N/(N−1)),
soit +0,14 % sur 365 observations. Choix non discriminant à cette
échelle, `ddof=0` plus simple et cohérent avec NumPy default.

## 8. Plage de valeurs typiques

### 8.1 Plage théorique attendue

Climatologie solaire intertropicale : CoV ∈ [0.10, 0.40] selon zone.

### 8.2 Plage observée 2021-2025 sur les 6 villes pilotes

| Ville | Min | Max | Moyenne | Climat |
|---|---:|---:|---:|---|
| Conakry-Kaloum | 0.212 | 0.269 | 0.237 | côtier (max, transition saisons) |
| Kankan | 0.171 | 0.193 | 0.179 | soudanien |
| Kindia | 0.177 | 0.207 | 0.190 | pixel partagé Mamou |
| Labé | 0.180 | 0.220 | 0.194 | Fouta-Djalon |
| Mamou | 0.177 | 0.207 | 0.190 | pixel partagé Kindia |
| Nzérékoré | 0.156 | 0.192 | 0.177 | équatorial humide (min, stable) |

Plage globale [0.156, 0.269]. Conakry-Kaloum présente le CoV le plus
élevé (climat côtier avec saison sèche/humide marquée), Nzérékoré le
plus bas (climat équatorial humide plus stable). Cohérent avec la
climatologie ouest-africaine.

## 9. Application Côte d'Ivoire

Décision, vérifications et constats : ADR-0024 (migration 0039).

### 9.1 Périmètre et calcul

- Entrée : le GHI **journalier** NASA POWER, disponible aux 34 localités
  du lot « pilotes + régions » (31 régions et les départements
  d'Abidjan, Yamoussoukro et Korhogo, ADR-0016), sur 1991-2025
  (ADR-0018).
- Définition reproduite à l'identique (v1) : écart-type de population
  (division par N, comme le service `services/grandeurs/variabilite_journaliere.py`)
  rapporté à la moyenne ; annuel uniquement ; complétude stricte des
  jours civils, vérifiée ici **au grain journalier** (365 ou 366 jours),
  sur les seules mesures courantes non dépréciées.
- 34 séries `variabilite_journaliere_nasa_power_<loc>` (source
  `kuma_calculs`, méthode `calcul_derive`), **1 190 lignes annuelles**
  (35 ans × 34 localités), confiance B, statut `brut`. Les 1 190 années
  sont complètes : aucune n'est écartée.
- Calcul hors-ligne en base (`stddev_pop` et `avg` en `numeric`).
  Vérifications : recalcul indépendant depuis les CSV journaliers et
  fonction pure du service identiques ; l'écart-type d'échantillon
  (N − 1) est rejeté par la même tolérance.

### 9.2 Plage observée (1991-2025)

Valeurs gravées dans **[0,135 ; 0,255]**, moyenne 0,178 : entièrement
dans la plage intertropicale du § 8.1 (`[0,10 ; 0,40]`).

| Localité | Moyenne | Min | Max |
|---|---:|---:|---:|
| San-Pédro (région) ≡ Gbôklé | 0,226 | 0,211 | 0,255 |
| Département d'Abidjan ≡ Grands-Ponts | 0,191 | 0,153 | 0,230 |
| Korhogo ≡ Poro ≡ Tchologo | 0,176 | 0,155 | 0,205 |
| Yamoussoukro ≡ Bélier ≡ Gôh | 0,170 | 0,145 | 0,217 |
| Bafing | 0,158 | 0,140 | 0,177 |

Lecture (constats, pas validation, détail dans ADR-0024) : le littoral
est le plus variable ; au-delà, le CoV varie peu du centre au nord, et
les localités les moins variables sont à l'ouest forestier et
montagneux (Bafing, Tonkpi, Kabadougou), pas au nord. L'hypothèse « le
sud est plus variable » ne vaut que pour la frange côtière.

### 9.3 Maille

Le § 7.1 (Kindia et Mamou) vaut pour la Guinée. En Côte d'Ivoire, les
34 localités ne donnent que 22 séries de CoV distinctes : des localités
d'une même cellule NASA POWER de 1° (signes ≡ ci-dessus) ont un GHI
journalier, donc un CoV, identique.

## 10. Versioning et historique

| Version | Date | Modifications |
|---|---|---|
| v1 | 2026-05 | Définition initiale CoV annuel, `ddof=0`, périodicité annuelle uniquement. |

## 11. Auteurs

- v1 - 2026-05 : Siba Kalivogui (Kuma Science).

## 12. Références bibliographiques

- Coefficient de variation - statistique classique, cf. Wikipedia /
  *Encyclopedia of Statistical Sciences*.
- Variability Index - PVsyst, Solargis (concept apparenté pour
  dimensionnement PV).
- NASA POWER methodology - `https://power.larc.nasa.gov/docs/methodology/`
- Fiche HEP - `docs/methodologie/grandeurs/hep.md`
