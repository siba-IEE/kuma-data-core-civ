"""Manifeste du filtre de publication (ADR-0003, D5 / WP0).

Classification exhaustive des tables du schéma de référence pour la
construction d'une édition publique. Trois catégories disjointes :

1. ``TABLES_PUBLIEES`` : dumpées telles quelles.
2. ``TABLES_ASSAINIES`` : dumpées après neutralisation de colonnes
   sensibles (règles dans ``ASSAINISSEMENTS``).
3. ``TABLES_EXCLUES`` : jamais dumpées.

Invariant (garanti par ``tests/unit/publication/``) : toute table de
``Base.metadata`` appartient à exactement une catégorie. Une table
ajoutée au schéma sans classement explicite ici casse la CI : rien ne
peut fuiter silencieusement.

L'assainissement s'applique en LOCAL, sur la base d'édition
intermédiaire, avant ``pg_dump`` (ADR-0003, D5). Le VPS ne reçoit
jamais rien à nettoyer. Les expressions de ``ASSAINISSEMENTS`` sont
des membres droits d'``UPDATE ... SET <colonne> = <expression>``
exécutés sur cette base intermédiaire.

Objets hors tables ORM :

- ``FONCTION_AUDIT`` et les triggers ``PREFIXE_TRIGGERS_AUDIT*`` sont
  supprimés de la base d'édition avant dump (l'écriture n'a pas lieu
  sur le VPS, et ``audit_log`` est exclue).
- ``TABLES_HORS_ORM_PUBLIEES`` : tables présentes en base mais absentes
  de ``Base.metadata`` (Alembic), publiées pour traçabilité.

Statuts éditoriaux : aucun filtrage par ligne au dump (ADR-0003, D6).
Le versioning non destructif fait partie de la donnée publiée ; c'est
l'API qui sert le courant ``statut <> 'deprecie'``.
"""

from __future__ import annotations

# Tables dumpées telles quelles.
TABLES_PUBLIEES: frozenset[str] = frozenset(
    {
        "unites",
        "localites",
        "sources",
        "grandeurs_referentiel",
        "grandeurs_metier",
        "mesures_ressource",
        "mesures_ressource_mensuelles",
        "mesures_ressource_horaires",
        "referentiels_calage",
        "calage_couverture",
    }
)

# Tables dumpées après assainissement (règles ci-dessous).
TABLES_ASSAINIES: frozenset[str] = frozenset({"contributeurs", "series_metadonnees"})

# Tables jamais dumpées.
TABLES_EXCLUES: frozenset[str] = frozenset({"audit_log"})

# Règles d'assainissement : table -> {colonne: expression SQL}.
# Contrainte : une colonne NOT NULL ne peut pas recevoir NULL ; une
# colonne UNIQUE doit recevoir une valeur distincte par ligne (d'où
# la dérivation depuis ``id`` pour ``email_principal``, qui est
# NOT NULL UNIQUE).
ASSAINISSEMENTS: dict[str, dict[str, str]] = {
    "contributeurs": {
        "email_principal": "'contributeur-' || id::text || '@retire.invalid'",
        "biographie": "NULL",
        "notes_internes": "NULL",
    },
    # Le journal de chantier d'une série (références internes : étapes,
    # cohortes, dettes D-n, PR du dépôt privé) ne sort pas de la base de
    # référence. Le passeport public vit dans note_publique (migration
    # 099), servi par l'API sous l'alias notes_fr.
    "series_metadonnees": {
        "commentaire_editorial": "NULL",
    },
}

# Fonction et triggers d'audit supprimés de la base d'édition avant dump.
FONCTION_AUDIT: str = "kuma_log_audit"
PREFIXE_TRIGGERS_AUDIT: str = "trg_audit_"

# Tables hors ORM (absentes de Base.metadata) publiées pour traçabilité.
TABLES_HORS_ORM_PUBLIEES: frozenset[str] = frozenset({"alembic_version"})


def tables_classees() -> frozenset[str]:
    """Union des trois catégories : le périmètre couvert par le manifeste."""
    return TABLES_PUBLIEES | TABLES_ASSAINIES | TABLES_EXCLUES


def tables_dumpees() -> frozenset[str]:
    """Tables ORM effectivement présentes dans le dump d'une édition."""
    return TABLES_PUBLIEES | TABLES_ASSAINIES
