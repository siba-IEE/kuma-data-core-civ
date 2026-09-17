# Amener son pays ou sa station

Ce guide s'adresse à un chercheur ou une institution d'un pays d'Afrique francophone qui
veut voir son pays représenté, ou apporter des mesures de terrain.

## Deux choses à apporter

1. **Un RDS national** : des données ouvertes, organisées par source, pour votre
   pays. Une donnée satellitaire ou de réanalyse entre en confiance B (voir
   [confiance et statuts](confiance-et-statuts.md)).
2. **Des mesures de terrain** : une station au sol. C'est le chemin vers la
   confiance A, qui est réservée aux données validées au sol.

## Comment le Core et un RDS national s'articulent

Le moteur est partagé et générique (voir [généricité
pays](genericite-pays.md)). Vos données vivent dans le dépôt RDS de votre pays ;
le pont les verse dans le Core. Vous n'avez pas à écrire de migration. Le modèle
de données est décrit dans le [guide de contribution de données](donnees.md).

## Contexte francophone

Plusieurs pays d'Afrique francophone disposent de stations sol ouvertes. Elles
constituent une première ancre de confiance A par pays, et une raison concrète
pour les chercheurs locaux de contribuer. Kuma amorce chaque pays à partir de
ces sources ouvertes ; une contribution est un renfort, pas un prérequis.

## Par où commencer

- Ouvrez une issue avec le modèle **Proposer des données ou une station**.
- Précisez la provenance et la licence (une licence ouverte est requise).
- Pour une validation terrain (confiance A), le protocole de soumission est un
  chantier de la [feuille de route](../../ROADMAP.md), jalon terrain.
