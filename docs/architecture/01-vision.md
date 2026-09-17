# Vision et positionnement de Kuma Data Core

## Raison d'être

Kuma Data Core est une infrastructure de données générique à confiance
tracée. Il définit, alimente et sert une base de données centrale conçue
pour agréger des données issues de sources publiques, d'enquêtes terrain
et de la littérature scientifique, en les enrichissant de métadonnées
rigoureuses, et en les rendant exploitables aussi bien éditorialement
(articles) que programmatiquement (outils).

La connaissance technique localisée fait défaut aux acteurs de
l'ingénierie énergétique africaine. Les bases de données existantes sont
soit globales et peu pertinentes à l'échelle d'une localité, soit
fragmentées, soit propriétaires et inaccessibles. Kuma Data Core adresse
ce manque avec un modèle de données à schéma physique unique et
générique, dans lequel une ressource ou une source nouvelle s'ajoute par
seed et migration, sans refonte.

## Principes structurants

Six principes non négociables guident les décisions techniques :

1. **Métadonnées systématiques** - chaque donnée est accompagnée de sa
   source primaire, de sa méthode de collecte, d'un niveau de confiance
   (A, B, C), de la date de collecte, d'une éventuelle date de
   péremption, de l'auteur de la saisie et d'un statut éditorial
   (`brut`, `valide_auto`, `valide_humain`, `publie`, `deprecie`).
2. **Versioning temporel** - aucune mise à jour destructive ; toute
   évolution d'une donnée crée une nouvelle ligne dotée d'une période de
   validité (`valide_du`, `valide_au`).
3. **Table `sources` centrale** - toute donnée pointe vers une source
   documentée. La table `sources` est l'ossature de la crédibilité du
   système.
4. **Validation à deux niveaux** - validation automatique (cohérence,
   fourchettes, doublons) puis validation humaine pour les données
   critiques avant publication.
5. **Audit centralisé** - toute modification est tracée dans un
   `audit_log` unique.
6. **Aucune modification manuelle de la base de production** - toute
   évolution du schéma ou des données passe par une migration versionnée
   et par la chaîne d'intégration continue.

## Niveaux de confiance

Chaque mesure porte un niveau de confiance A / B / C :

- **A** - haute confiance, réservée aux mesures terrain directes.
- **B** - confiance moyenne (modèle satellitaire / réanalyse, source de
  haute fiabilité).
- **C** - confiance basse (calcul dérivé, ou source moyenne / faible).

Ce niveau est dérivé automatiquement à partir de la méthode de collecte
et de la fiabilité de la source, avec possibilité d'un override éditorial
justifié.

## Pilote : solaire Guinée

La première application est le substrat physique solaire de la Guinée.
La couverture initiale porte sur six villes pilotes - Conakry, Kindia,
Mamou, Labé, Kankan, Nzérékoré - avec des données d'irradiation
(GHI, DNI, DHI), de température, d'humidité et d'indice de clarté, issues
principalement de NASA POWER, complétées par un cross-check SARAH-3 et
une couche de grandeurs dérivées Kuma (HEP, productible, degrés-jours,
etc.). Le modèle reste générique : d'autres substrats (vent, hydrologie,
biomasse, infrastructure, usages) et d'autres pays s'ajoutent selon le
même schéma.

## Données publiques

Les données du pilote solaire Guinée sont publiées dans le dépôt public
`rds-guinee`, organisées par source (grille par source, terrain par
station).

## Opération

Kuma Data Core est opéré et soutenu par Kuma Science, média scientifique
d'ingénierie énergétique appliquée. Le média et les outils dérivés
partagent la même source de vérité, dont Kuma Data Core est l'expression
opérationnelle.
