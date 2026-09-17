## Contexte

<!-- Quoi et pourquoi : le problème résolu ou la fonctionnalité ajoutée. -->

## Changements

<!-- Liste des changements principaux. -->

## Vérifications

- [ ] J'ai lu et j'accepte le [CLA](../CLA.md) (obligatoire à la première contribution)
- [ ] Tests unitaires passent (`uv run pytest -m unit`)
- [ ] Tests d'intégration hors regression passent (`uv run pytest -m "integration and not regression"`)
- [ ] Lint (`uv run ruff check`) et format (`uv run ruff format --check`)
- [ ] Typecheck (`uv run mypy src`)
- [ ] Migration Alembic vérifiée si le schéma change (`uv run alembic upgrade head` puis `uv run alembic check`)
- [ ] Documentation à jour si nécessaire

## Notes de relecture

<!-- Points d'attention pour le relecteur : choix de conception, limites connues,
     déviations volontaires. -->
