# ADR-0034 — Température et vent journaliers ERA5

Date : 2026-10-28. Statut : accepté — **gravé** (migration 0053).

## Contexte

La température et le vent journaliers ne venaient que de NASA POWER (réanalyse
MERRA-2, migrations 0035 et 0047). ERA5 était déjà gravé en mensuel
(température, vent, pluie : 0036, ADR-0021) et pour la pluie journalière (0050,
ADR-0032).

L'utilisateur a demandé une deuxième source journalière pour la météo. Ce sont
des données brutes en confiance B : la confiance A et le calage terrain
viendront à la fin.

## Décision

1. **Produit** : valeurs horaires instantanées ERA5 du jeu
   `reanalysis-era5-single-levels-timeseries` du CDS. Ce jeu sert les mêmes
   valeurs que le jeu sur grille (ADR-0032).
   - Une requête par nœud 0,25°, pour `2m_temperature`,
     `10m_u_component_of_wind` et `10m_v_component_of_wind`.
   - Période 1991-2025.
2. **Jour** : jour civil UTC, qui est le jour local (UTC+0). La valeur du jour
   est la moyenne des 24 valeurs horaires datées de 00 h à 23 h. C'est la
   convention des variables instantanées du produit dérivé
   `derived-era5-single-levels-daily-statistics`.
   - `t2m` : K − 273,15 → °C.
   - `vent_10m` : moyenne des **vitesses** horaires √(u² + v²), et non norme
     des composantes moyennes. Le jeu ponctuel ne sert pas la variable
     `10m_wind_speed`.
3. **Maille** : point de grille 0,25° le plus proche, la même que pour le
   mensuel et la pluie journalière (110 mailles pour 142 localités).
4. **Gravure** :
   - 284 séries `ecmwf_era5_<grandeur>_journalier_<localité>`, 3 630 656
     mesures ;
   - source `ecmwf_era5` (id 2), méthode `reanalyse`, confiance B ;
   - audit par série (ADR-0031), via le module commun `gravure_journaliere`,
     qui reprend les étapes des migrations journalières 0046 à 0052.

## Résultats

**Cohérence avec le mensuel ERA5** (moyenne des jours de chaque mois − mensuel
0036, 59 640 mois-localités) :
- `t2m` : écart de 0,002 °C au plus, l'arrondi des produits.
- `vent_10m` : le journalier est **toujours** sous le mensuel, de 0,001 à
  0,110 m/s, 0,021 en moyenne. Le maximum est à Tabou, en mai 2019.
  - Le mensuel moyenne la variable `10m_wind_speed`. Le journalier recalcule
    la vitesse depuis les composantes.
  - Ce signe constant est compatible avec une vitesse calculée sur des
    composantes déjà interpolées, toujours inférieure ou égale à une vitesse
    interpolée. Cette explication n'est pas vérifiée.
  - L'écart est cité dans la note publique et n'est pas corrigé.

**Comparaison avec NASA POWER journalier** (MERRA-2, 142 localités,
12 784 jours) :
- **Température** : ERA5 est plus chaude de 0,27 °C en moyenne (26,38 contre
  26,11 °C), avec 0,95 °C d'écart absolu moyen au jour le jour. Selon la
  localité, l'écart va de −0,49 °C (Touba) à +1,59 °C (Kouibly).
- **Vent à 10 m** : ERA5 est plus faible de 19 % (2,04 contre 2,52 m/s). Selon
  la localité, l'écart va de −1,68 m/s (Tiapoum, sur la côte) à +0,96 m/s
  (Issia).

**Reproductibilité** :
- Régénérer les CSV depuis le cache redonne les mêmes octets.
- L'aller-retour `downgrade`/`upgrade` redonne la même empreinte des mesures.

## Conséquences

- Deux sources journalières de température et de vent aux 142 localités.
- L'API ne mélange pas les sources : les compagnes d'une série sont cherchées
  dans sa propre source, et les calculs fondés sur NASA POWER sont inchangés.
- Le vent journalier ERA5 n'est pas interchangeable avec le vent journalier
  NASA. L'écart entre les deux réanalyses dépasse leur écart à la mesure, que
  seules les stations au sol (Jalon 4) pourront trancher.
