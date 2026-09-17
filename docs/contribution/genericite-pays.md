# Généricité pays

Note d'architecture à l'intention des contributeurs : **le Core ingère la
donnée solaire brute de n'importe quel pays.** La Guinée est le pays pilote,
mais rien dans le schéma n'est spécifique à la Guinée.

## Le pays est un axe de classification

Il n'y a aucune notion de pays câblée en dur. Les localités forment une
hiérarchie à sept niveaux :

`continent`, `region_supranationale`, `pays`, `region_administrative`,
`prefecture`, `commune`, `site`.

Le pays est un niveau de cette hiérarchie. Chaque localité porte un code
`pays_iso3` (ISO 3166-1 alpha-3) et un code métier de la forme
`<code_pays>_<slug>` (par exemple `gin_conakry`). La cohérence parent-enfant est
validée côté base.

## Ce qu'un nouveau pays branche

Le socle est partagé : sources, grandeurs, unités, confiance, statut,
versionnement, audit. Ajouter un pays revient à :

1. créer ses localités (la racine pays, puis ses descendants) ;
2. rattacher ses sources, ses séries et ses mesures ;
3. laisser la machinerie de confiance et de statut s'appliquer telle quelle.

Aucune migration de schéma n'est nécessaire pour un nouveau pays.

## Un produit-données par pays

Les données nationales sont publiées dans un dépôt RDS par pays
([rds-guinee](https://github.com/siba-IEE/rds-guinee), puis d'autres). Le Core
est le moteur commun ; chaque RDS est un produit éditorial. Le pont qui verse un
RDS national dans le Core est en construction (voir la [feuille de
route](../../ROADMAP.md)).

Pour contribuer les données ou une station de votre pays, voir
[amener son pays ou sa station](pays-et-terrain.md). La généricité est vérifiée
par un test de bout en bout sur un pays fictif
([issue #6](https://github.com/siba-IEE/kuma-data-core/issues/6)).
