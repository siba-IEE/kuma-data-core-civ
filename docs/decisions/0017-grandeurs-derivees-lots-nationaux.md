# ADR-0017 : Écarts inter-sources et fraction diffuse sur tout le territoire

Date : 2026-09-30. Statut : accepté — **gravé** (migrations 0028-0029).

## Contexte

Les 7 écarts inter-sources (ADR-0009 à ADR-0013) et la fraction diffuse NASA
(ADR-0014) n'étaient gravés qu'aux 3 points pilotes. Les données brutes couvrent
désormais 142 localités (ADR-0015). Décision du 2026-09-30 : étendre ces
grandeurs dérivées aux 139 localités des lots nationaux, après avoir traité la
lenteur des tests.

## Décision

### Extension, contrats inchangés

- **0028** : les 7 écarts `(comparée − nasa) / nasa × 100`, NASA au
  dénominateur, fenêtre commune 2005-2020, aux 139 localités des lots —
  973 séries, **186 816 lignes** (26 688 par écart).
- **0029** : la fraction diffuse NASA (`Σ DHI / Σ GHI`, formule de la fiche,
  version 1), mensuelle et annuelle 2001-2020 — 139 séries, **33 360 lignes
  mensuelles** et **2 780 annuelles**.

Aucune nouvelle grandeur ni source : seules des séries `calcul_derive`
(`kuma_calculs`) et des lignes `grandeurs_metier`. Les jointures se limitent aux
séries **mensuelles** : les séries journalières NASA (0026) partagent localité,
source et grandeur, et sont exclues explicitement. Avec les pilotes, chaque
grandeur dérivée couvre **142 localités**.

### Statistiques du planificateur : `ANALYZE` après les insertions massives

La suite de tests prenait ~4 min 40. La mesure (`--durations`) a montré que la
comparaison intégrale au CSV ne coûte qu'une quinzaine de secondes : **un seul
test** prenait 260 s. Juste après les ~1,2 M lignes insérées par les lots, les
statistiques de Postgres sont vides ; le planificateur choisit des boucles
imbriquées sur un index GiST. Après `ANALYZE`, le même test passe en 0,2 s.

- 0028 lance `ANALYZE` sur les tables de mesures et de séries avant ses
  jointures, et 0028-0029 sur `grandeurs_metier` en fin de migration.
- Les deux tests de cohérence `DHI ≤ GHI` (mensuel et journalier) sont réécrits
  **sans auto-jointure** : un seul regroupement par (localité, période), dont le
  plan reste linéaire quelles que soient les statistiques. Ils vérifient en plus
  que chaque mesure DHI a son GHI (nombre exact de paires).

La comparaison intégrale de chaque valeur est **conservée** : aucune perte de
couverture. Suite complète : **~26 s** (contre ~4 min 40).

### Reproductibilité au bit près : sommes en `numeric`

Un aller-retour de migrations a fait varier 1 504 fractions diffuses annuelles
de 3·10⁻¹⁶ (dernier bit) : en flottant, une `SUM` dépend de l'ordre
d'agrégation, que Postgres peut changer (parallélisme). Les sommes annuelles
(0024 et 0029, non encore fusionnées) se font désormais en `numeric`, exact
donc indépendant de l'ordre, puis convertissent le quotient en `float8`.
Vérifié : deux allers-retours 0029 → 0023 → 0029 et une reconstruction depuis
zéro donnent des empreintes identiques.

## Résultat — 142 localités

Moyenne, par localité, des écarts mensuels gravés (2005-2020), puis
distribution nationale :

| Écart | Min (localité) | Médiane | Max (localité) | Corrélation avec la latitude |
|---|---|---:|---|---:|
| GHI SARAH-3 − NASA | +6,0 % (Minignan) | +13,5 % | +24,1 % (Fresco) | −0,61 |
| GHI ERA5 − NASA | −5,1 % (Taï) | +0,6 % | +10,7 % (Jacqueville) | 0,18 |
| GHI CAMS − NASA | −0,9 % (Abidjan) | +11,3 % | +19,2 % (Fresco) | −0,43 |
| DNI SARAH-3 − NASA | +44,6 % (Folon) | +81,6 % | +142,5 % (Grand-Lahou) | −0,71 |
| DNI ERA5 − NASA | +52,8 % (Folon) | +84,8 % | +137,9 % (Grand-Bassam) | −0,41 |
| DNI CAMS − NASA | +31,5 % (Abidjan) | +62,6 % | +112,3 % (Fresco) | −0,55 |
| DHI CAMS − NASA | −7,9 % (Kaniasso) | +5,4 % | +10,6 % (Divo) | −0,70 |

Fraction diffuse NASA annuelle moyenne : de **0,440** (Minignan, nord) à
**0,559** (La Mé, sud), corrélation avec la latitude −0,83.

**Lecture (constats, pas validation) :**

- **NASA POWER est l'aberrant bas du DNI sur tout le territoire** : l'écart DNI
  moyen est positif dans les 142 localités pour les 3 sources comparées (426 cas
  sur 426). Ce qu'ADR-0012 observait aux 3 pilotes est national.
- **Les désaccords se creusent vers la côte** (corrélations négatives avec la
  latitude, maxima sur le littoral : Fresco, Grand-Lahou, Grand-Bassam) : c'est
  là que nuages et aérosols marins pèsent le plus, et que les sources divergent
  le plus. Aucune attribution physique n'est tranchée ici.
- La part diffuse décroît du sud au nord, cohérent avec une nébulosité plus
  forte au sud.
- La maille NASA (~1°, 35 valeurs distinctes sur 111 départements, ADR-0015)
  entre dans ces écarts : deux départements voisins peuvent partager la même
  valeur NASA.

## Conséquences

- Toutes les grandeurs dérivées de l'instance couvrent les 142 localités.
- Patron pour les prochaines insertions massives : `ANALYZE` en fin de
  migration, sommes flottantes en `numeric`, tests de cohérence sans
  auto-jointure.
