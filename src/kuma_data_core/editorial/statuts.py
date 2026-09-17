"""Machine d'état du statut éditorial Kuma.

Périmètre tables du périmètre statut : ``mesures_ressource``
et ``grandeurs_metier``. Pour les référentiels stables
(``contributeurs``, ``unites``, ``localites``, ``sources``,
``grandeurs_referentiel``, ``series_metadonnees``), le retrait est géré
par ``actif``/``desactive_le`` (soft delete), pas par transition de
statut.

5 valeurs autorisées (`frozenset` miroir de la CHECK constraint SQL) :

- ``brut`` : donnée importée non encore validée
- ``valide_auto`` : contrôle qualité automatique passé
- ``valide_humain`` : validation éditoriale humaine
- ``publie`` : publié publiquement
- ``deprecie`` : retiré du circuit éditorial (état terminal)

Matrice de transitions :

| État courant       | Transitions sortantes autorisées            |
|--------------------|---------------------------------------------|
| ``brut``           | ``valide_auto``, ``valide_humain``, ``deprecie`` |
| ``valide_auto``    | ``valide_humain``, ``deprecie``                  |
| ``valide_humain``  | ``publie``, ``deprecie``                         |
| ``publie``         | ``deprecie``                                     |
| ``deprecie``       | aucune (état terminal)                           |

Trois principes structurants :

1. **Pas de régression** dans le workflow (aucune transition vers un
   état antérieur).
2. ``deprecie`` est **terminal** (résurrection via rotation versionnée
   d'une nouvelle ligne avec statut initial, pas via transition).
3. **Sauts autorisés** dans le sens du workflow (``brut → valide_humain``,
   ``brut → deprecie``).

La fonction ``transition_statut`` vérifie la matrice et lève
``TransitionEditorialeRefusee`` si la transition n'est pas autorisée.
La mise à jour effective des colonnes ``statut``, ``modifie_le``,
``modifie_par`` sur la ligne est de la responsabilité du caller (ce
module reste indépendant de SQLAlchemy pour rester testable
unitairement sans DB).
"""

from __future__ import annotations

from kuma_data_core.exceptions import TransitionEditorialeRefusee

STATUTS_EDITORIAUX_AUTORISES: frozenset[str] = frozenset(
    {
        "brut",
        "valide_auto",
        "valide_humain",
        "publie",
        "deprecie",
    }
)
"""Constante miroir de la CHECK constraint SQL ``ck_<table>_statut_valide``.

Pattern hérité des constantes ``FAMILLES_AUTORISEES`` /
``STRATEGIES_CALCUL_AUTORISEES``. Cohérence inter-tables garantie :
les CHECK de ``mesures_ressource`` et ``grandeurs_metier`` doivent
rester strictement identiques sur leur liste de valeurs.
"""


TRANSITIONS_AUTORISEES: frozenset[tuple[str, str]] = frozenset(
    {
        # Depuis ``brut``
        ("brut", "valide_auto"),
        ("brut", "valide_humain"),
        ("brut", "deprecie"),
        # Depuis ``valide_auto``
        ("valide_auto", "valide_humain"),
        ("valide_auto", "deprecie"),
        # Depuis ``valide_humain``
        ("valide_humain", "publie"),
        ("valide_humain", "deprecie"),
        # Depuis ``publie``
        ("publie", "deprecie"),
        # Depuis ``deprecie`` : aucune transition (terminal)
    }
)
"""Matrice exhaustive des transitions autorisées.

8 transitions au total. Toute paire ``(statut_courant, nouveau_statut)``
absente de cet ensemble est refusée par ``transition_statut``.
"""


def transition_autorisee(statut_courant: str, nouveau_statut: str) -> bool:
    """Indique si la transition ``statut_courant -> nouveau_statut`` est autorisée.

    Helper sans effet de bord pour les cas où le caller veut tester sans
    déclencher l'exception (ex. construction d'un dropdown UI listant les
    transitions disponibles).
    """
    return (statut_courant, nouveau_statut) in TRANSITIONS_AUTORISEES


def transition_statut(statut_courant: str, nouveau_statut: str) -> None:
    """Vérifie une transition de statut éditorial contre la matrice.

    Args:
        statut_courant : valeur actuelle de la colonne ``statut`` sur la
            ligne ciblée.
        nouveau_statut : valeur cible souhaitée.

    Raises:
        TransitionEditorialeRefusee : si la paire ``(statut_courant,
            nouveau_statut)`` ne figure pas dans
            ``TRANSITIONS_AUTORISEES``. Inclut aussi les cas dégénérés :
            statuts non reconnus, transition vers le même statut.

    Side-effects :
        Aucun. Ce module reste indépendant de SQLAlchemy. La mise à jour
        effective des colonnes ``statut``, ``modifie_le``, ``modifie_par``
        sur la ligne est faite par le caller dans la même transaction,
        après vérification.

    Notes :
        - Transitions vers le même statut (``brut → brut``) sont refusées
          car non listées dans la matrice. Pas de no-op silencieux.
        - Les valeurs hors ``STATUTS_EDITORIAUX_AUTORISES`` sont refusées
          (toujours non listées dans la matrice) ; il n'y a pas
          d'exception dédiée - ``TransitionEditorialeRefusee`` couvre
          tous les cas de refus.
    """
    if not transition_autorisee(statut_courant, nouveau_statut):
        raise TransitionEditorialeRefusee(
            statut_courant=statut_courant, nouveau_statut=nouveau_statut
        )
