# Runbook go-live - première édition publique sur VPS

> Séquence complète pour déployer l'API publique Kuma Data Core sur un VPS
> nu (Ubuntu 24.04) jusqu'à `https://<domaine>/v1/edition` en ligne.
> Chaque étape est exécutable telle quelle. Les artefacts référencés vivent
> dans `docker/` et `scripts/publication/` (ADR-0003).

## Prérequis (avant de commencer)

- [ ] **VPS livré**, IP connue, image Ubuntu 24.04.
- [ ] **Clé SSH** déposée (paire Ed25519 locale ; clé publique installée sur
      le VPS à la (ré)installation, ou à déposer manuellement à l'étape 1).
- [ ] **Nom de domaine** possédé, avec un **enregistrement A** pointant vers
      l'IP du VPS. *Indispensable* : Let's Encrypt (TLS auto de Caddy) exige
      un domaine, pas une IP nue. Sans domaine, l'API tourne mais sans HTTPS.
- [ ] **Base locale de référence** à jour (c'est elle qu'on publie).

## Phase 1 - Durcissement du serveur nu

Objectif : réduire la surface d'attaque avant tout déploiement. **Ne jamais
couper l'accès root/mot de passe sans avoir vérifié qu'une connexion par clé
fonctionne**, sous peine de se verrouiller.

1. **Première connexion** (utilisateur par défaut indiqué par OVH : souvent
   `ubuntu`, parfois `debian` ou `root`) :
   ```bash
   ssh <utilisateur>@<IP>
   ```
2. **Récupérer le dépôt public** sur le VPS :
   ```bash
   sudo apt-get update && sudo apt-get install -y git
   git clone https://github.com/siba-IEE/kuma-data-core.git
   cd kuma-data-core
   ```
3. **S'assurer d'un utilisateur admin avec clé** : si la connexion se fait
   déjà en `<utilisateur>` non-root avec ta clé, cet utilisateur est l'admin.
   Sinon, créer l'utilisateur, déposer la clé publique dans
   `~/.ssh/authorized_keys`, lui donner `sudo`, et **tester la connexion par
   clé dans un second terminal** avant de continuer.
4. **Lancer le durcissement** (pare-feu, SSH, fail2ban, mises à jour, Docker) :
   ```bash
   sudo PORT_SSH=<port_choisi> ADMIN_USER=<utilisateur> \
     bash scripts/publication/durcir-vps.sh
   ```
   Après ce script : seuls 22 (ou le port choisi), 80 et 443 sont ouverts ;
   PostgreSQL et Redis ne sont **jamais** exposés.
5. **Vérifier la reconnexion** par clé sur le nouveau port dans un second
   terminal AVANT de fermer la session courante.

## Phase 2 - Base de données et provisioning

Ordre important : la base et ses rôles doivent exister avant l'API.

6. **Secrets de production** : copier le modèle et le remplir avec des mots
   de passe forts et **distincts par rôle** (ne jamais réutiliser le mot de
   passe superutilisateur) :
   ```bash
   cp docker/.env.prod.example .env.prod
   nano .env.prod   # remplir KUMA_DOMAINE, mots de passe, API_CLE_ADMIN
   ```
7. **Démarrer d'abord la base et le cache** (pas encore l'API) :
   ```bash
   docker compose -f docker/docker-compose.prod.yml --env-file .env.prod \
     up -d postgres redis
   ```
8. **Provisionner rôles + base de service** (rôle lecture seule, rôle de
   service, base `kuma_api_meta` verrouillée) :
   ```bash
   export PGUSER=$(grep POSTGRES_SUPERUSER= .env.prod | cut -d= -f2)
   export PGPASSWORD=$(grep POSTGRES_SUPERUSER_PASSWORD= .env.prod | cut -d= -f2)
   API_RO_PASSWORD=... API_SERVICE_PASSWORD=... \
     KUMA_PG_CONTENEUR=kuma-postgres-prod \
     bash scripts/publication/provisionner-serveur.sh
   ```
9. **Créer la table des clés** `cles_api` dans `kuma_api_meta` (schéma hors
   Alembic), en tant que superutilisateur :
   ```bash
   docker compose -f docker/docker-compose.prod.yml --env-file .env.prod \
     run --rm \
     -e META_DB=kuma_api_meta \
     -e META_USER=$PGUSER -e META_PASSWORD=$PGPASSWORD \
     api python -m kuma_data_core.db.meta
   ```

## Phase 3 - Publier la première édition

10. **En local** (machine de référence) : exporter une édition.
    ```powershell
    .\scripts\publication\exporter-edition.ps1
    ```
    Produit `out/publication/edition_<date>_<rev>.dump` + `.json`.
11. **Transférer** le couple dump + JSON vers le VPS :
    ```bash
    scp -P <port> out/publication/edition_*.dump out/publication/edition_*.json \
      <utilisateur>@<IP>:~/kuma-data-core/out/publication/
    ```
12. **Sur le VPS** : publier (restauration en base neuve, contrôles de
    non-fuite, grants au rôle lecture seule, mise à jour de `EDITION_DB`).
    Le second argument est le fichier d'environnement de l'API : le script
    y met à jour la ligne `EDITION_DB` directement (les autres secrets sont
    préservés), pas besoin de l'éditer à la main.
    ```bash
    export PGUSER=... PGPASSWORD=...   # superutilisateur
    KUMA_PG_CONTENEUR=kuma-postgres-prod \
      bash scripts/publication/publier-edition.sh \
      out/publication/edition_<date>_<rev>.dump .env.prod
    ```

## Phase 4 - Démarrer l'API et le TLS

14. **Démarrer (ou recréer) la pile** (API + Caddy) :
    ```bash
    docker compose -f docker/docker-compose.prod.yml --env-file .env.prod up -d
    ```
    L'API lit `EDITION_DB` depuis son environnement au démarrage du conteneur ;
    une bascule d'édition prend effet en **recréant le conteneur API**
    (`... up -d api`), pas par un simple rechargement.
15. **DNS** : vérifier que l'enregistrement A `<domaine>` -> IP est propagé.
    Caddy obtient et renouvelle le certificat Let's Encrypt automatiquement au
    premier accès HTTPS.
16. **Vérifier** :
    ```bash
    curl https://<domaine>/v1/health      # {"statut":"operationnel", "edition":"edition_..."}
    curl https://<domaine>/v1/edition      # métadonnées + couverture
    ```

## Phase 5 - Vérification et supervision

- [ ] **Émettre une clé self-service** et l'essayer sur un endpoint privé :
  ```bash
  curl -X POST https://<domaine>/v1/cles \
    -H 'Content-Type: application/json' \
    -d '{"email":"toi@exemple.org","usage_prevu":"test go-live"}'
  # puis : curl https://<domaine>/v1/localites -H "Authorization: Bearer <cle>"
  ```
- [ ] **Ping externe** (UptimeRobot ou équivalent) sur
      `https://<domaine>/v1/health`.
- [ ] **Confirmer le pare-feu** : `sudo ufw status` - seuls le port SSH, 80
      et 443 ouverts.
- [ ] **Sauvegarde de la base LOCALE** (la référence) planifiée et poussée
      hors de la machine locale. Le VPS, lui, ne détient rien d'irremplaçable.

## Republier une édition (routine ultérieure)

Après chaque vague d'ingestion mergée, ou à la cadence retenue :
`exporter-edition.ps1` (local) -> `scp` du dump + JSON -> `publier-edition.sh`
(VPS, met à jour `EDITION_DB` dans `.env.prod`) -> `docker compose ... up -d api`
(recrée le conteneur API). L'édition précédente reste en réserve N-1.

Rollback : remettre l'ancien nom dans `EDITION_DB` (`.env.prod`) et recréer le
conteneur API. La base de l'édition précédente est conservée, la bascule est
donc quasi instantanée (recréer un conteneur applicatif sans état = quelques
secondes).
