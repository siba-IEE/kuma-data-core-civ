"""Tests de l'extraction d'IP cliente derrière proxy (ADR-0003 D2, WP8).

La limite d'émission de clés par IP ne vaut que si l'IP est fiable.
Derrière un reverse proxy, ``request.client.host`` est l'IP du proxy ;
la vraie IP vit dans ``X-Forwarded-For``. Mais cet en-tête est
falsifiable par le client : on ne le lit que si un proxy de confiance
est déclaré, et on prend la dernière entrée (celle ajoutée par notre
proxy, non falsifiable).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from kuma_data_core.api.v1.cles import _adresse_ip
from kuma_data_core.core.config import get_settings

pytestmark = pytest.mark.unit


def _fausse_requete(ip_directe: str, xff: str | None) -> SimpleNamespace:
    entetes = {"x-forwarded-for": xff} if xff is not None else {}
    return SimpleNamespace(client=SimpleNamespace(host=ip_directe), headers=entetes)


def test_sans_proxy_ignore_x_forwarded_for(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exposition directe : l'en-tête client forgé ne doit pas être cru."""
    monkeypatch.setattr(get_settings(), "derriere_proxy_confiance", False)
    requete = _fausse_requete("203.0.113.7", xff="1.2.3.4")
    assert _adresse_ip(requete) == "203.0.113.7"  # type: ignore[arg-type]


def test_derriere_proxy_prend_la_derniere_entree(monkeypatch: pytest.MonkeyPatch) -> None:
    """La dernière entrée est celle ajoutée par notre proxy (non falsifiable).

    Un client qui préfixe une IP fictive (``1.2.3.4``) ne peut pas
    empêcher le proxy d'ajouter la vraie IP après : c'est elle qu'on lit.
    """
    monkeypatch.setattr(get_settings(), "derriere_proxy_confiance", True)
    requete = _fausse_requete("10.0.0.1", xff="1.2.3.4, 198.51.100.23")
    assert _adresse_ip(requete) == "198.51.100.23"  # type: ignore[arg-type]


def test_derriere_proxy_sans_entete_retombe_sur_ip_directe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "derriere_proxy_confiance", True)
    requete = _fausse_requete("10.0.0.1", xff=None)
    assert _adresse_ip(requete) == "10.0.0.1"  # type: ignore[arg-type]
