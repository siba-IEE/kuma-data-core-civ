"""Modèles SQLAlchemy de Kuma Data Core.

Importer ce module suffit à enregistrer tous les modèles dans
``Base.metadata``. C'est ce que fait ``migrations/env.py`` pour
qu'Alembic dispose de la cible complète des comparaisons.
"""

from kuma_data_core.db.models.audit_log import AuditLog
from kuma_data_core.db.models.calage_couverture import CalageCouverture
from kuma_data_core.db.models.contributeurs import Contributeur
from kuma_data_core.db.models.grandeurs_metier import GrandeurMetier
from kuma_data_core.db.models.grandeurs_referentiel import GrandeurReferentiel
from kuma_data_core.db.models.localites import Localite
from kuma_data_core.db.models.mesures_ressource import MesureRessource
from kuma_data_core.db.models.mesures_ressource_horaires import MesureRessourceHoraire
from kuma_data_core.db.models.mesures_ressource_mensuelles import MesureRessourceMensuelle
from kuma_data_core.db.models.referentiels_calage import ReferentielCalage
from kuma_data_core.db.models.series_metadonnees import SerieMetadonnees
from kuma_data_core.db.models.sources import Source
from kuma_data_core.db.models.unites import Unite

__all__ = [
    "AuditLog",
    "CalageCouverture",
    "Contributeur",
    "GrandeurMetier",
    "GrandeurReferentiel",
    "Localite",
    "MesureRessource",
    "MesureRessourceHoraire",
    "MesureRessourceMensuelle",
    "ReferentielCalage",
    "SerieMetadonnees",
    "Source",
    "Unite",
]
