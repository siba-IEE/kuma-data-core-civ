# ADR-0035 — Rayonnement journalier CAMS Radiation

Date : 2026-10-28. Statut : accepté — **gravé** (migration 0054).

## Contexte

Le rayonnement journalier (GHI, DNI, DHI) ne venait que de NASA POWER
(migrations 0026 et 0046). Or NASA sert une maille de 0,5° × 0,625° : il ne
distingue que 35 séries pour 142 localités (ADR-0027). CAMS Radiation, déjà gravé
en mensuel (ADR-0011, ADR-0013, ADR-0018), calcule l'irradiation au point
demandé à partir des images Meteosat.

L'utilisateur a choisi d'ajouter le rayonnement journalier CAMS. Ce sont des
données brutes en confiance B : la confiance A viendra à la fin.

## Décision

1. **Produit** : jeu ADS `cams-solar-radiation-timeseries` (CAMS Radiation
   Service v4.6, consulté le 2026-10-28).
   - Paramètres : tous ciels (`observed_cloud`), `time_step=1day`, temps
     universel.
   - Une requête par localité, aux coordonnées du référentiel, sur 2005-2025.
2. **Valeur** :
   - colonnes `GHI`, `BNI` (= DNI) et `DHI`, en Wh/m² intégrés sur le jour
     UTC, qui est le jour civil local ;
   - conversion ÷ 1000 → kWh/m²/jour, sans interpolation ni bouchage ;
   - la fiabilité journalière (`Reliability`) est résumée par l'ingesteur, mais
     n'est pas gravée.
3. **Lacunes explicites** : un jour que CAMS ne sert pas (`nan`) figure dans le
   CSV avec une valeur vide, grâce au nouvel attribut `lacunes_admises` des
   contrats journaliers. Ce jour compte pour la complétude, mais il n'est ni
   bouché ni gravé.
4. **Gravure** :
   - 426 séries `cams_<grandeur>_journalier_<localité>`, 3 265 554 mesures ;
   - source `cams_radiation` (id 13), méthode `modele_satellitaire`, confiance B ;
   - audit par série.

## Résultats

**Lacunes** : 622 jours-localités par grandeur.
- Quatre jours manquent partout : 2005-01-11, 2005-01-12, 2006-01-10 et
  2006-01-11. Ce sont des jours où une partie des images Meteosat manque
  (fiabilité voisine de 0,52).
- Le 2006-09-23 manque dans 54 localités de l'est et du sud-est.
- La migration vérifie que les jours absents de chaque série sont exactement
  ceux-là.

**Finesse spatiale** : 126 séries distinctes sur 142 localités, contre 35 pour
NASA POWER.

**Cohérence avec le mensuel CAMS gravé** (moyenne des jours servis − mensuel) :
- **2005-2020, hors mois à lacune** : 26 926 mois-localités par grandeur,
  identiques à 0,0001 kWh/m²/jour près.
- **2021-2025** : CAMS a **révisé** ces années après la gravure de leur mensuel
  (sondage du 2026-09-30, ADR-0018), sans changer de version de service (v4.6
  depuis octobre 2023) et sans documentation publique trouvée.
  - Écart moyen des 8 520 mois-localités : GHI +0,018 kWh/m²/jour (jusqu'à
    0,118), DNI +0,025 (jusqu'à 0,154), DHI −0,002 (jusqu'à 0,031).
  - À Sandégué, le mensuel servi le 2026-10-28 est identique au mensuel gravé
    de 2005 à 2020, mais il diffère de 2021 à 2025, où il redonne la moyenne
    des jours.
- **Mois à lacune** (338) : CAMS intègre le mois autrement que la moyenne des
  jours servis ; écart publié par l'ingesteur.

**Valeurs mensuelles gravées** : elles sont conservées. Les 426 séries
mensuelles CAMS reçoivent une mise en garde dans leur note publique, qui est
une métadonnée seulement.

**Comparaison avec NASA POWER journalier** (mêmes jours servis, 142 localités,
1 088 518 jours-localités par grandeur) :

| Grandeur | CAMS (kWh/m²/jour) | NASA (kWh/m²/jour) | Écart moyen | Écart par localité |
|---|---:|---:|---:|---|
| GHI | 5,36 | 4,84 | +10,9 % | de −0,03 (Abidjan) à +0,87 (Fresco) |
| DNI | 3,85 | 2,46 | +57 % | de +0,61 (Abidjan) à +2,07 (Fresco) |
| DHI | 2,61 | 2,51 | +3,8 % | de −0,18 (Kaniasso) à +0,27 (Divo) |

Pour le DNI, NASA reste l'aberrant bas (ADR-0012, ADR-0017).

**Jours sans nuage détecté** : 6,3 % des jours servis ont un GHI tous ciels
égal au ciel clair, surtout de décembre à février.

**Reproductibilité** :
- régénérer les CSV depuis le cache redonne les mêmes octets ;
- l'aller-retour `downgrade`/`upgrade` redonne la même empreinte des mesures et
  restaure les notes mensuelles à l'identique.

## Conséquences

- Les calculs journaliers peuvent désormais s'appuyer sur un rayonnement qui
  distingue vraiment les localités.
- L'API ne mélange pas les sources : les compagnes d'une série CAMS sont cherchées
  dans CAMS, et les calculs fondés sur NASA POWER sont inchangés.
- Une série CAMS journalière a des trous : les calculs qui exigent des jours
  contigus, comme le modèle de salissure HSU, refusent une telle série avec une
  erreur explicite.
- **Décision ouverte**, tranchée par l'ADR-0037 (migration 0056) : graver la
  révision 2021-2025 du mensuel CAMS par versionnement temporel non destructif
  (anciennes valeurs closes, nouvelles valeurs ouvertes). Les écarts dérivés du
  mensuel (ADR-0017, ADR-0026) en dépendent.
