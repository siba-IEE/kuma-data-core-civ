# ADR-0005 : mapping de la hiérarchie administrative ivoirienne sur les 7 niveaux génériques

Date : 2026-09-17. Statut : accepté.

## Contexte

Le Core range toute localité sur une échelle générique à **sept niveaux**
(`type_localite`) : `continent`, `region_supranationale`, `pays`,
`region_administrative`, `prefecture`, `commune`, `site`. Cette échelle est
un **axe de classification neutre** : ajouter un pays ne doit exiger aucune
migration de schéma, et l'identité nationale vit dans la donnée (`nom`,
`code`, `notes`, codes ISO), jamais dans l'énumération des types (voir
`docs/contribution/genericite-pays.md`).

La Côte d'Ivoire a sa propre hiérarchie administrative déconcentrée :

`District → Région → Département → Sous-préfecture → Village`

avec, en parallèle, des **collectivités territoriales** (Régions et
Communes municipales élues).

Deux frictions imposaient de trancher avant d'ajouter les niveaux inférieurs :

1. **Profondeur.** La CIV compte cinq paliers sub-nationaux (district,
   région, département, sous-préfecture, village) pour quatre niveaux
   génériques sous `pays` (`region_administrative`, `prefecture`, `commune`,
   `site`). Le mapping n'est donc pas 1:1 : un palier est absorbé.
2. **Vocabulaire.** Le niveau générique `prefecture` porte le nom de la
   subdivision de 1ᵉʳ ordre de la **Guinée** (33 préfectures), pays pilote du
   Core. La Côte d'Ivoire n'a **pas** de subdivision nommée « préfecture » ;
   elle a des **préfets** (préfet de région, préfet de département) dont la
   « préfecture » est le siège. Le nom du niveau n'est donc pas le nom d'un
   tier ivoirien.

Trois modèles étaient possibles : **(A)** garder l'énumération générique
telle quelle (identité dans la donnée) ; **(B)** neutraliser le vocabulaire
du cœur (renommer les niveaux en tokens agnostiques) ; **(C)** donner à la
CIV ses propres valeurs d'énumération (`district`, `region`, `departement`…).
**(C)** contredit la doctrine de généricité (chaque pays forkerait l'énum) ;
**(B)** corrige la friction de nommage mais est une décision de niveau cœur,
au périmètre bien plus large que cette instance.

## Décision

**Modèle retenu : (A).** L'énumération `type_localite` reste inchangée et est
traitée comme un **axe technique générique**. Aucune valeur d'énumération
propre à un pays n'est introduite. L'identité ivoirienne d'une localité est
portée par `nom`, `code`, `notes` et les codes ISO — pas par `type_localite`.

**Mapping CIV → niveaux génériques :**

| Palier ivoirien | Niveau `type_localite` | Effectif | Statut |
|---|---|---|---|
| District (dont 2 autonomes) | `region_administrative` | 14 | posé (migr. 0003) et densifié (0004) |
| Région | `prefecture` | 31 | à seeder |
| Département | `commune` | 108 | à seeder |
| Sous-préfecture | `site` | plusieurs centaines | ultérieur |

Précisions :

1. **`prefecture` = étiquette technique.** Le fait qu'une **région**
   ivoirienne soit dirigée par un **préfet de région** rend le mapping non
   absurde, mais le nom du niveau ne doit jamais être lu comme le nom du tier
   ivoirien. Chaque ligne portera dans `notes` sa qualification réelle (ex.
   « Région de Côte d'Ivoire (niveau générique `prefecture`) »).
2. **Palier absorbé.** Le **village** (5ᵉ palier déconcentré) n'a pas de
   niveau dédié ; il n'est pas modélisé comme tier, et un point d'intérêt fin
   (station, point d'ingestion, chef-lieu de sous-préfecture) est représenté
   au niveau `site`.
3. **Communes municipales.** Les communes élues (collectivités) forment une
   structure **parallèle**, pas un cinquième niveau de l'axe déconcentré :
   elles ne sont pas modélisées comme tier distinct. Une commune municipale
   qui est aussi un point d'ingestion sera portée comme `site` (ou `commune`
   si elle coïncide avec un département chef-lieu), au cas par cas et
   documenté.
4. **Contrat consommateur.** Un consommateur de l'API ne doit pas interpréter
   `type_localite` comme le nom du palier administratif ivoirien : le libellé
   humain est dans `nom` / `notes`. `type_localite` sert au tri hiérarchique
   et à la validation parent-enfant, pas à l'affichage réglementaire.

## Conséquences

- **Aucune migration de schéma** n'est requise par ce mapping : la généricité
  est préservée, conformément à `genericite-pays.md`.
- Les prochaines passes de densification sont débloquées et cadrées :
  31 régions au niveau `prefecture` (parent : le district), puis
  108 départements au niveau `commune` (parent : la région). La règle de
  validation hiérarchique parent-enfant en base reste applicable telle quelle.
- La **friction de nommage** (`prefecture` est un mauvais nom générique parce
  qu'il coïncide avec un tier guinéen réel) est **acceptée au niveau de cette
  instance**. Sa correction de fond — neutraliser le vocabulaire du cœur
  (modèle B) — relève d'une décision du moteur commun et n'est pas tranchée
  ici ; si elle survient, ce mapping se relira sans changement de données
  (seuls les noms de niveaux évolueraient, pour tous les pays à la fois).
- L'item « arrêter le mapping de la hiérarchie ivoirienne sur les 7 niveaux »
  de la feuille de route (Jalon 1) est **clos**.
