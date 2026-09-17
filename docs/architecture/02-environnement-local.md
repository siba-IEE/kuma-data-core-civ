# Environnement local de développement

L'environnement local repose sur Docker Compose (PostgreSQL, Redis) et
`uv` pour les dépendances Python. Cette page couvre l'installation,
l'usage courant et le dépannage.

## Vue d'ensemble

L'environnement local repose sur Docker Desktop, qui héberge deux
conteneurs (PostgreSQL et Redis) sur un réseau Docker isolé. Le code
applicatif Python tourne en dehors de Docker, directement sur la
machine de développement, et se connecte aux services via
`127.0.0.1`.

```
+-------------------------------------------------------------+
|  Machine de développement (Windows 11 + Docker Desktop)     |
|                                                             |
|  Code Python (uv, pytest, ...)                              |
|              |                                              |
|              | 127.0.0.1:5432  127.0.0.1:6379               |
|              v                                              |
|  +-----------+----------------------+----------------+      |
|  |  Réseau Docker : kuma_network    |                |      |
|  |                                  |                |      |
|  |  +----------------------------+  |                |      |
|  |  |  kuma-postgres             |  |                |      |
|  |  |  postgres:16-alpine        |  |                |      |
|  |  |  volume: kuma_postgres_data|  |                |      |
|  |  +----------------------------+  |                |      |
|  |                                  |                |      |
|  |  +----------------------------+  |                |      |
|  |  |  kuma-redis                |  |                |      |
|  |  |  redis:7-alpine            |  |                |      |
|  |  |  volume: kuma_redis_data   |  |                |      |
|  |  +----------------------------+  |                |      |
|  +-------------------------------------------------+        |
|                                                             |
+-------------------------------------------------------------+
```

## Pourquoi Docker

Trois raisons motivent le choix de conteneurs Docker pour les services
de développement :

1. **Reproductibilité** - toute machine qui clone le dépôt obtient le
   même environnement, dans les mêmes versions, indépendamment du
   système hôte.
2. **Isolation** - les services Kuma cohabitent sans interférer avec
   d'autres bases PostgreSQL ou Redis éventuellement installées sur la
   machine.
3. **Cohérence avec la production** - la cible de déploiement
   ultérieure utilisera également des images conteneurisées, ce qui
   réduit les écarts entre développement et production.

## Services

| Service     | Image                | Port (hôte)        | Rôle                          |
|-------------|----------------------|--------------------|-------------------------------|
| `postgres`  | `postgres:16-alpine` | `127.0.0.1:5432`   | Base de données principale    |
| `redis`     | `redis:7-alpine`     | `127.0.0.1:6379`   | Cache et files d'attente      |

Les deux services sont lancés via `docker/docker-compose.yml`. Aucun
service applicatif (FastAPI, scripts d'ingestion) n'est conteneurisé à
ce stade ; le code Python s'exécute directement sur la machine.

### PostgreSQL

- Authentification forcée en `scram-sha-256` sur les canaux local et
  hôte (via `POSTGRES_INITDB_ARGS`).
- Utilisateur, mot de passe et base définis dans le fichier `.env`
  (jamais versionné).
- Healthcheck via `pg_isready` toutes les 10 secondes, avec
  `start_period` de 30 secondes pour laisser le temps à l'init.

### Redis

- Mot de passe imposé via `--requirepass`. La directive est passée à
  `redis-server` par un shell intermédiaire (`sh -c`) afin que la
  variable soit résolue à l'intérieur du conteneur ; le mot de passe
  n'apparaît pas dans la ligne de commande visible par
  `docker inspect`.
- Healthcheck via `redis-cli ping` authentifié.

## Persistance des données

Chaque service est associé à un volume nommé Docker :

- `kuma_postgres_data` - données PostgreSQL.
- `kuma_redis_data` - dump Redis (`/data`).

Ces volumes sont gérés par Docker, indépendants du cycle de vie des
conteneurs. Un `docker compose down` arrête et supprime les conteneurs
mais **préserve les volumes**. Les données survivent donc aux
redémarrages, aux mises à jour des images, et aux modifications du
fichier de composition.

Pour supprimer délibérément les données (par exemple, repartir d'une
base vide) :

```bash
docker compose -f docker/docker-compose.yml down -v
```

L'option `-v` retire les volumes nommés. Cette opération est
irréversible. Elle est destructive au sens de
`docs/conventions/02-migrations.md` : à utiliser en pleine conscience.

Pour inspecter ou sauvegarder un volume :

```bash
docker volume inspect kuma_data_core_kuma_postgres_data
docker run --rm -v kuma_data_core_kuma_postgres_data:/data -v "${PWD}":/backup alpine \
  tar czf /backup/postgres-backup.tar.gz -C /data .
```

(Le préfixe `kuma_data_core_` est ajouté automatiquement par Compose
selon le nom du dossier projet.)

## Sécurité

L'environnement local applique trois règles de sécurité minimales :

1. **Aucun mot de passe en dur.** Les valeurs sensibles vivent dans
   `.env` à la racine, jamais commité. Le modèle `docker/.env.example`
   est versionné, avec des valeurs `changeme_*` qui doivent être
   remplacées avant le premier démarrage.
2. **Liaison locale uniquement.** Les ports `5432` et `6379` sont liés
   à `127.0.0.1`, ce qui empêche toute connexion depuis un autre poste
   du réseau. Aucun pare-feu n'a à intervenir : Docker ne publie pas
   les ports vers l'extérieur.
3. **Authentification systématique.** PostgreSQL exige scram-sha-256.
   Redis exige un mot de passe à chaque connexion.

Toute fuite suspectée d'un mot de passe local doit déclencher la
procédure décrite dans `SECURITY.md` (rotation immédiate dans `.env`,
puis redémarrage des services). Les mots de passe locaux ne donnent
pas accès à la production, mais peuvent révéler des habitudes de
nommage exploitables.

## Commandes essentielles

Toutes les commandes ci-dessous sont à exécuter depuis la racine du
dépôt.

Démarrer les services :

```powershell
.\scripts\services-start.ps1
```

Arrêter les services :

```powershell
.\scripts\services-stop.ps1
```

Voir l'état :

```powershell
.\scripts\services-status.ps1
```

Voir les logs d'un service :

```bash
docker compose -f docker/docker-compose.yml --env-file .env logs -f postgres
docker compose -f docker/docker-compose.yml --env-file .env logs -f redis
```

Ouvrir un shell PostgreSQL interactif :

```bash
docker compose -f docker/docker-compose.yml --env-file .env exec postgres \
  psql -U kuma_admin -d kuma_data_core
```

Ouvrir un shell Redis (avec authentification) :

```bash
docker compose -f docker/docker-compose.yml --env-file .env exec redis \
  redis-cli -a "${REDIS_PASSWORD}"
```

Vérifier la validité du fichier de composition :

```bash
docker compose -f docker/docker-compose.yml --env-file .env config
```

## Dépannage

### Le démon Docker ne répond pas

`services-start.ps1` détecte ce cas et affiche un message en rouge.
Démarrer Docker Desktop manuellement et attendre que l'icône soit
verte avant de relancer le script.

### PostgreSQL refuse les connexions

Vérifier que le service est `healthy` :

```powershell
.\scripts\services-status.ps1
```

Si le statut reste `starting` au-delà de 30 secondes ou passe à
`unhealthy`, consulter les logs :

```bash
docker compose -f docker/docker-compose.yml --env-file .env logs postgres
```

Causes fréquentes : mot de passe modifié dans `.env` après une
première initialisation (PostgreSQL conserve le mot de passe initial
dans le volume), conflit de port `5432` avec une instance locale.

### Conflit de port 5432 ou 6379

Une autre instance PostgreSQL ou Redis tourne déjà sur la machine.
Deux options : arrêter l'instance concurrente, ou modifier
temporairement le mapping de port dans `docker-compose.yml` (par
exemple `127.0.0.1:55432:5432`). Privilégier la première option pour
ne pas dévier du standard.

### Réinitialiser un volume

Si la base se trouve dans un état incohérent et qu'aucune donnée
critique n'y est stockée :

```bash
docker compose -f docker/docker-compose.yml --env-file .env down
docker volume rm kuma_data_core_kuma_postgres_data
.\scripts\services-start.ps1
```

PostgreSQL réinitialisera la base avec les paramètres du `.env`
courant. Les éventuelles migrations Alembic devront être rejouées.

### Mot de passe PostgreSQL ignoré après changement de `.env`

PostgreSQL ne réapplique pas le mot de passe au redémarrage si le
volume contient déjà des données : la valeur `POSTGRES_PASSWORD`
n'agit qu'à l'initialisation. Pour appliquer un nouveau mot de passe
sans détruire les données, se connecter en `psql` et exécuter
`ALTER USER kuma_admin WITH PASSWORD '...'`.
