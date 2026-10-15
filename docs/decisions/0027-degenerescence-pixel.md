# ADR-0027 : Dégénérescence de pixel — la couche d'honnêteté spatiale

Date : 2026-10-15. Statut : accepté — **gravé** (migration 0042).

## Contexte

Les séries mensuelles couvrent **142 localités** (3 pilotes, 31 régions, 108
départements ; ADR-0015, ADR-0018) à 4 sources. L'ADR-0015 a constaté que NASA
POWER ne distingue que **22 séries sur 31 régions** et **35 sur 111
départements** : des localités voisines lisent exactement les mêmes valeurs.
Ce fait n'était consigné que dans les ADR ; un lecteur de la base ou de l'API
voyait 111 séries NASA « départementales » sans savoir qu'il n'y en a que 35.

L'héritage prévoit une grandeur pour le dire, `degenerescence_pixel` (id 34,
F1, sans dimension) :

- **service** `services/grandeurs/degenerescence_pixel.py` : regroupe les
  localités dont les séries mensuelles sont **strictement identiques**
  (égalité exacte du vecteur, aucune définition de grille) et écrit une ligne
  `statique` par (localité, source, grandeur) dans `grandeurs_metier`,
  `valeur` = nombre de jumeaux, confiance B, FK vers la **série brute**, groupe
  et caveats dans `commentaire_editorial` ;
- **API** `incertitude_inter_source` : lit cette ligne (source `nasa_power`,
  grandeur `ghi`, une par localité) en « lecture/assemblage pur des grandeurs
  déjà matérialisées » ; sans elle, la fiche d'une localité qui porte des
  écarts répond 500 ;
- **référentiel** : `strategie_calcul = calculee_volee`, avec une description
  qui dit « matérialisée statique ». C'est la dérive que l'ADR-0009 (piège 1) a
  refusé de reproduire : ce qui vit dans `grandeurs_metier` est `stockee`.

Aucune ligne n'était gravée en CIV, et le service hérité n'est appelé nulle
part : sa configuration est guinéenne (sélection par `periode_debut` exacte :
SARAH-3 et CAMS à partir de 2021, alors qu'en CIV ils commencent en 2005).

## Décision

### Matérialiser, par migration, et reclasser `stockee`

- La valeur est **matérialisée** dans `grandeurs_metier` (migration 0042) :
  c'est ce que l'API lit, et l'identité observée est un fait de la base,
  calculable hors-ligne, sans réseau.
- La grandeur passe de `calculee_volee` à **`stockee`** et sa description est
  réécrite : `strategie_calcul` décrit où vit la valeur, et la seule voie de
  lecture est la table. Le downgrade restaure l'état hérité à l'identique.
- La grandeur **dépend du périmètre** (les localités qui portent la famille) :
  c'est pourquoi l'héritage la disait « à la volée ». Ce périmètre ne change
  que par migration ; la règle est donc : **toute migration qui ajoute ou
  retire des localités à une famille, ou modifie ses mesures, recalcule sa
  dégénérescence**. Un test compare en permanence les lignes gravées au
  regroupement recalculé depuis la base : une matérialisation périmée échoue.

### Contrat de ligne — celui du service, inchangé

Une ligne par **série mensuelle brute** (`granularite = 'mensuel'`, hors
`kuma_calculs`) : `periode_type = 'statique'`, `annee_debut`/`annee_fin` =
période de la série, `mois` NULL, `version_formule = 1`, `valeur` = nombre
d'**autres** localités de la famille dont le vecteur (mois, valeur) est
strictement identique, confiance **B**, statut `brut`.
`series_metadonnees_id` pointe la **série brute** qualifiée, pas une série
`kuma_calculs` (différence assumée avec les ADR-0009 à 0017) : la grandeur est
une propriété de cette série, l'identité `EXCLUDE` inclut la série, et c'est la
jointure de l'API. Les séries journalières n'en portent pas, pour que l'API
lise une ligne unique par (localité, source, grandeur).

### Nuance par type de source, rendue par le commentaire

Le compte est toujours **mesuré** ; le commentaire dit ce qu'il signifie :

- jumeaux à **coordonnées distinctes** : liste des localités ; « la source ne
  distingue pas ces points (maille) : ne pas présenter leurs valeurs comme des
  mesures indépendantes » ;
- jumeaux **aux mêmes coordonnées** (une région et un département de mêmes
  coordonnées, cf. ADR-0006) : « même point, série identique par
  construction » ;
- **aucun jumeau** : caveat de résolution, « un compte nul ne vaut pas
  résolution au point », avec la maille annoncée par la source.

Toutes les lignes portent le caveat de confiance (indicateur exact, mais B : A
est réservée aux mesures terrain).

### Familles détectées en base

La migration traite **toutes les familles mensuelles brutes présentes** quand
elle s'exécute. Les 10 familles de rayonnement sont **exigées** (142 localités,
période et nombre de mois de leur contrat) ; toute autre famille est traitée si
sa maille figure au catalogue `MAILLES` de la migration, sinon la migration
s'arrête. Le catalogue couvre déjà les familles annoncées : météo NASA POWER
(`t2m`, `rh2m`, `vent_2m`, `vent_10m`, `precipitation` sur MERRA-2 ; `kt` et
`albedo_surface` sur CERES), CAMS EAC4 (0,75°), ERA5 et ERA5-Land servis par le
CDS. Garde-fous : aucune ligne préexistante, grandeur dans l'état hérité, une
seule série par (localité, famille), séries non vides, comptes exacts par
famille (une ligne par série, 1420 pour le rayonnement), valeurs dans
`[0, n − 1]`. `ANALYZE grandeurs_metier` en fin de migration.

## Résultat

**1420 lignes** (10 familles × 142 localités). Aller-retour 0042 → 0033 → 0042 :
empreinte identique.

| Source | Grandeurs | Maille annoncée | Séries distinctes (142) | Régions (31) | Départements (111) |
|---|---|---|---:|---:|---:|
| NASA POWER | GHI, DNI, DHI | CERES SYN1deg, 1° | 35 | 22 | 35 |
| SARAH-3 (PVGIS) | GHI, DNI | au point, ~5 km | 126 | 31 | 111 |
| ERA5 (PVGIS) | GHI, DNI | 0,25°, servi par PVGIS | 126 | 31 | 111 |
| CAMS Radiation | GHI, DNI, DHI | au point, pixel 3-5 km | 126 | 31 | 111 |

**NASA POWER** (partition identique pour GHI, DNI et DHI : même grille CERES) :

- **134 localités sur 142 ont au moins un jumeau** ; 27 groupes, 8 localités
  seules (les départements Dabakala, Gbéléban, Kong, M’Bengué, Nassian, Tabou,
  Taï, Tengréla).
- Plus grands groupes : **12** (Bélier, Gôh ; Attiégouakro, Bonon, Bouaflé,
  Djékanou, Gagnoa, Oumé, Sinfra, Taabo, Toumodi, Yamoussoukro) ; **9**
  (Agnéby-Tiassa, Indénié-Djuablin, La Mé ; Abengourou, Adzopé, Akoupé, Arrah,
  Bettié, Yakassé-Attobrou) ; **9** (Gbêkê, Marahoué ; Béoumi, Botro, Bouaké,
  Gohitafla, Kounahiri, Sakassou, Tiébissou) ; **8** (Iffou ; Agnibilékrou,
  Daoukro, Koun-Fao, Prikro, Sandégué, Tanda, Transua) ; **7** (Grands-Ponts ;
  Abidjan, Agboville, Dabou, Jacqueville, Sikensi, Tiassalé) ; **7** (Poro,
  Tchologo ; Dikodougou, Ferkessédougou, Korhogo, Ouangolodougou, Sinématiali).
- Entre départements seulement : 35 séries, groupe maximal de **10** (autour de
  Yamoussoukro) ; **12 départements** seulement n'ont aucun autre département
  dans leur série. Entre régions : 22 séries, 8 groupes (Agnéby-Tiassa,
  Indénié-Djuablin et La Mé ; Bélier et Gôh ; Béré et Worodougou ; Cavally et
  Guémon ; Gbêkê et Marahoué ; Gbôklé et San-Pédro ; Moronou et N'Zi ; Poro et
  Tchologo).
- La partition empirique **coïncide exactement** avec un découpage en cellules
  de 1° bornées aux degrés entiers (35 cellules occupées) : la maille CERES de
  1° annoncée est vérifiée. Ce découpage n'est qu'un constat ; il n'entre pas
  dans le calcul.
- Le **journalier** NASA (34 localités, ADR-0016) donne 22 séries distinctes et
  exactement la même partition que le mensuel restreint à ces localités.

**Sources au point** (SARAH-3, ERA5, CAMS ; même partition pour les 7
familles) : les seuls jumeaux sont les **16 paires de coordonnées identiques**
région/département (Poro et Korhogo, Gbêkê et Bouaké, Folon et Minignan, Hambol
et Katiola, etc.) : 126 séries pour 126 points distincts. Hors ces paires, deux
localités ne partagent jamais une série.

**ERA5 servi par PVGIS est plus fin que sa maille** : les 126 points distincts
ne tombent que sur **110 nœuds** de la grille de 0,25° (112 cellules si on la
borne aux multiples de 0,25°), et pourtant ERA5 donne 126 séries distinctes.
PVGIS ne sert donc pas la valeur d'une cellule : il produit une valeur propre
au point, dont la finesse au-delà de 0,25° n'est pas une information de la
réanalyse (caveat porté par le commentaire).

## Lecture (constats, pas validation)

- Une étude NASA à l'échelle du département est, dans 99 cas sur 111, une
  étude à l'échelle d'une cellule d'environ 110 km partagée avec d'autres
  départements. SARAH-3 et CAMS restent les seules sources qui varient
  réellement d'un département à l'autre (ADR-0015).
- Les écarts inter-sources (ADR-0017) comparent donc souvent une valeur au
  point (SARAH-3, CAMS) à une valeur de cellule (NASA) : une partie de l'écart
  peut tenir à la représentativité spatiale. Rien n'est attribué ici.
- Un compte nul ne prouve rien sur la résolution : NASA seul dans sa cellule
  reste une moyenne de cellule ; ERA5 distinct partout reste une réanalyse de
  0,25°.

## Conséquences

- L'API `incertitude_inter_source` trouve sa ligne NASA GHI pour les 142
  localités (une ligne courante unique, testée). Ses paires d'écarts
  (`ecart_relatif_referentiel`, `ecart_relatif_dni_cams`, fenêtre 2021-2023)
  ne sont pas gravées en CIV : son adaptation relève du lot API.
- Les lignes référencent les séries brutes (FK `RESTRICT`) : une migration qui
  supprime ou remplace une série mensuelle brute retire d'abord ses lignes de
  dégénérescence, puis recalcule la famille.
- **Ordre des migrations** : 0042 doit suivre toute migration qui grave ou
  prolonge des séries mensuelles brutes. Si une famille est gravée après, elle
  n'est pas couverte et le test de couverture (une ligne par série mensuelle
  brute) échoue : soit placer 0042 après, soit graver ses lignes dans une
  nouvelle migration selon la même règle (le regroupement d'une famille ne
  dépend d'aucune autre).
- Le service hérité reste en place mais n'est pas utilisé en CIV ; il serait
  refusé par l'identité `EXCLUDE` s'il était rejoué sur les familles déjà
  gravées.

## Suite

- Météo NASA (MERRA-2, 0,5° × 0,625°) et CAMS EAC4 (0,75°) : couverts par la
  même règle dès qu'ils sont gravés. Si ces sources sont servies par cellule,
  les 126 points distincts ne devraient donner **au plus ~78** séries MERRA-2
  et **~49** séries EAC4 (nœuds de grille les plus proches) ; un compte
  supérieur signalerait une interpolation au point. Hypothèse à vérifier sur
  les données gravées, pas un constat.
