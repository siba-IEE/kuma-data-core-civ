"""Schémas Pydantic des endpoints `/api/v1/series`.

5 schémas + 1 union discriminée :

- :class:`SerieListee` : ligne du listing (`GET /api/v1/series`).
- :class:`SerieDetail` : détail d'une série (`GET /api/v1/series/{code}`)
  contenant un sous-objet ``mesures: list[MesureLue]``.
- :class:`MesureJournaliere` : mesure journalière (table
  ``mesures_ressource``), discriminée par ``type = 'journalier'``.
- :class:`MesureMensuelle` : mesure mensuelle (table
  ``mesures_ressource_mensuelles``), discriminée par ``type = 'mensuel'``.
- :class:`GrandeurMetierValeur` : valeur de grandeur calculée Kuma
  (table ``grandeurs_metier``), discriminée par ``type = 'grandeur_metier'``.
- :data:`MesureLue` : union discriminée `MesureJournaliere |
  MesureMensuelle | GrandeurMetierValeur`.

Pattern générique paramétré (1 schéma par catégorie, pas 1 schéma par
grandeur) - évite un schéma spécifique par série exposée.
Discrimination via champ littéral `type` (Pydantic discriminated union).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

# === Schémas mesures (union discriminée MesureLue) ========================


class MesureJournaliere(BaseModel):
    """Mesure journalière d'une série brute (table ``mesures_ressource``)."""

    type: Literal["journalier"] = "journalier"
    instant_mesure: date
    valeur: float
    niveau_confiance_derive: str = Field(min_length=1, max_length=1)
    niveau_confiance_override: str | None = Field(default=None, min_length=1, max_length=1)
    niveau_effectif: str = Field(min_length=1, max_length=1)
    statut: str


class MesureMensuelle(BaseModel):
    """Mesure mensuelle d'une série brute (table ``mesures_ressource_mensuelles``)."""

    type: Literal["mensuel"] = "mensuel"
    annee: int = Field(ge=1991, le=2099)
    mois: int = Field(ge=1, le=12)
    valeur: float
    niveau_confiance_derive: str = Field(min_length=1, max_length=1)
    niveau_confiance_override: str | None = Field(default=None, min_length=1, max_length=1)
    niveau_effectif: str = Field(min_length=1, max_length=1)
    statut: str


class GrandeurMetierValeur(BaseModel):
    """Valeur d'une grandeur calculée Kuma (table ``grandeurs_metier``)."""

    type: Literal["grandeur_metier"] = "grandeur_metier"
    periode_type: Literal["annuel", "mensuel", "statique"]
    annee_debut: int = Field(ge=1991, le=2099)
    annee_fin: int = Field(ge=1991, le=2099)
    mois: int | None = Field(default=None, ge=1, le=12)
    version_formule: int = Field(ge=1)
    valeur: float
    niveau_confiance_derive: str = Field(min_length=1, max_length=1)
    niveau_confiance_override: str | None = Field(default=None, min_length=1, max_length=1)
    niveau_effectif: str = Field(min_length=1, max_length=1)
    statut: str


MesureLue = Annotated[
    MesureJournaliere | MesureMensuelle | GrandeurMetierValeur,
    Field(discriminator="type"),
]
"""Union discriminée des 3 catégories de mesures lues par les endpoints.

Le champ discriminant ``type`` (Literal) permet la désérialisation
type-safe côté client : la catégorie est inscrite explicitement dans
chaque mesure retournée.
"""


# === Schémas séries (listing + détail) ====================================


class SerieListee(BaseModel):
    """Ligne du listing `GET /api/v1/series` (contrat enrichi, ADR-0001).

    Vue catalogue dénormalisée couvrant identifiants, localité (code +
    nom + iso3), grandeur (code + label + unit), source (id + code +
    label + url), période, méthode, notes éditoriales, audit.

    Conventions de nommage (cf. ADR-0001 Data Core §nommage public) :

    - Les noms exposés côté API publique alignent avec le contrat
      attendu côté consommateur Kuma Science. Ils
      diffèrent volontairement des noms de colonnes DB internes :

      - ``source_label`` ← ``sources.titre``
      - ``grandeur_label`` ← ``grandeurs_referentiel.libelle``
      - ``grandeur_unit`` ← ``unites.symbole``
      - ``notes_fr`` ← ``series_metadonnees.note_publique`` (passeport public)
      - ``created_at`` ← ``series_metadonnees.cree_le``
      - ``updated_at`` ← ``series_metadonnees.modifie_le``

    - Les IDs (``id``, ``localite_id``, ``source_id``) sont exposés en
      ``int`` natif (BigInteger DB), pas en UUID. Côté consommateur
      Kuma Science : adapter le schéma Zod ``z.number().int().positive()``
      au lieu de ``z.uuid()``.
    """

    # === Identifiants ====================================================
    id: int
    code: str = Field(min_length=1, max_length=80)
    libelle: str

    # === Localité (dénormalisée) =========================================
    localite_id: int
    localite_code: str
    localite_nom: str
    localite_iso3: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

    # === Grandeur (dénormalisée) =========================================
    grandeur_code: str
    grandeur_label: str
    grandeur_unit: str

    # === Source (dénormalisée) ===========================================
    source_id: int
    source_code: str
    source_label: str
    source_url: str | None

    # === Période et méta éditoriales =====================================
    periode_debut: date
    periode_fin: date | None
    methode_collecte: str | None
    notes_fr: str | None

    # === Audit ===========================================================
    created_at: datetime
    updated_at: datetime

    # === Flag actif ======================================================
    actif: bool


class SerieListeePaginee(BaseModel):
    """Envelope paginée du listing `GET /api/v1/series` (ADR-0001).

    Structure standard de pagination offset-based (et non un tableau
    JSON nu). Le champ ``total`` permet aux consommateurs de connaître
    le nombre total de séries matchant les filtres sans avoir à boucler
    jusqu'à une page vide.

    Note : le seul consommateur connu (Kuma Science) adapte son schéma
    Zod ``dataCorePaginatedResponseSchema`` dans le cycle de
    synchronisation parallèle (cf. ADR-0012 Kuma Science).
    """

    items: list[SerieListee]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class SerieDetail(SerieListee):
    """Détail d'une série `GET /api/v1/series/{code}` avec mesures (ADR-0001).

    Étend :class:`SerieListee` (champs catalogue) avec :

    - ``unite_code`` : unité héritée via FK
      ``series_metadonnees.grandeur_code`` ->
      ``grandeurs_referentiel.unite_id`` -> ``unites.code``.
      Volontairement conservée en plus de ``grandeur_unit`` (le code
      symbolique stable est utile pour les consommateurs qui veulent
      faire un lookup sur la table ``unites``).
    - ``mesures`` : liste de mesures discriminées par catégorie. Le
      type concret dépend de la table-cible résolue par
      ``resolve_table_from_series_metadata`` (cf.
      ``api/services/serie_lecture.py``).
    """

    unite_code: str
    mesures: list[MesureLue]
