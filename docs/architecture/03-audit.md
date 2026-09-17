# Audit et traçabilité des modifications

L'infrastructure d'audit, posée par la migration 005, trace les
modifications des tables métier via des triggers PostgreSQL vers une
table `audit_log` unique. Elle sert à qui modifie le schéma, écrit du
code applicatif ou exploite l'historique des données.

## Principe

L'audit est implémenté **côté base de données** via des triggers
PL/pgSQL. À chaque `INSERT`, `UPDATE` ou `DELETE` sur une table
auditée, un déclencheur row-level appelle la fonction générique
`kuma_log_audit()` qui inscrit une ligne dans la table `audit_log`.

Trois propriétés découlent de ce choix :

1. **Inviolable depuis l'applicatif** : aucun chemin de code Python ne
   peut omettre la trace. L'audit a lieu dans la même transaction que
   la modification - soit les deux passent, soit ni l'une ni l'autre.
2. **Universel** : tout client SQL (psql, pgAdmin, scripts ad hoc,
   futur ORM) déclenche automatiquement l'audit, sans configuration
   supplémentaire.
3. **Indépendant de l'API** : la traçabilité ne dépend pas de la
   couche FastAPI à venir, ni de SQLAlchemy.

## Architecture

```
+-----------------------------------------------------+
|  Tables auditées : sources, localites, unites,      |
|                    contributeurs                    |
+-----------------------+-----------------------------+
                        | INSERT / UPDATE / DELETE
                        v
            +-----------------------+
            |  Trigger row-level    |
            |  AFTER (par table)    |
            +----------+------------+
                       | appelle
                       v
            +------------------------+
            |  Fonction PL/pgSQL     |
            |  kuma_log_audit()      |
            |  (générique)           |
            +----------+-------------+
                       | INSERT
                       v
            +------------------------+
            |   Table audit_log      |
            +------------------------+
```

## Table `audit_log`

| Colonne | Type | Rôle |
|---|---|---|
| `id` | `BIGINT IDENTITY` | PK |
| `table_auditee` | `TEXT NOT NULL` | Nom de la table modifiée |
| `schema_audite` | `TEXT NOT NULL DEFAULT 'public'` | Schéma de la table |
| `type_operation` | `CHAR(1) NOT NULL` | `'I'`, `'U'`, `'D'` (CHECK) |
| `id_ligne_auditee` | `TEXT NOT NULL` | PK de la ligne modifiée, en `TEXT` (universel) |
| `champs_modifies` | `JSONB NULL` | Pour UPDATE : `{"col": [avant, apres]}` |
| `valeurs_avant` | `JSONB NULL` | Snapshot complet avant (UPDATE/DELETE) |
| `valeurs_apres` | `JSONB NULL` | Snapshot complet après (INSERT/UPDATE) |
| `utilisateur_pg` | `TEXT NOT NULL` | `current_user` PostgreSQL |
| `auteur_applicatif` | `TEXT NULL` | Identifiant applicatif optionnel |
| `adresse_client` | `INET NULL` | `inet_client_addr()` |
| `horodatage` | `TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()` | Instant réel (pas début de transaction) |

Cinq index couvrent les cas d'usage :

- `idx_audit_log_table_horodatage` - recherche par table.
- `idx_audit_log_horodatage` - recherche par période.
- `idx_audit_log_utilisateur_pg` - recherche par auteur PostgreSQL.
- `idx_audit_log_auteur_applicatif` - recherche par auteur applicatif
  (partiel : `WHERE auteur_applicatif IS NOT NULL`).
- `idx_audit_log_ligne` - historique d'une ligne précise.

## Identifiant applicatif

Le `current_user` PostgreSQL identifie le rôle de connexion (souvent
un compte technique mutualisé). En complément, l'applicatif peut
positionner un identifiant logique via la variable de session
PostgreSQL `kuma.auteur_applicatif`.

La fonction d'audit lit cette variable avec
`current_setting('kuma.auteur_applicatif', true)` (le second argument
`true` signifie « ne pas lever d'exception si la variable n'est pas
définie »).

### Exemple Python avec SQLAlchemy

```python
from sqlalchemy import text
from sqlalchemy.orm import Session

def avec_auteur(session: Session, auteur: str) -> None:
    """Positionne l'auteur applicatif pour la transaction courante.

    Le troisième argument ``true`` rend la valeur LOCALE à la
    transaction : elle est automatiquement effacée au COMMIT ou
    au ROLLBACK. Aucun nettoyage manuel n'est nécessaire.
    """
    session.execute(
        text("SELECT set_config('kuma.auteur_applicatif', :val, true)"),
        {"val": auteur},
    )


# Usage
with Session(engine) as session:
    avec_auteur(session, "script_ingestion_nasa_power")
    session.execute(text("UPDATE sources SET fiabilite = 'haute' WHERE id = 42"))
    session.commit()

# La ligne d'audit générée aura :
#   utilisateur_pg     = 'kuma_admin'
#   auteur_applicatif  = 'script_ingestion_nasa_power'
```

### Conventions pour les valeurs d'`auteur_applicatif`

Pistes de conventions :

- Préfixes par domaine : `script_<nom>`, `cli_<commande>`,
  `api_<endpoint>`, `migration_<numero>`.
- Pas de PII (pas d'email, pas de nom complet).
- Format `snake_case` court (< 80 caractères).

## Tables actuellement auditées

Au sortir de la migration 005 :

- `contributeurs`
- `localites`
- `sources`
- `unites`

Toute nouvelle table structurante (typiquement la future table
`mesures`) devra être ajoutée à ce périmètre via une migration dédiée
qui crée le trigger `trg_audit_<table>`.

## Migrations de masse : suspension ciblée du trigger

**Décision du 2026-08-10.** Les migrations de seed ou d'ingestion de
masse **reproductibles** (déversement initial d'une source rejouable :
seed offline committé, ingestion NASA POWER gardée) suspendent le
trigger d'audit de la table cible le temps de leurs écritures
(`ALTER TABLE ... DISABLE TRIGGER trg_audit_<table>`, réactivation en
fin de migration ; geste transactionnel, un rollback restaure l'état).
Même règle pour leurs downgrades (DELETE de masse) et pour les
migrations de contrôle qualité algorithmique qui requalifient ces
mêmes lignes en masse.

Motif : l'audit trace l'édition, pas le déversement. Le rejeu du
backfill journalier (4 147 830 insertions, migration 107, antérieure à
cette décision) a montré le coût du trigger par ligne : 19 minutes
d'insertion en local, 24 minutes de job CI, et autant de lignes
d'`audit_log` écrites **à chaque rejeu complet** (CI, nightly en
double via le roundtrip, rebuild local) sans aucune valeur de
traçabilité : la donnée est déjà tracée par le seed committé et la
migration elle-même.

Bornes strictes : la suspension est **par table et par migration**,
jamais globale (`session_replication_role` interdit) ; elle ne
s'applique qu'aux écritures rejouables à l'identique. Toute écriture
éditoriale (correction humaine, override de confiance, dépréciation)
reste auditée sans exception.

## Rétention

**Politique courante** : rétention infinie. Aucune purge automatique.
La table `audit_log` croît indéfiniment.

Cette politique sera ré-examinée quand on disposera de chiffres réels
sur le volume d'écriture. Options envisageables : partitionnement
déclaratif par mois, archivage froid au-delà de N années, agrégation
après une durée configurable.

## Pièges connus

### Convention de PK obligatoire

La fonction `kuma_log_audit()` utilise `OLD.id::TEXT` / `NEW.id::TEXT`
pour construire `id_ligne_auditee`. **Toute table auditée doit avoir
une colonne `id` simple** (PK auto-incrémentée). Voir
[`docs/conventions/01-naming.md`](../conventions/01-naming.md).

Si une future table devait avoir une PK composite ou un nom différent,
il faudrait refondre la fonction (paramétrer le nom de la colonne PK)
plutôt que d'introduire des exceptions silencieuses.

### Colonnes sensibles

`to_jsonb(NEW)` et `to_jsonb(OLD)` sérialisent **toutes** les colonnes
de la ligne, y compris d'éventuelles colonnes sensibles (mots de passe
hachés, tokens, secrets). Au moment de la migration 005, **aucune
colonne sensible n'existe** sur les 4 tables auditées (vérifié).

Avant d'ajouter une colonne sensible à une table auditée, prévoir une
stratégie d'exclusion : soit refonder `kuma_log_audit()` pour
permettre une liste de colonnes ignorées par table, soit déplacer la
colonne sensible dans une table séparée non auditée.

### Données personnelles (RGPD)

`contributeurs` contient des données personnelles (`email_principal`,
`notes_internes`). Ces données sont auditées et conservent leur
historique dans `audit_log`. Les implications RGPD sont à anticiper
avant toute ouverture de l'API publique.

## Évolutions anticipées

### Séparation des rôles PostgreSQL et propriété de la fonction

La fonction `kuma_log_audit()` est créée en `SECURITY DEFINER` :
elle s'exécute avec les droits du rôle propriétaire. Ce propriétaire
est aujourd'hui `kuma_admin` (le seul rôle existant), qui détient déjà
tous les droits - la sécurité est triviale.

Lors d'une séparation des rôles applicatifs et administratifs, il
faudra :

1. Créer un rôle dédié `kuma_audit_writer` avec les droits stricts
   nécessaires : `INSERT` sur `audit_log`, lecture des tables
   auditées (pour `to_jsonb(...)`).
2. Transférer la propriété de la fonction :
   `ALTER FUNCTION kuma_log_audit() OWNER TO kuma_audit_writer`.
3. Restreindre les rôles applicatifs à `INSERT` / `SELECT` sur
   `audit_log` (pas d'`UPDATE` / `DELETE`).

### Immuabilité de `audit_log` par GRANT/REVOKE

La protection en INSERT-only de `audit_log` reposera sur les droits
PostgreSQL une fois la séparation des rôles effective :

```sql
REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM PUBLIC;
GRANT INSERT, SELECT ON audit_log TO <roles_applicatifs>;
```

Aucun trigger défensif n'est posé : empiler trigger + GRANT donnerait
une fausse sécurité (deux mécanismes à maintenir, risque
d'incohérence). Avec un seul rôle, l'audit sert à **tracer**, pas à se
protéger de soi-même.

### Partitionnement déclaratif

À envisager si la table dépasse plusieurs millions de lignes ou si
les requêtes par fenêtre temporelle deviennent trop lentes.
Partitionnement par mois sur `horodatage` (`PARTITION BY RANGE`).

### Archivage froid

Pour les entrées au-delà d'un certain âge (par exemple 5 ans),
déplacement vers une table d'archive ou export vers un stockage
externe (S3, Glacier). À cadrer avec la politique de rétention
légale et les obligations RGPD.

### Exclusion sélective de colonnes

Évolution future de `kuma_log_audit()` pour accepter un paramètre
(via `TG_ARGV`) listant les colonnes à exclure des `valeurs_avant` /
`valeurs_apres`. Permettrait d'auditer une table tout en masquant
les colonnes sensibles. Non implémenté (pas de cas d'usage
immédiat).
