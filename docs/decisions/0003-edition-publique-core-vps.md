# ADR-0003 · Édition publique du Core sur VPS

> **Statut** · Accepté · 2026-07-02
> **Repo concerné** · `siba-IEE/kuma-data-core` (producteur API)

## Contexte

Le Core vit aujourd'hui en local : c'est là que se font l'ingestion, l'audit
par triggers (`audit_log`, `kuma_log_audit()`), le versioning temporel non
destructif et les corrections. L'API FastAPI existe (`/v1`, 19 endpoints) mais
elle est **entièrement privée** : hors `GET /v1/health`, tout endpoint exige une
clé admin (`api/dependencies.py:verifier_cle_api`), les clés vivent en variables
d'environnement (`Settings.api_cle_solar_bridge`, `api_cle_admin`), la table
`cles_api` est marquée « prévue ». La doc de référence (§2.2) l'écrit
explicitement : « aucun compte, aucun flux d'inscription, aucune clé publique ».

L'objectif est d'exposer le Core au public sur un VPS. La question n'est donc pas
seulement « comment déployer », mais « comment servir du public à partir d'une
base pensée privée, sans exposer ce qui ne doit pas l'être, et sans transformer
la synchronisation en un mécanisme continu fragile ».

Le modèle retenu transforme un problème technique (synchronisation) en acte
éditorial (publication) : le VPS ne reçoit pas un flux, il reçoit des **éditions**
datées, citables et reproductibles - cohérent avec le versioning des données, les
dépôts figés à DOI (`.zenodo.json`, `CITATION.cff`) et la logique de référence
datée déjà en place.

Cet ADR enregistre les arbitrages qui débloquent la construction et fixe le plan
séquencé.

## Décisions

### D1 · Modèle d'édition : dump complet, restauration, bascule par repointage

La base locale reste la **référence** unique. Chaque poussée vers le VPS est une
édition : « état publié du Core au JJ-MM-AAAA ». Le rythme est éditorial (après
une vague d'ingestion mergée, ou mensuel), pas un mécanisme automatique.

Mécanisme, vu la taille de la base (centaines de Mo au plus) :

1. **Local** - construction d'une **base d'édition intermédiaire** (D5), puis
   `pg_dump` de cette base.
2. **Transfert** - `scp`/`rsync` vers le VPS.
3. **VPS** - restauration dans une base neuve `kuma_edition_<AAAAMMJJ>`, contrôles
   de fumée (smoke checks), puis **bascule par repointage** : l'API lit la variable
   d'environnement `EDITION_DB` (sans préfixe `KUMA_`, conformément à la convention
   sur les variables d'environnement) qui désigne la base active.
   `publier-edition.sh` met à jour cette variable dans le fichier d'environnement
   de l'API (`.env.prod`, le seul que le conteneur lise) ; la bascule prend effet
   en **recréant le conteneur API** (`docker compose up -d api`), pas par un simple
   rechargement (le DSN est figé au démarrage du process). L'édition précédente est
   conservée une génération en réserve : rollback = remettre l'ancien nom dans
   `EDITION_DB` et recréer le conteneur (quasi instantané, conteneur applicatif sans
   état ; la base précédente est intacte).

**Repointer une variable plutôt que `ALTER DATABASE ... RENAME`** : mettre à jour
`EDITION_DB` laisse intactes les bases de service du VPS (clés, état de rate limiting
- cf. D3), qui ne doivent pas être écrasées par une édition. Le renommage, lui,
remplacerait la base entière et emporterait ces états.

Conséquences : le VPS ne détient **aucune donnée non reconstructible**. S'il brûle,
on remonte un VPS neuf et on rejoue la dernière édition. La sauvegarde sérieuse
porte sur la base **locale** ; sauvegarder le VPS devient quasi optionnel. Pas de
migration Alembic à orchestrer en prod : chaque édition embarque son schéma déjà
appliqué (`alembic check` en CI garantit la cohérence en amont), ainsi que sa table
`alembic_version` (traçabilité de la révision de schéma embarquée).

### D2 · Lecture seule sur l'édition, écriture confinée au service

Sur le VPS, l'API se connecte à la base d'édition via un rôle PostgreSQL **en
lecture seule** (`kuma_api_ro`, `SELECT` sur les tables et vues publiques
uniquement, aucun droit d'écriture). Un attaquant qui compromet l'API ne peut rien
écrire dans les données publiées. Les triggers d'audit ne servent à rien sur le VPS
puisque rien n'y écrit : l'audit vit en local, là où les modifications se font.

Nuance à ne pas surdire : l'API du VPS **écrit**, mais uniquement dans la base de
service `kuma_api_meta` (émission de clés, cf. D3) et dans Redis (compteurs de rate
limiting). La formulation exacte est donc : *lecture seule sur l'édition, écriture
confinée à la base de service*. L'émission self-service de clés est la seule
surface d'écriture exposée au public : elle reçoit sa propre protection dès WP6
(limite d'émission par IP, vérification d'e-mail à évaluer).

**Contrainte de déploiement à honorer en WP8 (revue de sécurité 2026-07-02)** : les
deux rôles `kuma_api_ro` (lecture seule sur l'édition) et `kuma_api_service`
(écriture sur `kuma_api_meta`) sont **mutuellement exclusifs** par construction du
provisioning - `kuma_api_ro` n'a pas `CONNECT` sur `kuma_api_meta`, et
`kuma_api_service` n'a pas de `SELECT` sur les éditions. Or les deux DSN
(`database_url`, `database_url_meta`) sont aujourd'hui construits depuis un **seul**
couple `postgres_user`/`postgres_password`. WP8 doit donc introduire un second
couple d'identifiants (`meta_user`/`meta_password`) pour que le moteur d'édition
tourne réellement en `kuma_api_ro` et le moteur méta en `kuma_api_service`. À défaut,
l'opérateur serait tenté de tout faire tourner sous un rôle sur-privilégié (voire
`postgres`), ce qui annulerait silencieusement la garantie de lecture seule de ce
même D2. Ce n'est pas une vulnérabilité exploitable (aucune entrée attaquable ; tous
les modes de panne échouent en 401), mais la garantie de moindre privilège n'est
tenue que si les deux identifiants existent. Le code applicatif ne doit jamais
tourner sous un rôle superutilisateur.

### D3 · Régime d'accès public : clé gratuite obligatoire

**Décision** : accès public sous **clé gratuite obligatoire** (et non anonyme façon
NASA POWER). L'inscription est libre-service et légère ; on garde le mécanisme
`Authorization: Bearer <cle>` existant, on ajoute l'émission self-service et la
gestion de cycle de vie.

Justification : cohérent avec l'infra d'auth déjà en place (le Bearer ne change
pas), avec l'éthos de traçabilité et de citation (« données consultées via la clé
X, édition Y »), et permet un rate limiting **par consommateur** plutôt que par IP.

Implications structurelles :

- Matérialiser la table `cles_api` (révocation, rotation, quotas) - déjà anticipée
  dans le code (`dependencies.py`, `config.py`).
- **La table `cles_api` ne fait pas partie de l'édition.** Les clés sont un état du
  VPS, pas une donnée éditoriale locale. Elles vivent dans une base de service
  séparée `kuma_api_meta`, persistante à travers les bascules d'édition (c'est ce
  que protège le repointage de D1). Le dump de l'édition n'emporte jamais de clé.
- **`kuma_api_meta` vit hors de la lignée Alembic.** Les migrations Alembic
  versionnent la base de référence, et `alembic check` garantit l'alignement
  modèles <-> référence ; une table qui n'existe que sur le VPS casserait cet
  invariant. Le schéma de `kuma_api_meta` est provisionné par un script SQL
  versionné (`scripts/publication/`), et son futur modèle SQLAlchemy (WP6)
  utilisera une `Base` déclarative distincte, hors `Base.metadata` de référence.
- Rate limiting par clé via Redis (déjà dans la stack `docker-compose`).

### D4 · Premier public servi : développeurs / outils dérivés

**Décision** : le premier public est celui des **développeurs et outils dérivés**
(Solar Bridge, outils tiers). Priorité d'exposition et de polissage :

| Endpoint | Rôle pour ce public | État |
|---|---|---|
| `GET /v1/series` | Catalogue paginé, contrat figé (ADR-0001) | Prêt |
| `GET /v1/series/{code}` | Détail + mesures, JSON/CSV | Prêt |
| `GET /v1/localites` + `/{code}` | Référentiel géographique (ADR-0002) | Prêt |
| `GET /v1/horaire/...` | Horaire **stocké** (repli passe-plat désactivé, cf. D6) | À profiler |

Les grandeurs F2 paramétrables, l'atlas d'incertitude et les fiches
méthodologiques restent exposés mais ne sont pas la cible de polissage prioritaire
de cette édition. Le contrat de catalogue étant déjà figé, c'est aussi le chemin
qui demande le moins de travail éditorial pour une première ouverture.

### D5 · Filtre de publication (garde anti-fuite)

Le dump ne doit embarquer que ce qui est public. Le filtre est écrit **une fois, en
clair**, comme un manifeste versionné et **testé** :
`src/kuma_data_core/publication/manifeste.py` (module du package, donc couvert par
mypy strict), avec un test de complétude (`tests/unit/publication/`) qui échoue si
une table de `Base.metadata` n'est pas explicitement classée - une table ajoutée
demain ne peut pas fuiter silencieusement, la CI casse.

**Mécanique : l'assainissement se fait en local, jamais sur le VPS.** `pg_dump` ne
transforme pas les données ; assainir après restauration exigerait d'écrire sur le
VPS, avec des triggers d'audit restaurés pointant vers une `audit_log` exclue. Le
script d'export (WP1) construit donc une **base d'édition intermédiaire locale**
(copie de la référence + filtre + assainissement + suppression de la fonction
`kuma_log_audit()` et des triggers `trg_audit_*`), et c'est *elle* qui est dumpée.
Le VPS ne reçoit jamais rien à nettoyer.

Règles :

| Objet | Traitement | Raison |
|---|---|---|
| `audit_log` | **Exclu** | Audit interne, jamais exposé par l'API. Volumineux et sensible. |
| `cles_api` | **Hors édition par construction** | État de service du VPS (D3), hors schéma de référence. |
| `contributeurs` | **Inclus mais assaini** | FK `cree_par`/`modifie_par` doivent résoudre. On conserve les lignes, on neutralise les colonnes PII. `email_principal` est `NOT NULL UNIQUE` : valeur neutre **par ligne** (`contributeur-<id>@retire.invalid`), pas `NULL` ni constante. `biographie`, `notes_internes` (nullables) -> `NULL`. L'API n'expose aucun endpoint `contributeurs`. |
| Statuts éditoriaux des mesures | **Aucun filtrage par ligne au dump** | Cf. D6 : le versioning non destructif fait partie de la donnée publiée. |
| Fonction `kuma_log_audit()` + triggers `trg_audit_*` | **Supprimés de la base d'édition** avant dump | L'écriture n'a pas lieu sur le VPS ; des triggers pointant vers une table exclue seraient de toute façon cassés. |
| `alembic_version` | **Incluse** | Traçabilité de la révision de schéma de l'édition. |

Le manifeste est le premier livrable : rien ne se publie avant qu'il existe et
soit relu.

### D6 · Édition figée, sans passe-plat temps réel

**Décision** : l'édition publique sert **uniquement le stocké**. Le repli
passe-plat de `GET /v1/horaire/...` (relais live vers NASA POWER,
`api/v1/horaire.py`) est **désactivé** dans le profil public.

Justification : cohérent avec « le VPS ne détient que du reconstructible », zéro
dépendance sortante, aucune surface d'abus par relais amont, et pureté de l'édition
reproductible. Conséquence heureuse : la question du gating du temps-quasi-réel
devient **sans objet** sur l'édition publique (il n'y a pas de temps réel à
relayer).

**Ce que D6 ne dit pas** : D6 désactive un *mécanisme* (le relais temps réel), il
ne filtre pas par *statut éditorial*. Les deux questions sont indépendantes, et la
seconde est tranchée ainsi (ex-QO-1) : **l'édition embarque toutes les lignes hors
exclusions D5, tous statuts compris**, et l'API publique conserve son comportement
actuel - servir le courant `statut <> 'deprecie'` (cf. `api/v1/series.py`), le
champ `statut` restant exposé dans les réponses. Justification : l'acte éditorial,
c'est la publication de l'édition elle-même ; exiger `publie` viderait l'édition
(rien ne porte ce statut), exiger `valide_auto` amputerait le brut assumé (séries
PM EAC4, ingérées brutes par décision). Le versioning non destructif
(`deprecie`, `valide_du`/`valide_au`) fait partie de la donnée publiée : c'est lui
qui rend l'édition auditable de l'extérieur.

Mise en œuvre : un flag de configuration (p.ex. `EDITION_FIGEE=true`) qui,
pour une plage non couverte par le stocké, renvoie
`PLAGE_TEMPORELLE_NON_DISPONIBLE` plutôt que de relayer. Le comportement stocké
reste identique.

### D7 · Fraîcheur affichée comme propriété

Le retard sur la base locale est assumé, donc **affiché** : « un retard documenté
est une propriété, un retard silencieux est un défaut ». L'API expose l'édition
courante :

- Enrichissement de `GET /v1/health` avec un champ `edition` (identifiant daté).
- Endpoint dédié `GET /v1/edition` : `{ edition_id, date_publication,
  revision_source, couverture_resumee }`, non authentifié (même statut public que
  `/v1/health`).

Les métadonnées d'édition sont produites au moment de la publication (date,
révision git) et injectées dans l'édition, pas devinées côté serveur.
`revision_source` désigne le hash du **dépôt public** `siba-IEE/kuma-data-core` -
c'est lui que les utilisateurs peuvent consulter.

## Plan de construction séquencé

Ordre dicté par ce qui bloque le reste. Chaque lot est un changement cohérent unique
(convention `docs/conventions/02-migrations.md`).

| Lot | Objet | Touche | Dépend de |
|---|---|---|---|
| **WP0** | Manifeste du filtre de publication (D5) + test de complétude | `src/kuma_data_core/publication/manifeste.py`, `tests/unit/publication/` | - |
| **WP1** | Script d'export local (PowerShell) : base d'édition intermédiaire -> `pg_dump` + métadonnées d'édition (D1, D5, D7) | `scripts/publication/exporter-edition.ps1` (esprit `services-*.ps1`) | WP0 |
| **WP2** | Script VPS (bash) : restauration en base neuve, smoke checks, bascule par repointage, réserve N-1 (D1) | `scripts/publication/publier-edition.sh` | WP1 |
| **WP3** | Rôle lecture seule `kuma_api_ro` + provisioning SQL de `kuma_api_meta` (D2, D3) | `scripts/publication/`, grants | WP2 |
| **WP4** | Profil « édition figée » : désactiver le repli passe-plat, désactiver `/docs` (déjà géré par le validateur prod), CORS clos (D6) + trancher QO-3 | `core/config.py`, `api/v1/horaire.py`, `api/main.py` | - |
| **WP5** | Métadonnées de fraîcheur : `GET /v1/edition` + champ `edition` sur `/v1/health` (D7) | `api/v1/health.py`, schéma, table d'édition | WP1 |
| **WP6** | Table `cles_api` + émission self-service + révocation/rotation + protection de l'émission (D2, D3) | schéma `kuma_api_meta` hors lignée Alembic (`Base` distincte), modèle, endpoint, `dependencies.py` | WP3 |
| **WP7** | Rate limiting par clé via Redis (D3) | dépendance/middleware FastAPI | WP6 |
| **WP8** | Déploiement VPS : `docker-compose` prod, reverse proxy TLS, gestion des secrets, **second couple d'identifiants `meta_user`/`meta_password` (D2)**, **`X-Forwarded-For` de confiance pour la limite d'émission par IP**, pare-feu (Postgres/Redis jamais exposés) | `docker/`, provisioning, `config.py` | WP3, WP4 |
| **WP9** | Vérification : smoke post-bascule, **test de non-fuite** (asserter l'absence des objets exclus dans l'édition restaurée), exercice de rollback | tests, CI | transversal |

## Questions ouvertes

- **QO-2** - Cadence de publication : après chaque vague mergée, ou mensuelle fixe ?
  Décision éditoriale, sans impact bloquant sur le mécanisme.
(QO-1, statuts publiés, est tranchée dans D6. QO-3, `api_environnement`, est
tranchée en WP4 dans le sens de la doc de référence : le `Literal` de
`config.py` passe de `staging` à `integration` - la valeur `staging` n'avait
jamais été documentée ni utilisée hors du `Literal` lui-même.)

## Conséquences

### Positives

- La synchronisation devient un acte éditorial daté, citable et reproductible, aligné
  sur le versioning des données et les dépôts à DOI existants.
- Le VPS est jetable : aucune donnée non reconstructible, sauvegarde concentrée sur la
  base locale, retour arrière instantané par repointage.
- Surface d'attaque réduite : lecture seule sur l'édition, aucune dépendance
  sortante, `/docs` et audit absents en public.
- Le contrat public déjà figé (ADR-0001, ADR-0002) est réutilisé tel quel pour le
  premier public développeur.
- Le manifeste testé rend la garde anti-fuite mécanique : une table nouvelle non
  classée casse la CI.

### Dettes acceptées

- Deux chemins de base sur le VPS (édition tournante + `kuma_api_meta` persistante) à
  provisionner et documenter, dont un hors lignée Alembic.
- Le rate limiting introduit une dépendance dure à Redis côté API publique (jusqu'ici
  déclaré mais non branché, cf. référence §3.2).
- La cadence de publication reste un geste humain : un retard non publié est un retard
  invisible tant que WP5 (fraîcheur) n'est pas livré.
- L'émission self-service de clés est une surface d'écriture publique : sa protection
  (WP6) conditionne l'ouverture réelle.

## Cross-references

- [ADR-0001](./0001-contrat-v1-series-enrichi.md) · contrat `/v1/series` figé
- [ADR-0002](./0002-endpoint-localites-v1.md) · endpoint `/v1/localites`
- `docs/architecture/06-api-reference-publique.md` · référence API
- `docs/conventions/02-migrations.md` · discipline de migration
- `docs/architecture/03-audit.md` · audit par triggers (local uniquement)
