# Fiche méthodologique - `humidex` (Indice de confort thermique)

> Conventions communes : voir fiche HEP `hep.md`.

## 1. Identification

| Champ | Valeur |
|---|---|
| Nom | Indice de confort thermique Humidex |
| Code métier | `humidex` |
| Unité | °C apparents |
| Famille | F1 - fait stocké |
| Stratégie de calcul | `stockee` (persistée dans `grandeurs_metier`) |
| Version courante | 1 |
| Périodicités exposées | annuel + mensuel (moyenne arithmétique) |

## 2. Définition formelle

Formule **Masterton & Richardson 1979** avec constantes Magnus standard
(17.67 et 243.5, sources : Environnement Canada, Masterton & Richardson
1979) :

```
e = (RH/100) * 6.112 * exp((17.67 * T) / (T + 243.5))
H = T + (5/9) * (e - 10)
```

Avec :
- `T` : température journalière moyenne en °C
- `RH` : humidité relative journalière moyenne en %
- `e` : pression de vapeur saturante en hPa
- `H` : humidex en °C apparents

**Référence numérique** : T = 30 °C, RH = 70 % → H ≈ 40.95 °C apparents
(vérifiable manuellement, test T-1 du module).

## 3. Agrégat annuel et mensuel

Humidex calculé jour par jour, puis **moyenne arithmétique** sur la
période agrégée. Pas de stockage journalier des valeurs humidex.

## 4. Compteur `nb_jours_inconfort_modere`

Nombre de jours par année avec `H ≥ 40 °C apparents` (seuil
*inconfort modéré* Environnement Canada). Calculé en interne dans le
module `services/grandeurs/humidex.py`, retourné dans `CalculHumidexResultat`,
logué via `op.execute('-- ...')` dans la migration d'ingestion 032.

**Non stocké dans `grandeurs_metier`** : sa persistance nécessiterait
une nouvelle entrée du référentiel `humidex_nb_jours_inconfort`.
Reporté à une extension ultérieure si besoin éditorial.

## 5. Source amont

`t2m` et `rh2m` journaliers NASA POWER (paramètres `T2M` et `RH2M`,
source MERRA-2 GMAO).

## 6. Limites et portée

### 6.1 Altitude du Fouta-Djalon

Humidex consomme T2M directement. La sous-estimation de l'altitude du
Fouta-Djalon par MERRA-2 affecte la température mesurée à Labé (1025 m)
et Mamou (782 m). Les valeurs humidex de Labé et Mamou sont donc
**biaisées vers le haut** par rapport à la réalité de terrain
(température réelle plus basse en altitude qu'estimée par MERRA-2).

Direction physique néanmoins préservée : Labé reste le minimum observé
(29.6 °C) - l'effet altitude est partiellement capté par MERRA-2 même
sous-estimé.

### 6.2 Co-localisation Kindia / Mamou

`humidex` ne consomme pas GHI ; la co-localisation Kindia / Mamou dans
le même pixel CERES ne s'applique pas directement. Mais Kindia et Mamou
peuvent partager le même pixel MERRA-2 0.5° × 0.625° (résolution
distincte de CERES). Constat factuel : valeurs proches mais pas
identiques (Kindia 34.7, Mamou 30.9), donc pixels MERRA-2 distincts
pour ces 2 localités.

## 7. Plage de valeurs typiques

### 7.1 Plage théorique attendue

Guinée tropicale : humidex moyen annuel ∈ [27, 40] °C apparents selon
zone climatique et altitude.

### 7.2 Plage observée 2021-2025 sur les 6 villes pilotes

| Ville | Min | Max | Moyenne | Note |
|---|---:|---:|---:|---|
| Conakry-Kaloum | 37.29 | 38.55 | 37.93 | côtier humide, max |
| Kankan | 32.49 | 33.53 | 33.10 | soudanien sec |
| Kindia | 33.98 | 35.03 | 34.68 | |
| Labé | 29.00 | 29.96 | 29.60 | Fouta-Djalon altitude, min |
| Mamou | 30.26 | 31.14 | 30.89 | |
| Nzérékoré | 31.30 | 32.44 | 32.02 | équatorial humide |

Plage globale [29.0, 38.6]. Conakry-Kaloum domine (côtier humide chaud),
Labé minimum (altitude Fouta-Djalon, mais cf. § 6.1).

## 8. Versioning et historique

| Version | Date | Modifications |
|---|---|---|
| v1 | 2026-05 | Définition initiale Masterton & Richardson 1979, agrégat moyenne arithmétique annuel + mensuel, seuil `nb_jours_inconfort_modere = 40 °C` non stocké. |

## 9. Auteurs

- v1 - 2026-05 : Siba Kalivogui (Kuma Science).

## 10. Références bibliographiques

- Masterton J.M. & Richardson F.A. (1979). *Humidex: A method of
  quantifying human discomfort due to excessive heat and humidity.*
  Environment Canada, Atmospheric Environment Service, CLI 1-79.
- Environnement Canada - grille d'inconfort humidex (40 = modéré, 45 =
  élevé, 54+ = danger).
- NASA POWER methodology MERRA-2 - `https://power.larc.nasa.gov/docs/methodology/`
- Fiche HEP référence - `docs/methodologie/grandeurs/hep.md`
