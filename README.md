# Kuma Data Core (Côte d'Ivoire)

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)

Instance dédiée à la Côte d'Ivoire du moteur Kuma Data Core. Moteur de données à
confiance tracée : chaque valeur porte sa source, sa méthode, son niveau de
confiance (A/B/C), ses dates de validité et son statut éditorial. Versionnement
temporel non destructif, audit applicatif par triggers. Base PostgreSQL, API
FastAPI. Domaine : la ressource solaire en Côte d'Ivoire.

Le code moteur est générique : le pays est un axe de classification, pas une base
séparée. Cette instance repart d'un socle propre, sans donnée d'une autre
instance.

## État

Socle en place. La donnée nationale se construit par lots.

- Schéma : baseline unique regroupant le schéma complet du moteur (tables, vues,
  contraintes, index, fonctions PL/pgSQL, triggers d'audit et de validation
  hiérarchique, extension `btree_gist`), sans donnée.
- Référentiels génériques : unités, catalogue des grandeurs, sources amont (NASA
  POWER, ERA5 et ERA5-Land, SARAH-3 via PVGIS, CAMS, ESMAP/WAPP, normes IEC et
  WMO).
- Localités : le pays `civ` (ISO 3166-1 alpha-3 : CIV) et les 14 districts (12
  districts et 2 districts autonomes, Abidjan et Yamoussoukro), niveau
  `region_administrative`, nomenclature ISO 3166-2:CI.

`alembic upgrade head` n'exige aucun accès réseau : aucune migration d'ingestion.

### À faire

- Localités : 31 régions (`prefecture`) puis 108 départements, avec coordonnées,
  population et sourçage (Wikidata, HDX/COD-AB, INS Côte d'Ivoire).
- Ingestion de la donnée solaire (séries et mesures brutes par source), puis
  grandeurs métier calculées et contrôle qualité.
- Adaptation de la documentation `docs/` au contexte ivoirien.

## Démarrage rapide

Pré-requis : Python 3.12, [uv](https://docs.astral.sh/uv/), Docker.

```bash
git clone https://github.com/siba-IEE/kuma-data-core-civ.git
cd kuma-data-core-civ
uv sync --group dev
cp docker/.env.example .env      # renseigner les mots de passe (champs changeme_*)
docker compose -f docker/docker-compose.yml --env-file .env up -d
uv run alembic upgrade head
uv run uvicorn kuma_data_core.api.main:app --reload
```

L'API écoute sur `http://127.0.0.1:8000` (`/docs` en dev).

## Stack

Python 3.12, PostgreSQL 16, FastAPI, SQLAlchemy 2.x, Alembic, Redis, Docker
Compose, uv, ruff, mypy, pytest. CI GitHub Actions (lint, types, tests unitaires
et d'intégration, contrôle de cohérence Alembic).

## Structure

| Chemin | Rôle |
|---|---|
| `src/kuma_data_core/db/` | Modèles SQLAlchemy, sessions, seeds de référentiels |
| `src/kuma_data_core/api/` | Application FastAPI (auth Bearer) |
| `src/kuma_data_core/services/grandeurs/` | Modules de calcul par grandeur |
| `src/kuma_data_core/ingestion/` | Ingestion des sources externes |
| `src/kuma_data_core/editorial/` | Statuts éditoriaux, confiance A/B/C, versionnement |
| `migrations/versions/` | Migrations Alembic (baseline, référentiels, localités) |
| `migrations/sql/` | SQL de la baseline schéma et des référentiels |
| `tests/` | Tests unitaires et d'intégration |
| `docs/` | Architecture, conventions, méthodologie |

## Conventions

Le SQL et les identifiants métier sont en français. Toute évolution du schéma
passe par une migration Alembic. Détails dans
[docs/conventions/](docs/conventions/) et [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

Distribué sous licence AGPL-3.0-or-later (voir [LICENSE](LICENSE)). Exploité comme
service en réseau, l'AGPL impose de publier les modifications sous la même
licence.

Projet développé et soutenu par Kuma Science
([kumascience.com](https://kumascience.com)).

## Contact

Siba Kalivogui, Kuma Science.
