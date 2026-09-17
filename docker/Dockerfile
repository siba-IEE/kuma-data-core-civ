# Image de production de l'API Kuma Data Core (ADR-0003, WP8).
#
# Multi-stage : build des dépendances avec uv, puis image d'exécution
# mince. L'API tourne en utilisateur non-root, sans les migrations ni
# les outils de dev (l'image ne sert QUE l'API en lecture d'édition).

FROM python:3.12-slim AS build

# uv : installateur de dépendances (aligne sur uv.lock versionné).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Couche de dépendances (cache tant que le lock ne bouge pas).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Code applicatif (README requis par le backend de build hatchling).
COPY README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

# Utilisateur non-root : l'API ne doit jamais tourner en root.
RUN useradd --create-home --uid 10001 kuma

WORKDIR /app
COPY --from=build --chown=kuma:kuma /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER kuma
EXPOSE 8000

# Un seul worker par défaut (la charge attendue est modeste ; monter en
# workers si la supervision le justifie). --proxy-headers laisse uvicorn
# consommer X-Forwarded-* posés par Caddy ; --forwarded-allow-ips limite
# la confiance au réseau Docker interne.
CMD ["uvicorn", "kuma_data_core.api.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
