# Kuma Data Core — Côte d'Ivoire

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)

Ressource solaire et météo de la Côte d'Ivoire, en base PostgreSQL et servies par
une API FastAPI. 142 localités (31 régions, 111 départements), de 1991 à 2025
selon les sources, en mensuel et en journalier.

Chaque série porte sa source et sa méthode, chaque mesure son niveau de
confiance. Tout est aujourd'hui en confiance B (satellite ou réanalyse). La
confiance A viendra des mesures au sol.

## Données

| Grandeur | Sources |
|---|---|
| Rayonnement GHI, DNI, DHI | NASA POWER, CAMS Radiation ; GHI et DNI aussi SARAH-3 et ERA5 (PVGIS) |
| Température, humidité, vent | NASA POWER, ERA5 |
| Pluie | NASA POWER, ERA5, GPM IMERG, CHIRPS |
| Albédo | NASA POWER |
| Particules PM2.5, PM10 | CAMS EAC4 |

S'y ajoutent des grandeurs calculées : écarts entre sources, fraction diffuse,
heures équivalentes, productible, indice de clarté, humidex. Les choix et les
limites de chaque lot sont dans [docs/decisions/](docs/decisions/).

## Lancer

Python 3.12, [uv](https://docs.astral.sh/uv/) et Docker.

```bash
git clone https://github.com/siba-IEE/kuma-data-core-civ.git
cd kuma-data-core-civ
uv sync --group dev
cp docker/.env.example .env      # remplacer les mots de passe changeme_*
docker compose -f docker/docker-compose.yml --env-file .env up -d
uv run alembic upgrade head
uv run uvicorn kuma_data_core.api.main:app --reload
```

`alembic upgrade head` grave toutes les données à partir des CSV du dépôt, sans
réseau. C'est long : la CI met environ 55 minutes pour ce rejeu et les tests
d'intégration. Les scripts de `scripts/` régénèrent les CSV depuis les sources
(clé Copernicus pour ERA5 et CAMS).

L'API écoute sur `http://127.0.0.1:8000`, avec sa documentation sur `/docs`.

## Contribuer

Conventions : [docs/conventions/](docs/conventions/) et
[CONTRIBUTING.md](CONTRIBUTING.md). Suite prévue : [ROADMAP.md](ROADMAP.md).

## Licence

AGPL-3.0-or-later ([LICENSE](LICENSE)). Kuma Science
([kumascience.com](https://kumascience.com)), Siba Kalivogui.
