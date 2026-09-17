# Conventions de migrations

Toutes les évolutions du schéma de base de données passent par Alembic.
Aucune exception n'est tolérée, ni en développement, ni en
pré-production, ni en production.

Ce document fixe les règles applicables à la création et à la gestion
des migrations.

## Principe directeur

Une migration est un artefact immuable une fois mergée sur `main`. Toute
correction se fait par une nouvelle migration, jamais par modification
de l'existante. Cette règle protège l'historique de la base de données
et garantit que toute instance peut être reconstruite à partir de la
suite ordonnée des migrations.

## Nommage des fichiers

Le format des noms de fichiers de migration est :

```
YYYY_MM_DD_HHMM_description_courte.py
```

- `YYYY_MM_DD_HHMM` : horodatage de création de la migration, en heure
  locale de l'auteur, sans fuseau (l'ordre relatif des migrations est
  géré par Alembic via le chaînage `down_revision`).
- `description_courte` : en snake_case français, succincte et
  descriptive. Exemples :
  - `2026_06_12_1430_creer_table_sources.py`
  - `2026_07_03_0915_ajouter_index_localites_nom.py`
  - `2026_07_18_1100_renommer_colonne_niveau_confiance.py`

Le `revision_id` interne d'Alembic reste en hexadécimal généré
automatiquement et n'apparaît pas dans le nom du fichier.

## Règle « une migration = un changement logique »

Chaque migration porte sur un changement cohérent unique. Exemples
acceptables :

- Création d'une table avec ses index et ses contraintes initiales.
- Ajout d'une colonne avec sa valeur par défaut et son backfill.
- Renommage d'une colonne et adaptation des contraintes associées.

Une migration ne mélange jamais des changements indépendants (par
exemple, créer une table et modifier une autre). Si un besoin
fonctionnel exige plusieurs changements, ils sont scindés en autant de
migrations ordonnées.

## Modifications interdites une fois mergée

Une migration mergée sur `main` ne peut plus être modifiée. Sont
interdits :

- L'édition de son corps (`upgrade` ou `downgrade`).
- Le renommage du fichier.
- La modification de son `revision_id` ou de son `down_revision`.

Si une migration mergée s'avère erronée, la correction prend la forme
d'une nouvelle migration qui rétablit l'état attendu.

## Opérations destructives

Toute opération destructive nécessite une validation explicite double :
l'auteur du changement et un relecteur indépendant. Sont considérées
comme destructives :

- Suppression d'une table.
- Suppression d'une colonne.
- Suppression d'une contrainte de validation.
- Suppression d'un index couvrant des cas de production.
- Modification de type qui peut entraîner une perte d'information
  (rétrécissement, changement d'unité, conversion de type).

En période de travail en solo, la « validation indépendante »
prend la forme d'une relecture différée : la PR portant la migration
destructive est ouverte, l'auteur attend au minimum 24 heures avant de
la relire et de la merger lui-même. Ce délai est destiné à empêcher les
suppressions impulsives.

## Backfill et migrations en deux temps

Lorsqu'un changement nécessite une migration de données significative,
le schéma est modifié en deux temps :

1. Migration A : ajoute le nouveau schéma sans casser l'ancien
   (nouvelle colonne nullable, nouvelle table).
2. Code applicatif : commence à écrire dans le nouveau schéma.
3. Migration B : effectue le backfill des données depuis l'ancien
   schéma vers le nouveau.
4. Code applicatif : bascule la lecture sur le nouveau schéma.
5. Migration C : retire l'ancien schéma (relevant de la procédure
   destructive ci-dessus).

Cette séquence garantit qu'à aucun moment la base ne se trouve dans un
état incompatible avec une version active du code.

## Versioning temporel

Le schéma de Kuma Data Core repose sur un versioning temporel : les
mises à jour ne remplacent jamais une ligne existante. Toute migration
qui introduit une table contenant des données métier doit prévoir, dès
sa création, les colonnes `valide_du` et `valide_au`, et ne pas
permettre l'`UPDATE` direct sur les colonnes versionnées hors
`valide_au`.

## Tests de migration

L'intégration continue exécute
systématiquement la suite complète des migrations sur une base vide,
puis vérifie qu'`alembic check` ne signale aucun écart entre le schéma
ORM et le schéma migré. Toute migration doit franchir ces deux portes
pour être mergeable.

## Production

Aucune migration n'est appliquée à la base de production manuellement.
La procédure de déploiement, qui sera définie ultérieurement, comportera
une étape de migration automatisée déclenchée depuis l'intégration
continue, avec sauvegarde préalable et possibilité de rollback selon les
règles décrites dans la section « Opérations destructives ».
