# Conventions de nommage

Ces règles s'appliquent à toute évolution du schéma SQL, du code Python
et de la documentation. Elles ont valeur normative.

## Langue

- **SQL (tables, colonnes, contraintes, index, schémas)** : français.
- **Python (modules, classes, fonctions, variables)** : anglais, en
  cohérence avec l'écosystème technique. Les identifiants Python qui
  font directement écho à un nom SQL conservent toutefois la racine
  française (par exemple, le modèle `Source` représente la table
  `sources`, mais une colonne `niveau_confiance` est exposée par
  l'attribut `niveau_confiance` du modèle Python).
- **Documentation** : français.
- **Messages de log et exceptions** : français pour les messages
  destinés à l'utilisateur final, anglais pour les messages techniques
  destinés au développeur.

## Tables

- Au pluriel, en minuscules, en snake_case français.
- Pas de préfixe de schéma dans le nom logique de la table.
- Exemples : `sources`, `localites`, `unites`, `contributeurs`,
  `audit_log`, `mesures_irradiation`.

## Colonnes

- En minuscules, en snake_case français.
- Une colonne représente une grandeur ou une relation, jamais une
  abréviation cryptique.
- Les booléens sont préfixés par `est_` ou `a_` lorsque cela améliore la
  lecture (`est_publique`, `a_donnees_brutes`).
- Les dates et horodatages utilisent les suffixes :
  - `_le` pour un horodatage instantané (`cree_le`, `modifie_le`)
  - `_du` et `_au` pour une période de validité (`valide_du`,
    `valide_au`)
  - `_a` est évité car ambigu en français.
- Les colonnes de métadonnées récurrentes adoptent un nom canonique :
  `source_id`, `methode_collecte`, `niveau_confiance`, `date_collecte`,
  `date_peremption`, `auteur_saisie`, `statut`.

## Clés primaires et étrangères

- Clé primaire : `id`, type `bigint` (ou `uuid` pour les entités
  exposées publiquement, à décider au cas par cas).
- Clé étrangère : `<table_singulier>_id`. Exemples : `source_id` pour
  une référence vers `sources`, `localite_id` pour `localites`.
- Une clé étrangère peut être nommée différemment lorsqu'elle exprime un
  rôle (`auteur_id` pour une FK vers `contributeurs` exprimant la
  paternité d'une saisie).

## Contraintes

- Préfixe systématique selon la nature :
  - `pk_` pour la clé primaire (généralement implicite, mais nommée
    explicitement si Alembic le permet)
  - `fk_<table>_<colonne>` pour une clé étrangère
  - `uq_<table>_<colonne(s)>` pour une contrainte d'unicité
  - `ck_<table>_<règle>` pour une contrainte de vérification
  - `ex_<table>_<concept>` pour une contrainte EXCLUDE (PostgreSQL,
    typiquement utilisée pour le versioning temporel avec l'extension
    `btree_gist` + `tstzrange`). `<concept>` décrit la propriété
    d'exclusivité (par exemple `identite_periode`).
- Exemples : `fk_mesures_irradiation_source_id`,
  `uq_localites_nom_pays`, `ck_niveau_confiance_valide`,
  `ex_mesures_ressource_identite_periode`.
- **Cas particulier des listes fermées (catégoriels)** : le nom de la
  contrainte CHECK est de la forme `ck_<table>_<champ>_valide`, avec le
  suffixe `_valide` systématique. Exemples :
  `ck_contributeurs_statut_valide`, `ck_unites_systeme_valide`,
  `ck_localites_type_valide`, `ck_sources_type_source_valide`,
  `ck_sources_fiabilite_valide`. Les CHECK de cohérence multi-colonnes
  (soft delete, démographie, etc.) conservent un descriptif libre :
  `ck_contributeurs_actif_desactive_coherent`,
  `ck_localites_demographie_coherente`.

> *Exception : `ck_audit_log_type_operation` a été posée sans
> le suffixe `_valide`. Conservée en l'état, à corriger lors d'une
> future migration corrective si la table `audit_log` fait l'objet
> d'autres modifications.*

## Index

- Préfixe `idx_` suivi du nom de table et des colonnes indexées.
- Exemples : `idx_mesures_irradiation_localite_id_date_collecte`,
  `idx_sources_url_unique`.
- Les index uniques utilisent à la place le préfixe `uq_` (cohérent avec
  les contraintes d'unicité).

## Vues

- Préfixe `v_` suivi d'un descriptif court de la projection ou du
  filtrage appliqué.
- Exemples : `v_mesures_avec_niveau_effectif`,
  `v_grandeurs_metier_courantes`.
- Les vues servent à exposer une lecture facilitée d'une table de base
  (filtres pré-appliqués, colonnes calculées via `COALESCE` ou
  équivalent). Les opérations d'écriture passent par la table de base,
  jamais par la vue : l'audit applicatif s'appuie sur les triggers
  posés sur les tables, qui ne se déclenchent pas via la vue.

## Catégoriels et listes fermées

Kuma Data Core **n'utilise pas** les types `ENUM` natifs PostgreSQL
(`CREATE TYPE ... AS ENUM`). Toute colonne porteuse d'une liste fermée
de valeurs est typée `VARCHAR(N)` et contrainte par un `CHECK IN (...)`.

Justification : les ENUM PostgreSQL sont verrouillants à faire évoluer
(ajout de valeur supporté mais retrait/renommage extrêmement lourd ;
pas de `CHECK` exploitable côté Alembic ; coercion implicite parfois
surprenante). `VARCHAR + CHECK` reste auditable, lisible dans
`information_schema`, et révisable par migration corrective standard.

- **Type** : `VARCHAR(N)`, `N` calibré sur la valeur la plus longue
  attendue plus marge raisonnable (24, 32, 50, 64 selon le cas).
- **Valeurs** : minuscules, snake_case, ASCII pur (sans accents). Ex. :
  `brut`, `valide_auto`, `valide_humain`, `publie`, `deprecie`.
- **Contrainte** : `CHECK (<champ> IN ('valeur_1', 'valeur_2', ...))`,
  nommée `ck_<table>_<champ>_valide` (cf. section *Contraintes*).
- **Côté SQLAlchemy** : `Mapped[str]` typé `String(N)`, sans
  `sa.Enum`. La liste des valeurs autorisées peut être dupliquée dans
  une constante Python (par exemple
  `STATUTS_AUTORISES = frozenset({...})`) pour validation applicative
  en amont du `CHECK`. L'introduction est progressive, sans rétroportage
  obligatoire.

Cette règle codifie la pratique en vigueur sur les six tables socles,
toutes en `VARCHAR + CHECK`.

## Codes métier des référentiels

Les tables de référentiel (`unites`, `grandeurs_referentiel`, etc.)
exposent une colonne `code` qui sert de clé naturelle métier
(`UNIQUE NOT NULL`, citée dans les FK aval). Les valeurs de cette
colonne suivent les règles ci-dessous.

- **ASCII pur, snake_case, minuscules**. Pas d'accents, pas
  d'espaces, pas de tirets. `metre` (pas `mètre`),
  `annee_calendaire` (pas `année`), `poa_parametrable`
  (pas `poa_paramétrable`).
- **Français descriptif quand un terme français existe** :
  `seconde`, `kilogramme`, `cheval_vapeur_metrique`,
  `fraction_diffuse`, `productible_specifique_theorique`.
- **Acronyme canonique de la discipline quand il existe** :
  `hep`, `kt`, `dni`, `ghi`. Conservés en minuscules même quand
  l'usage typographique standard est en majuscules (`Kt`, `GHI`).
- **Composition acronyme + qualificatif français autorisée** :
  `btu_internationale`, `kwh_par_m2_jour`, `mj_par_m2_jour`.
- **Ratios** composés via `_par_` : `watt_par_metre_carre`,
  `kwh_par_m2_an`. Pas de `/`, pas de `per`.
- **Distinction `code` vs `libelle`** : la colonne `code` reste
  ASCII pur ; la colonne `libelle` (titre humain) peut porter
  accents et casse normale (`Indice de clarté Kt`,
  `POA paramétrable`).

## Séries (`series_metadonnees`)

La table `series_metadonnees` expose une colonne `code` qui sert
de clé naturelle métier (`UNIQUE NOT NULL`). Les valeurs de cette
colonne suivent un pattern composite formalisé ci-dessous.

### Pattern général

```
<localite_alias>_<grandeur>_<source>_<plage>
```

avec :

- `<localite_alias>` : alias court de la localité (cf. *Mapping
  `localite_alias`* ci-dessous).
- `<grandeur>` : `code` de la table `grandeurs_referentiel` (ex.
  `ghi`, `dni`, `dhi`, `t2m`, `rh2m`, `kt`, `hep`, `fraction_diffuse`,
  `humidex`, `productible_specifique_theorique`,
  `variabilite_journaliere`).
- `<source>` : `code` de la table `sources` (ex. `nasa_power`,
  `kuma_calculs`).
- `<plage>` : plage temporelle couverte au format `YYYY_YYYY` (année
  de début et année de fin incluses, ex. `2021_2025`).

### Exemples

- `gin_conakry_ghi_nasa_power_2021_2025` (Conakry-Kaloum, GHI
  NASA POWER, 2021-2025)
- `gin_kindia_hep_kuma_calculs_2021_2025` (Kindia, HEP calculée
  par Kuma, 2021-2025)
- `gin_labe_humidex_kuma_calculs_2021_2025` (Labé, Humidex
  calculé par Kuma, 2021-2025)

### Mapping `localite_alias`

`<localite_alias>` est généralement identique à la valeur de
`localites.code`. Une exception est actée :

| `localites.code` | `<localite_alias>` |
|---|---|
| `gin_conakry_kaloum` | `gin_conakry` (sans suffixe `_kaloum`) |
| `gin_kankan` | `gin_kankan` |
| `gin_kindia` | `gin_kindia` |
| `gin_labe` | `gin_labe` |
| `gin_mamou` | `gin_mamou` |
| `gin_nzerekore` | `gin_nzerekore` |

**Exception Conakry-Kaloum** : la localité pilote de Conakry est
ingérée sous `localites.code = 'gin_conakry_kaloum'` (sous-préfecture
côtière représentative de la commune urbaine), mais les codes de
série utilisent le préfixe `gin_conakry` sans le suffixe `_kaloum`.
Pattern introduit en migration 016, formalisé par
le helper `_prefixe_ville_pour_serie(localite_code)` introduit en
migration 028. Le helper centralise la
résolution et est consommé par les migrations 028 à 034.

### Décompte factuel

66 séries présentes (vérification par requête
SQL `SELECT COUNT(*) FROM series_metadonnees`) :

- 36 séries brutes : 5 grandeurs (`ghi`, `dni`, `dhi`, `t2m`, `rh2m`)
  × 6 villes pilotes en migrations 016, 018, 020, 022 + 6 séries `kt`
  (1 par ville) en migration 028.
- 30 séries calculées : 6 séries `hep` (migration 026) +
  24 séries de 4 grandeurs calculées par Kuma (`fraction_diffuse`,
  `humidex`, `productible_specifique_theorique`,
  `variabilite_journaliere`) × 6 villes en migrations 030 à 034.

### Extension future

L'introduction d'autres localités avec sous-divisions (par exemple
`gin_kankan_centre`, `gin_kankan_region`, etc.) suivra le pattern
défini ici. La décision d'introduire ou non un alias court (analogue
à `gin_conakry` pour `gin_conakry_kaloum`) sera arbitrée au cas par
cas, en pesant la cohérence
visuelle des codes de série contre la traçabilité de la sous-division
dans `localites.code`.

## Schémas

- Schéma par défaut : `public`.
- Si une séparation par substrat devient nécessaire, les schémas
  prendront le nom du substrat en français : `physique`, `infrastructure`,
  `technologie`, `economie`, `usages`.

## Migrations Alembic

Voir [`02-migrations.md`](02-migrations.md) pour les règles spécifiques
aux migrations.

## Code Python

- Modules : snake_case, courts, en anglais (`models.py`, `database.py`,
  `settings.py`).
- Classes : PascalCase, en anglais lorsqu'elles décrivent un concept
  technique générique (`Settings`, `DatabaseEngine`), en cohérence avec
  le nom logique du domaine lorsqu'elles modélisent une table (la
  classe SQLAlchemy `Source` modélise la table `sources`).
- Fonctions et variables : snake_case, anglais par défaut. Les
  identifiants directement issus du domaine de données conservent leur
  racine française (`niveau_confiance`, `date_collecte`).
- Constantes : `UPPER_SNAKE_CASE`.

## Fichiers de documentation

- Préfixe numérique à deux chiffres pour ordonner :
  `01-vision.md`, `02-migrations.md`, etc.
- Nom en kebab-case français.
- Une majuscule en début de titre, pas de point final dans les titres.

## Audit et convention de PK pour les tables auditées

Toute table auditée par le mécanisme de triggers PL/pgSQL
`kuma_log_audit()` (voir [`../architecture/03-audit.md`](../architecture/03-audit.md))
**DOIT** avoir une PK auto-incrémentée nommée `id`, de type
`BIGINT IDENTITY` (ou son alias hérité `BIGSERIAL`). La fonction
d'audit suppose cette convention pour construire la référence de ligne
stockée dans `audit_log.id_ligne_auditee`.

Cette règle s'applique à toutes les tables structurantes du noyau Kuma
Data Core. Les tables de jonction pure ou les tables techniques non
auditées peuvent déroger à cette convention si nécessaire, sous réserve
de justifier le choix dans la migration concernée.

## API FastAPI

Les conventions ci-dessous s'appliquent au sous-paquet
`src/kuma_data_core/api/`. La règle
`pep8-naming` (`N`) de ruff y est désactivée pour permettre les
identifiants français.

### Routeurs

- Nom de fichier en français singulier : `health.py`, `sources.py`,
  `localites.py`, `audit.py` (ne pas pluraliser le nom de fichier).
- Variable du routeur : `routeur` (pas `router`).
  ```python
  routeur = APIRouter(prefix="/health", tags=["sante"])
  ```
- Routeur agrégateur d'une version : `routeur_v<N>` (`routeur_v1`).

### Fonctions endpoints

Nom français descriptif, à l'infinitif ou au substantif selon la
nature de l'opération :

- Lecture : `sante`, `sante_detailee`, `lister_sources`,
  `recuperer_source`.
- Écriture : `creer_source`, `mettre_a_jour_source`, `desactiver_source`.

### Modèles Pydantic de requête / réponse

Préfixe `Requete` ou `Reponse` suivi du sujet en français, en
PascalCase :

- `ReponseSantePublique`, `ReponseSanteDetailee`.
- `RequeteCreationSource`, `ReponseSource`, `ReponseListeSources`.

### Codes d'erreur

`UPPER_SNAKE_CASE` français, regroupés par préfixe métier dans la
`StrEnum` `CodeErreur` (voir `api/codes_erreur.py`) :

- `AUTH_*`           - authentification, autorisation
- `VALIDATION_*`     - validation des entrées
- `RESSOURCE_*`      - état des ressources
- `INFRASTRUCTURE_*` - dépendances externes
- `SERVEUR_*`        - erreurs internes non classifiées

Un code publié est **stable** : aucune modification ni suppression
ultérieure. Pour faire évoluer la sémantique, créer un nouveau code et
déprécier l'ancien.

### Événements de log

`snake_case` français descriptif (`api_demarrage`, `requete_traitee`,
`exception_non_geree`). Attributs structurés également en
`snake_case` français (`methode`, `chemin`, `statut`, `duree_ms`).
Pas de PII dans les logs (ni email, ni nom complet, ni clé API).
