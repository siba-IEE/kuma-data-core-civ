"""Résolution de la table de mesures cible pour une série.

Fonction utilitaire pure (sans I/O) qui résout la table-cible des mesures
d'une série à partir de ses métadonnées. Routage **source-first puis
granularité** :

- Les séries ``kuma_calculs`` vont dans ``grandeurs_metier`` (routées par
  source ; ``granularite`` NULL pour ces séries).
- Les autres séries sont routées par leur ``granularite``
  (``journalier`` / ``mensuel`` / ``horaire``), discriminant posé en
  migration 052 sur ``series_metadonnees``.

Auparavant le routage des séries ``nasa_power`` reposait sur
``periode_debut.year`` (bascule 2021). Cette heuristique ne
distinguait pas une série horaire d'une série journalière de même source
et même année de début ; elle est remplacée par la granularité explicite.

Fail-fast (``ValueError``) sur combinaison (source, granularité) non
résolue : force la mise à jour explicite quand un cas non prévu apparaît.
"""

from __future__ import annotations

from enum import StrEnum


class TableMesures(StrEnum):
    """Tables-cibles des mesures pour les endpoints `/api/v1/series`."""

    JOURNALIER = "mesures_ressource"
    MENSUEL_RESSOURCE = "mesures_ressource_mensuelles"
    HORAIRE = "mesures_ressource_horaires"
    GRANDEURS_METIER = "grandeurs_metier"


def resolve_table_from_series_metadata(
    source_code: str,
    granularite: str | None,
) -> TableMesures:
    """Résout la table-cible des mesures d'une série.

    Fonction pure (sans I/O). Routage source-first puis granularité :

    - ``source_code == 'kuma_calculs'`` -> ``grandeurs_metier`` (quelle
      que soit la granularité, NULL pour ces séries).
    - sinon, routage par ``granularite`` (``journalier`` / ``mensuel`` /
      ``horaire``).

    Args:
        source_code : valeur de ``sources.code`` de la série (lookup
            préétabli par le caller via JOIN ``series_metadonnees`` /
            ``sources``).
        granularite : valeur de ``series_metadonnees.granularite``. ``NULL``
            uniquement pour les séries ``kuma_calculs`` (traitées avant
            que la granularité ne soit consultée).

    Returns:
        :class:`TableMesures` indiquant la table SQL où trouver les
        mesures de la série.

    Raises:
        ValueError : si la combinaison (source, granularité) n'est pas
            résolue. Une série non-``kuma_calculs`` doit porter une
            granularité valide ; un ``NULL`` ou une valeur inconnue sur
            une telle série déclenche le fail-fast (incohérence de
            métadonnée détectée, pas silencieuse).
    """
    if source_code == "kuma_calculs":
        return TableMesures.GRANDEURS_METIER
    if granularite == "horaire":
        return TableMesures.HORAIRE
    if granularite == "mensuel":
        return TableMesures.MENSUEL_RESSOURCE
    if granularite == "journalier":
        return TableMesures.JOURNALIER
    raise ValueError(
        f"Routage non resolu pour resolve_table_from_series_metadata : "
        f"source={source_code!r}, granularite={granularite!r}. Une serie "
        f"non-kuma_calculs doit porter une granularite "
        f"'journalier'/'mensuel'/'horaire' (cf. migration 052, dette D-36)."
    )
