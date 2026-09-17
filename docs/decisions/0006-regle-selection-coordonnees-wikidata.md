# ADR-0006 : règle de sélection des coordonnées Wikidata (localités CIV)

Date : 2026-09-17. Statut : accepté.

## Contexte

Les coordonnées (`latitude` / `longitude`) des localités ivoiriennes sont
sourcées sur **Wikidata** (propriété `P625`, « coordonnées géographiques »),
selon la doctrine « aucune coordonnée inventée ». Trois situations se
présentent dans la donnée réelle, rencontrées dès la densification des
districts puis des régions et appelées à se répéter aux départements :

1. **Un seul point `P625`** : cas courant, aucune ambiguïté.
2. **Plusieurs points `P625`** sur la même entité, avec des **rangs**
   différents (`preferred` vs `normal`) ou **plusieurs `normal`** équivalents.
   Exemples rencontrés : district Savanes (`CI-SV`, un `preferred`), districts
   Vallée du Bandama (`CI-VB`) et Denguélé (`CI-DN`), région Sud-Comoé (deux
   `normal`, aucun `preferred`).
3. **Un point unique mais manifestement erroné** en amont. Exemple : la région
   Hambol (`civ_hambol`), dont le `P625` pointe exactement sur Bouaké,
   co-localisé avec la région voisine Gbêkê, alors que Hambol est la région de
   Katiola.

La règle appliquée était décrite dans la docstring du seed mais n'avait pas
de décision formelle (une référence « ADR coordonnées » y pointait dans le
vide). Cet ADR la fige.

## Décision

1. **Sélection parmi plusieurs `P625`** : on retient le statement de rang
   `preferred` s'il existe ; sinon le **premier statement dans l'ordre
   document Wikidata** parmi les rangs `normal`. Règle **déterministe et
   reproductible** via l'API `wbgetentities` (props=claims).
   - Limite assumée : lorsqu'il existe **plusieurs `normal` sans `preferred`**
     (`CI-VB`, `CI-DN`, Sud-Comoé), Wikidata ne privilégie aucun point ;
     « premier en ordre document » est un **départage conventionnel**, stable
     via l'API mais éditable en amont, et non sémantiquement canonique. Il est
     accepté comme pragmatique et **révisable** si un critère meilleur
     (centroïde d'une source officielle, géométrie polygonale) devient
     disponible.
2. **Point unique erroné** : lorsqu'un `P625` est démontrablement faux
   (co-localisé avec une autre entité, hors de l'emprise connue), on **ne le
   grave pas**. On retient un **substitut sourcé** — par défaut la coordonnée
   du **chef-lieu** de l'entité (Wikidata) — et on **documente** en `notes` la
   substitution et l'erreur amont. On n'invente jamais de coordonnée ; si
   aucun substitut sourcé n'existe, la coordonnée reste `NULL`. Cas appliqué :
   Hambol → chef-lieu Katiola (Q2409805).
3. **Garde-fou d'enveloppe** : toute coordonnée gravée doit tomber dans
   l'enveloppe géographique du pays (bornes larges CIV), contrôlée par test
   d'intégration.

La règle s'applique à tous les niveaux de localité de l'instance (districts,
régions, à venir départements), à `type_localite` près.

## Conséquences

- Sourçage des coordonnées **uniforme et reproductible** d'un niveau à
  l'autre ; les cas multi-points (`CI-VB`, `CI-DN`, Sud-Comoé) sont traçables
  et re-dérivables à l'identique.
- Le repli sur chef-lieu est une **exception documentée**, jamais un
  écrasement silencieux ; l'erreur amont (Hambol) peut être corrigée sur
  Wikidata puis ré-importée sans changer la règle.
- La passe **départements** suivra cette règle sans nouvelle décision ; il
  faudra y scanner les doublons/co-localisations (le cas Hambol montre que
  l'erreur amont existe).
- Si le besoin d'un départage canonique des cas à rangs égaux se fait sentir,
  cet ADR sera révisé (nouveau critère explicite), sans invalider les
  coordonnées déjà gravées (mêmes points, simplement mieux justifiés).
