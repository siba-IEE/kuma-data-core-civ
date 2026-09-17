# Démarrage rapide - API publique Kuma Data Core

Interroger les données climatiques et solaires de la Guinée en quelques
minutes. L'API sert des **séries situées** : chaque valeur arrive avec sa
source, son unité, son niveau de confiance et ses caveats - jamais un
nombre nu.

- **Base URL** : `https://api.kumascience.com`
- **Format** : JSON par défaut, CSV en option (`?format=csv`) sur les séries
  et grandeurs.
- **Authentification** : `Authorization: Bearer <cle>` (clé gratuite, voir
  ci-dessous). Seuls `GET /v1/health`, `GET /v1/edition` et `POST /v1/cles`
  sont accessibles sans clé.

## 1. Vérifier que l'API répond (sans clé)

```bash
curl https://api.kumascience.com/v1/health
# {"statut":"operationnel","version":"0.1.0","environnement":"prod","edition":"edition_20260702"}

curl https://api.kumascience.com/v1/edition
# édition servie, date de publication, révision source, couverture
```

## 2. Obtenir une clé (une seule fois, gratuite)

```bash
curl -X POST https://api.kumascience.com/v1/cles \
  -H "Content-Type: application/json" \
  -d '{"email":"vous@exemple.org","usage_prevu":"outil de dimensionnement"}'
# {"cle":"kuma_...","prefixe":"kuma_xxxxxxxx","quota_journalier":5000}
```

La clé n'est **montrée qu'une seule fois** : conservez-la. Le `prefixe` est
son identifiant public (support, révocation). Quota par défaut :
5000 requêtes/jour.

## 3. Première requête authentifiée

```bash
CLE="kuma_..."   # votre clé

# Le catalogue des séries d'une localité
curl "https://api.kumascience.com/v1/series?localite=gin_boffa&grandeur=ghi" \
  -H "Authorization: Bearer $CLE"

# Le détail d'une série + ses mesures
curl "https://api.kumascience.com/v1/series/gin_boffa_ghi_era5_land_2001_2020" \
  -H "Authorization: Bearer $CLE"
```

## 4. Exemples par langage

### Python

```python
import requests

API = "https://api.kumascience.com"
CLE = "kuma_..."
h = {"Authorization": f"Bearer {CLE}"}

# Découvrir les séries GHI de Boffa
cat = requests.get(f"{API}/v1/series",
                   params={"localite": "gin_boffa", "grandeur": "ghi"},
                   headers=h).json()
code = cat["items"][0]["code"]

# Récupérer la série + ses mesures (chaque mesure porte son passeport)
serie = requests.get(f"{API}/v1/series/{code}", headers=h).json()
print("Source :", serie["source_label"], "| unité :", serie["grandeur_unit"])
valeurs = [m["valeur"] for m in serie["mesures"]]
print("GHI moyen :", round(sum(valeurs) / len(valeurs), 2), serie["grandeur_unit"])
```

### JavaScript (navigateur ou Node)

```javascript
const API = "https://api.kumascience.com";
const h = { Authorization: `Bearer ${CLE}` };

const cat = await (await fetch(`${API}/v1/series?localite=gin_boffa&grandeur=ghi`, { headers: h })).json();
const serie = await (await fetch(`${API}/v1/series/${cat.items[0].code}`, { headers: h })).json();
console.log(serie.source_label, serie.grandeur_unit);
```

### CSV (Excel, pandas, R)

```bash
curl "https://api.kumascience.com/v1/series/gin_boffa_ghi_era5_land_2001_2020?format=csv" \
  -H "Authorization: Bearer $CLE" -o boffa_ghi.csv
```

## 5. Endpoints principaux

| Endpoint | Rôle | Auth |
|---|---|---|
| `GET /v1/health` | Santé de l'API + édition servie | non |
| `GET /v1/edition` | Édition publiée (date, révision, couverture) | non |
| `POST /v1/cles` | Émettre une clé | non |
| `GET /v1/series` | Catalogue paginé (`localite`, `grandeur`, `source`, `limit`, `offset`) | oui |
| `GET /v1/series/{code}` | Détail d'une série + mesures (JSON/CSV) | oui |
| `GET /v1/localites` | Référentiel géographique | oui |
| `GET /v1/localites/{code}` | Détail d'une localité | oui |
| `GET /v1/grandeurs/incertitude_inter_source/{localite}` | Écart inter-sources + dégénérescence de pixel | oui |
| `GET /v1/grandeurs/<code>` | Grandeurs calculées et paramétrables (POA, productible...) | oui |
| `GET /v1/horaire/{localite}/{grandeur}` | Données horaires stockées | oui |

Référence complète des paramètres et des réponses :
[`docs/architecture/06-api-reference-publique.md`](../architecture/06-api-reference-publique.md).

## 6. Le passeport d'une mesure

Chaque mesure d'une série brute porte :

- `valeur` - la valeur numérique,
- `annee`/`mois` (mensuel) ou `instant_mesure` (journalier) - le repère temporel,
- `niveau_effectif` - le niveau de confiance (A terrain / B modélisé / C...),
- `statut` - le statut éditorial (`brut`, `valide_auto`, `publie`...).

Au niveau de la série : `source_label`, `source_url`, `grandeur_unit`,
`methode_collecte`, `periode_debut`/`periode_fin`, et un champ `notes_fr`
qui documente confiance, résolution et caveats.

## 7. Format d'erreur

Toutes les erreurs suivent la même enveloppe :

```json
{"erreur": {"code": "AUTH_CLE_INVALIDE", "message": "...", "details": {}}}
```

Codes stables (un code publié ne change jamais de sens) : `AUTH_*`,
`VALIDATION_*`, `RESSOURCE_*`, `CLES_*`, etc. Détail dans la référence.

## 8. Limites et bon usage

- Quota journalier par clé (défaut 5000 requêtes/jour).
- Les données sont **publiques** : la clé sert à vous identifier et à
  réguler l'usage, pas à restreindre l'accès.
- L'édition servie est datée (`GET /v1/edition`) : citez la date et la
  révision pour la reproductibilité.

## 9. Citer les données

Kuma Data Core est archivé avec un DOI :
**[10.5281/zenodo.21117158](https://doi.org/10.5281/zenodo.21117158)**.
Indiquez l'`edition_id` et la `date_publication` renvoyés par
`GET /v1/edition` pour préciser l'état des données consultées.
