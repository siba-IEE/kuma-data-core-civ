# ADR-0013 : DHI — NASA POWER et CAMS, premier écart diffus

Date : 2026-09-29. Statut : accepté — **gravé** (migrations 0021-0023, 2026-09-29).

## Contexte

Le GHI et le DNI sont triangulés à 4 sources (ADR-0010 à ADR-0012). Le **DHI**
(irradiation diffuse horizontale, grandeur `dhi`, id 18, déjà seedée en 0002)
n'avait aucune série. C'est la 3ᵉ composante du rayonnement (GHI = DHI + DNI ×
cos θz) et l'entrée de la fraction diffuse et du POA.

Sondage des sources déjà utilisées (2026-09-29) :

| Source | DHI servi | Décision |
|---|---|---|
| NASA POWER | `ALLSKY_SFC_SW_DIFF`, moyenne journalière mensuelle en kWh/m²/jour, **1991-2020 sans trou** | ingérée |
| CAMS Radiation | colonne `DHI` du CSV ADS déjà utilisé (Wh/m² intégrés au mois) | ingérée |
| PVGIS (SARAH-3, ERA5) | **seulement le ratio `Kd`** = diffus/global (option `d2g=1`), **arrondi à 2 décimales** | **non ingérée** |

**Pourquoi pas PVGIS** : le DHI y serait **reconstruit** (`Kd × H(h)_m`), pas
servi. L'arrondi de `Kd` au centième (ex. 0,40) introduit jusqu'à ±0,005/0,40 ≈
**1,3 %** d'erreur de quantification, soit plus que certains écarts DHI observés
ci-dessous. Graver une valeur reconstruite sous la méthode `modele_satellitaire`
masquerait cette dérivation. Reportée tant qu'aucune sortie native n'existe.

## Décision

### Séries brutes (contrat ADR-0007/0011)

- **NASA POWER DHI** (migration 0021) : source `nasa_power` (id 1), 3 séries ×
  360 mois **1991-2020** = **1080 mesures**, `modele_satellitaire`, confiance B,
  **aucune conversion** (NASA sert déjà la moyenne journalière en kWh/m²/jour).
- **CAMS DHI** (migration 0022) : source `cams_radiation` (id 13), 3 séries × 192
  mois **2005-2020** = **576 mesures**, conversion ADR-0011 (Wh/m² ÷ 1000 ÷ jours
  du mois).

Aucune nouvelle source ni valeur d'énumération ; garde-fous d'identité de source.
**Continuité prouvée** : les ingesteurs NASA et CAMS, étendus au DHI,
régénèrent les seeds GHI et DNI déjà gravés **identiques à l'octet** (`git diff`
vide) — ni NASA ni l'ADS n'ont révisé leurs valeurs.

### Écart dérivé : `ecart_relatif_dhi_cams_nasa` (id 41, migration 0023)

Même contrat qu'ADR-0009 : `stockee`, `pourcent`, F1, `(cams − nasa) / nasa × 100`,
**NASA au dénominateur** (convention de tous les écarts CIV), fenêtre commune
2005-2020 par jointure SQL, **576 lignes**, confiance B.

## Résultat de la gravure (2005-2020)

| Point | DHI NASA | DHI CAMS | Rapport des moyennes | Moy. ratios mensuels | DJF | JJA | Min / max mensuel | Mois CAMS > NASA |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Abidjan | 2,54 | 2,72 | +7,2 % | +7,4 % | +5,0 % | +13,3 % | −3,2 / +23,4 % | 183 / 192 |
| Yamoussoukro | 2,52 | 2,68 | +6,1 % | +6,4 % | +1,7 % | +16,6 % | −8,6 / +29,9 % | 141 / 192 |
| Korhogo | 2,57 | 2,51 | −2,5 % | −2,8 % | −11,3 % | +6,6 % | −29,9 / +19,1 % | 78 / 192 |

*(kWh/m²/jour. « Rapport des moyennes » = `moy(cams)/moy(nasa) − 1` ; les
colonnes suivantes sont des moyennes des ratios mensuels **gravés**.)*

**Lecture (honnête, sans sur-interprétation) :**

- **Le diffus concorde bien mieux que le direct.** L'écart DHI CAMS − NASA reste
  dans ±8 % en moyenne, contre +31 à +78 % pour le DNI (ADR-0011). Le désaccord
  inter-source du rayonnement porte donc essentiellement sur la **composante
  directe**. C'est cohérent avec NASA « aberrant bas » sur le DNI (ADR-0012) sans
  l'être sur le DHI, mais **deux sources ne disent pas qui a raison**.
- **Saisonnalité** : CAMS est plus haut que NASA en mousson (JJA) aux 3 points.
  À Korhogo en saison sèche (DJF), c'est l'inverse (−11 %). Aucune attribution
  physique n'est tranchée ici : ce n'est pas une signature d'aérosols démontrée.
- Une 3ᵉ source DHI native reste nécessaire pour trianguler (PVGIS ne la sert
  pas ; mesure sol ESMAP/WAPP, Jalon 4).

## Reproductibilité

`scripts/ingest_nasa_power_mensuel.py` (grandeur `dhi` ajoutée) et
`scripts/ingest_cams_radiation_mensuel.py` (colonne `DHI` repérée par nom, clé
`ADS_API_KEY`) régénèrent les seeds `series_nasa_power_dhi_mensuel_civ` et
`series_cams_dhi_mensuel_civ`, lus **hors-ligne** par les migrations.

## Conséquences

- Les 3 composantes du rayonnement (GHI, DNI, DHI) sont en base aux 3 points.
- 7 grandeurs d'écart, toutes référées à NASA POWER.
- La **fraction diffuse** (grandeur `fraction_diffuse`, id 3) devient calculable
  par source (DHI/GHI) : prochaine grandeur dérivée possible, à décider.
