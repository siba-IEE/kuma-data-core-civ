# ADR-0004 : exposition des études au point (résolution de cellule et référentiel de calage)

Date : 2026-07-20. Statut : accepté.

## Contexte

Le chantier Solar Bridge mini-réseaux (brief du dépôt de pilotage,
cadrage du 2026-07-20) fait de l'API publique le guichet unique de
données des études de dimensionnement : le logiciel consomme le Core,
il n'est jamais l'autorité. Deux savoirs nécessaires aux études au
point quelconque existent déjà dans le Core mais n'étaient pas servis
par l'API :

1. **La climatologie au point.** Les points d'ingestion du
   référentiel (33 préfectures + Conakry) échantillonnent les
   cellules de la grille de la source de climatologie (1 degré x
   1 degré, frontières aux degrés entiers). Vérification empirique du
   2026-07-20 : la moyenne 1991-2020 de la série de Kérouané
   reproduit le relevé NASA POWER au point de Tokounou, même cellule,
   écart nul sur les 12 mois. Savoir quelle série représente un point
   est un savoir éditorial : le plus-proche-voisin naïf est FAUX
   (Tokounou est à ~74 km de Kankan mais dans la cellule de Kérouané,
   ~99 km) - le laisser aux consommateurs garantirait des
   climatologies erronées.
2. **Le calage satellite/sol.** Les biais saisonniers mesurés à la
   station de Kankan vivent dans les notes de méthodologie
   (calage-ghi-kankan-terrain-lite.md) et leurs scripts
   reproductibles, pas dans l'édition servie.

Un premier cadrage envisageait un passe-plat climatologie au point
(relais amont a la demande) : contraire a la decision D6 de
l'ADR-0003 (edition figee, zero dependance sortante), abandonne. Un
deuxieme envisageait d'ingerer une grille climatologique nationale :
redondant, le deja-la couvre le besoin.

## Décision

1. **Résolution au point servie par l'API** :
   `GET /v1/localites/resolution?lat=&lon=` retourne la localité du
   référentiel qui échantillonne la cellule du point (candidates :
   localités actives portant une série climatologie mensuelle active
   1991-2020 de la grandeur), avec bornes de cellule, distance et
   drapeau `meme_cellule`. Cellule non échantillonnée : la candidate
   la plus proche est renvoyée avec `meme_cellule=false`, à charge du
   consommateur d'afficher l'hypothèse de transport. Lecture pure du
   stocké, conforme D6.
2. **Référentiel de calage publié comme donnée éditoriale** : table
   `referentiels_calage` (une ligne par station, grandeur, saison :
   biais relatif satellite moins sol, provenance, portée de
   transport, version), seedée par migration, publiée dans l'édition
   (TABLES_PUBLIEES), servie par
   `GET /v1/calage/{localite}/{grandeur}` avec le facteur dérivé
   k = 1/(1+biais). Pas de grandeur recalculée à la volée : les
   lignes satellite horaires de l'appariement d'origine ne sont plus
   stockées, et le serveur public ne calcule que du reconstructible
   (D6). Le recalcul appartient à la chaîne de recherche (notes +
   scripts), l'édition publie le résultat avec sa provenance.
3. **Périmètre initial** : grandeur `ghi` seule pour la résolution ;
   référentiel de calage GHI Kankan seul (migration 101). Le DNI et
   les stations futures entreront quand un consommateur en aura
   besoin (une migration = un changement).

## Conséquences

- Solar Bridge (et tout consommateur d'étude au point) obtient la
  climatologie juste et le calage tracé via l'API, sans embarquer ni
  géométrie de grille ni constantes de recherche.
- L'exposition n'atteint la production que par la publication d'une
  nouvelle édition (les données : migration 101) et le redéploiement
  du conteneur API (le code des endpoints).
- La convention de cellule (1 degré, frontières entières) est
  documentée avec sa vérification empirique ; si une source de
  climatologie à grille différente entre au catalogue, la résolution
  devra porter la géométrie par source.
- Les 5 tests d'intégration de la résolution (ti116-ti120) et les 3
  du calage (ti113-ti115) contractualisent le comportement, dont le
  cas Tokounou vers Kérouané.

## Complément du 2026-07-20 au soir : couverture progressive

Décision du fondateur : les logiciels consommateurs ne couvrent
d'abord que la zone où le transport du calage est défendable, puis
grandissent ville par ville au rythme de la recherche. Le domaine de
couverture est une donnée servie, jamais une liste codée chez les
consommateurs :

- table ``calage_couverture`` (migration 102, TABLES_PUBLIEES) : une
  ligne par localité qualifiée d'un référentiel, justification
  obligatoire ; servie par le champ ``localites_couvertes`` de
  ``GET /v1/calage/{localite}/{grandeur}`` ;
- domaine initial du référentiel GHI Kankan : les 5 communes points
  d'ingestion de la région administrative de Kankan (Kankan,
  Kérouané, Kouroussa, Mandiana, Siguiri) - même régime soudanien,
  précédent de transport déclaré de l'étude Tokounou ;
- extension : qualification par la recherche (cohérence
  inter-source par cellule, campagnes de mesure, leave-one-out
  quand une deuxième station sol existera), une édition à la fois ;
- côté consommateur : site hors domaine = refus honnête (décision
  produit Solar Bridge, consignée au brief de chantier).

Test ti121.
