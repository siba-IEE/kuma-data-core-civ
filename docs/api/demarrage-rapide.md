# Démarrage rapide - API publique Kuma Data Core

Interroger les données climatiques et solaires d'une instance de Kuma
Data Core en quelques minutes. Le moteur est générique (le pays est un
axe de classification) ; les exemples ci-dessous portent sur l'instance
**Côte d'Ivoire**. L'API sert des **séries situées** : chaque valeur
arrive avec sa source, son unité, son niveau de confiance et ses
caveats - jamais un nombre nu.

- **Base URL** : celle du déploiement interrogé, notée `$API` dans les
  exemples (en local : `http://127.0.0.1:8000`, voir le `README`).
- **Format** : JSON par défaut, CSV en option (`?format=csv`) sur le
  détail des séries, les grandeurs F2 et l'horaire.
- **Authentification** : `Authorization: Bearer <cle>`. Seuls
  `GET /v1/health`, `GET /v1/edition` et `POST /v1/cles` sont
  accessibles sans clé.

## 1. Vérifier que l'API répond (sans clé)

```bash
API="http://127.0.0.1:8000"   # ou l'adresse du serveur public

curl "$API/v1/health"
# {"statut":"operationnel","edition":"edition_AAAAMMJJ"}

curl "$API/v1/edition"
# édition servie : identifiant, date de publication, révision source, couverture
```

`edition` vaut `null` sur un déploiement qui ne sert pas une édition
publiée (base locale de développement) ; `GET /v1/edition` y répond
alors `404 RESSOURCE_INTROUVABLE`, c'est l'état normal. La version
logicielle et l'environnement ne sont plus exposés publiquement : ils
figurent dans `GET /v1/health/db`, qui exige une clé.

## 2. Obtenir une clé (une seule fois, gratuite)

```bash
curl -X POST "$API/v1/cles" \
  -H "Content-Type: application/json" \
  -d '{"email":"vous@exemple.org","usage_prevu":"outil de dimensionnement"}'
# {"cle":"kuma_...","prefixe":"kuma_xxxxxxxx","quota_journalier":5000}
```

La clé n'est **montrée qu'une seule fois** : conservez-la. Le `prefixe`
est son identifiant public (support, révocation). Quota par défaut :
5000 requêtes/jour. L'émission n'existe que sur le serveur public : un
déploiement sans base de service répond
`404 CLES_EMISSION_NON_ACTIVEE` (en local, la clé est fournie par
variable d'environnement).

## 3. Premières requêtes authentifiées

```bash
CLE="kuma_..."   # votre clé

# Chercher une localité par son nom (insensible à la casse et aux accents)
curl "$API/v1/localites?q=san-pedro" -H "Authorization: Bearer $CLE"
# 2 localités : civ_dep_san_pedro (département) et civ_san_pedro (région)

# Le catalogue des séries GHI du département d'Abidjan
curl "$API/v1/series?localite=civ_dep_abidjan&grandeur=ghi" \
  -H "Authorization: Bearer $CLE"
# 5 séries : NASA POWER mensuelle et journalière (1991-2025),
# CAMS (2005-2025), SARAH-3 et ERA5 (2005-2023)

# Le détail d'une série + ses mesures, sur la normale 1991-2020
curl "$API/v1/series/nasa_power_ghi_mensuel_civ_dep_abidjan?from=1991-01&to=2020-12" \
  -H "Authorization: Bearer $CLE"
# "pagination_mesures": {"total": 360, "limit": 1000, "offset": 0}
```

Chaque série du catalogue porte sa `granularite` (`mensuel`,
`journalier`, `horaire`, ou `null` pour une grandeur calculée) ; le
filtre `?granularite=` la sélectionne. Pour un même lieu, une même
source et une même grandeur, une série mensuelle et une série
journalière peuvent coexister (c'est le cas ici pour NASA POWER).

## 4. Exemples par langage

### Python : lire une série complète, page par page

Le détail d'une série renvoie **au plus 1000 mesures par défaut**
(10 000 au maximum avec `limit`). Le bloc `pagination_mesures` dit
combien la fenêtre `from`/`to` en contient : sans lui, une moyenne
calculée sur la première réponse porterait sur une partie de la série
seulement.

```python
import requests

API = "http://127.0.0.1:8000"   # adresse du déploiement interrogé
CLE = "kuma_..."
h = {"Authorization": f"Bearer {CLE}"}

# Trouver la série GHI journalière NASA POWER d'Abidjan
cat = requests.get(f"{API}/v1/series",
                   params={"localite": "civ_dep_abidjan", "grandeur": "ghi",
                           "source": "nasa_power", "granularite": "journalier"},
                   headers=h).json()
code = cat["items"][0]["code"]   # nasa_power_ghi_journalier_civ_dep_abidjan

# Lire toutes les mesures de 1991-2020 (chaque mesure porte son passeport)
valeurs, offset = [], 0
while True:
    page = requests.get(f"{API}/v1/series/{code}",
                        params={"from": "1991-01-01", "to": "2020-12-31",
                                "limit": 10000, "offset": offset},
                        headers=h).json()
    valeurs += [m["valeur"] for m in page["mesures"]]
    pagination = page["pagination_mesures"]
    offset += pagination["limit"]
    if offset >= pagination["total"]:
        break

assert len(valeurs) == pagination["total"]   # 10 958 jours, en 2 pages
print("Source :", page["source_label"], "| unité :", page["grandeur_unit"])
print("GHI moyen 1991-2020 :", round(sum(valeurs) / len(valeurs), 2), page["grandeur_unit"])
# GHI moyen 1991-2020 : 4.7 kWh/m²/jour
```

Sans la boucle, la réponse par défaut s'arrête au 26 septembre 1993
(1000 jours sur 10 958) et la moyenne vaut 4,73 au lieu de 4,70
kWh/m²/jour.

### JavaScript (navigateur ou Node)

```javascript
const API = "http://127.0.0.1:8000";
const h = { Authorization: `Bearer ${CLE}` };

const cat = await (await fetch(
  `${API}/v1/series?localite=civ_dep_korhogo&grandeur=ghi&source=nasa_power&granularite=mensuel`,
  { headers: h })).json();
const serie = await (await fetch(`${API}/v1/series/${cat.items[0].code}`, { headers: h })).json();
console.log(serie.source_label, serie.grandeur_unit, serie.pagination_mesures.total);
// ... kWh/m²/jour 420  (mois de 1991 à 2025, une seule page)
```

### CSV (Excel, pandas, R)

```bash
curl "$API/v1/series/nasa_power_ghi_journalier_civ_dep_abidjan?format=csv&from=2024-01-01&to=2024-12-31" \
  -H "Authorization: Bearer $CLE" -D - -o abidjan_ghi_2024.csv
# en-tête de réponse : X-Kuma-Mesures-Total: 366
```

Le CSV ne porte que des lignes de mesures : le total de la fenêtre
voyage dans l'en-tête HTTP `X-Kuma-Mesures-Total` (exposé aux clients
navigateur). Si ce total dépasse le nombre de lignes reçues, demandez
les pages suivantes avec `offset` (et `limit` jusqu'à 10 000).

## 5. Endpoints principaux

| Endpoint | Rôle | Auth |
|---|---|---|
| `GET /v1/health` | Santé de l'API + édition servie | non |
| `GET /v1/edition` | Édition publiée (date, révision, couverture) | non |
| `POST /v1/cles` | Émettre une clé | non |
| `GET /v1/series` | Catalogue paginé (`localite`, `grandeur`, `source`, `granularite`, `limit`, `offset`) | oui |
| `GET /v1/series/{code}` | Détail d'une série + mesures paginées (JSON/CSV) | oui |
| `GET /v1/localites` | Référentiel géographique (`pays_iso3`, `type_localite`, `parent_code`, recherche `q`) | oui |
| `GET /v1/localites/{code}` | Détail d'une localité | oui |
| `GET /v1/localites/resolution` | Localité et série de climatologie qui représentent un point (`lat`, `lon`) | oui |
| `GET /v1/grandeurs/incertitude_inter_source/{localite}` | Écart inter-sources + dégénérescence de pixel | oui |
| `GET /v1/grandeurs/<code>` | Grandeurs calculées et paramétrables (POA, productible, P50/P90...) | oui |
| `GET /v1/horaire/{localite}/{grandeur}` | Horaire stocké validé, sinon relais amont | oui |
| `GET /v1/calage` | Référentiels de calage satellite/sol publiés | oui |
| `GET /v1/etudes/capsule` | Ressource complète du moteur d'étude pour un point | oui |

Référence complète des paramètres et des réponses :
[`docs/architecture/06-api-reference-publique.md`](../architecture/06-api-reference-publique.md).

## 6. Le passeport d'une mesure

Chaque mesure d'une série brute porte :

- `valeur` - la valeur numérique,
- `annee`/`mois` (mensuel) ou `instant_mesure` (journalier) - le repère
  temporel,
- `niveau_effectif` - le niveau de confiance (A terrain / B modélisé / C...),
- `statut` - le statut éditorial (`brut`, `valide_auto`, `publie`...).

Une grandeur calculée (source `kuma_calculs` : HEP, productible
théorique, fraction diffuse, indice de clarté...) porte à la place
`periode_type` (`mensuel`, `annuel` ou `statique`), `annee_debut`,
`annee_fin`, `mois` et `version_formule`.

Au niveau de la série : `source_label`, `source_url`, `grandeur_unit`,
`granularite`, `methode_collecte`, `periode_debut`/`periode_fin`, et un
champ `notes_fr` qui documente confiance, résolution et caveats (par
exemple la mise en garde sur le saut de 2021 des séries ERA5).

## 7. Format d'erreur

Les erreurs de l'API suivent la même enveloppe :

```json
{"erreur": {"code": "AUTH_CLE_INVALIDE", "message": "...", "details": {}}}
```

Codes stables (un code publié ne change jamais de sens) : `AUTH_*`,
`VALIDATION_*`, `RESSOURCE_*`, `CLES_*`, etc. Un paramètre absent ou
hors de son domaine (type, bornes) répond
`422 VALIDATION_VALEUR_INVALIDE`, avec le détail dans
`details.erreurs`. Exception : une route inexistante répond hors
enveloppe (`404 {"detail": "Not Found"}`). Détail dans la référence.

## 8. Limites et bon usage

- Quota journalier par clé (défaut 5000 requêtes/jour).
- Le détail d'une série est paginé : lisez `pagination_mesures.total`
  (JSON) ou `X-Kuma-Mesures-Total` (CSV) avant tout calcul sur la
  série entière.
- Les données sont **publiques** : la clé sert à vous identifier et à
  réguler l'usage, pas à restreindre l'accès.
- L'édition servie est datée (`GET /v1/edition`) : citez la date et la
  révision pour la reproductibilité.

## 9. Citer les données

Cette instance se cite d'après son fichier `CITATION.cff` (Kuma Data
Core, Côte d'Ivoire, dérivé du moteur Kuma Data Core). Le moteur Kuma
Data Core est archivé avec un DOI :
**[10.5281/zenodo.21117158](https://doi.org/10.5281/zenodo.21117158)**.
Indiquez l'`edition_id` et la `date_publication` renvoyés par
`GET /v1/edition` pour préciser l'état des données consultées.
