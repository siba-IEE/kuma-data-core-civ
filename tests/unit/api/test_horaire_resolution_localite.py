"""Tests unitaires de la resolution de localite de ``/v1/horaire`` (ADR-0029).

``_resoudre_localite`` ne code plus de prefixe pays : le code court
(sans prefixe) est resolu contre les pays presents au referentiel.
La session SQLAlchemy est simulee : premier ``execute`` = recherche du
code complet (``.first()``), second = recherche des alias (``.all()``).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from kuma_data_core.api.codes_erreur import CodeErreur
from kuma_data_core.api.erreurs import ExceptionKuma
from kuma_data_core.api.v1.horaire import _resoudre_localite

pytestmark = pytest.mark.unit


def _session(code_complet_existe: bool, alias: list[str]) -> MagicMock:
    resultat_complet = MagicMock()
    resultat_complet.first.return_value = (1,) if code_complet_existe else None
    resultat_alias = MagicMock()
    resultat_alias.all.return_value = [MagicMock(code=code) for code in alias]
    session = MagicMock()
    session.execute.side_effect = [resultat_complet, resultat_alias]
    return session


def test_code_complet_resolu_tel_quel_sans_chercher_d_alias() -> None:
    session = _session(code_complet_existe=True, alias=[])
    assert _resoudre_localite(session, "civ_dep_korhogo") == "civ_dep_korhogo"
    assert session.execute.call_count == 1


@pytest.mark.parametrize(
    ("court", "complet"),
    [("kankan", "gin_kankan"), ("abidjan", "civ_abidjan"), ("dakar", "sen_dakar")],
)
def test_code_court_resolu_par_le_prefixe_d_un_pays_du_referentiel(
    court: str, complet: str
) -> None:
    session = _session(code_complet_existe=False, alias=[complet])
    assert _resoudre_localite(session, court) == complet
    # Le prefixe vient de la table (jointure sur les pays), pas d'une constante.
    sql_alias = str(session.execute.call_args_list[1].args[0])
    assert "type_localite = 'pays'" in sql_alias
    assert session.execute.call_args_list[1].args[1] == {"code": court}


def test_code_court_ambigu_entre_deux_pays_renvoie_404_avec_candidats() -> None:
    session = _session(code_complet_existe=False, alias=["civ_bouna", "gha_bouna"])
    with pytest.raises(ExceptionKuma) as exc:
        _resoudre_localite(session, "bouna")
    assert exc.value.statut_http == 404
    assert exc.value.code == CodeErreur.RESSOURCE_LOCALITE_INCONNUE
    assert exc.value.details == {"candidats": ["civ_bouna", "gha_bouna"]}


def test_localite_inconnue_renvoie_404() -> None:
    session = _session(code_complet_existe=False, alias=[])
    with pytest.raises(ExceptionKuma) as exc:
        _resoudre_localite(session, "inexistante")
    assert exc.value.statut_http == 404
    assert exc.value.code == CodeErreur.RESSOURCE_LOCALITE_INCONNUE
    assert exc.value.details is None
