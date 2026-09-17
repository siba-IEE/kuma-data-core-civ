# Confiance et statut éditorial

Chaque valeur du Core porte sa confiance et son statut éditorial comme des
propriétés de première classe. Ce document décrit les deux, à l'intention d'un
contributeur qui propose une donnée ou une méthode.

Périmètre : la confiance et le statut s'appliquent à `mesures_ressource` et
`grandeurs_metier`. Les référentiels (`sources`, `localites`, `unites`,
`grandeurs_referentiel`, `series_metadonnees`, `contributeurs`) n'ont pas de
statut ; leur retrait passe par un soft delete (`actif`, `desactive_le`).

## Confiance A/B/C

- **A** (haute) : donnée mesurée directement par un instrument de référence, ou
  calculée par une méthode reconnue à partir de mesures elles-mêmes A.
- **B** (moyenne) : donnée modélisée, interpolée ou extrapolée selon une
  méthodologie documentée, à partir d'une source de fiabilité haute ou moyenne.
- **C** (basse) : donnée estimée par expertise sans validation instrumentale, ou
  issue d'une source de fiabilité faible.

La confiance est dérivée par quatre règles, évaluées dans l'ordre ; la première
qui s'applique fixe la valeur :

| Ordre | Condition | Résultat |
|---|---|---|
| R1 | source de fiabilité `faible` | C |
| R2 | méthode de collecte `expertise_humaine` | C |
| R3 | méthode `mesure_directe` et source de fiabilité `haute` | A |
| R4 | tous les autres cas | B |

R4 est le cas par défaut : une donnée satellitaire ou de réanalyse (NASA POWER,
CAMS, ERA5) est en confiance B. Une décision éditoriale peut poser un override
sur une ligne, avec une justification obligatoire conservée dans le commentaire
éditorial.

**La confiance A est réservée aux données validées au sol.** Un fait exact tiré
d'une source satellitaire reste B, avec un caveat documenté, tant qu'il n'a pas
été confronté à une mesure terrain. La définition publiée est rappelée dans la
[référence d'API](../architecture/06-api-reference-publique.md).

## Statut éditorial

Cinq états, dans un sens unique :

`brut` puis `valide_auto` puis `valide_humain` puis `publie`, avec `deprecie`
comme état terminal atteignable depuis n'importe quel état.

| État courant | Transitions autorisées |
|---|---|
| `brut` | `valide_auto`, `valide_humain`, `deprecie` |
| `valide_auto` | `valide_humain`, `deprecie` |
| `valide_humain` | `publie`, `deprecie` |
| `publie` | `deprecie` |
| `deprecie` | aucune (terminal) |

Trois principes : pas de régression (aucun retour à un état antérieur) ; les
sauts vers l'avant sont permis (`brut` vers `valide_humain`) ; `deprecie` est
terminal, une valeur retirée ne ressuscite pas, une nouvelle version est créée à
sa place.

## Validité temporelle

Aucune mise à jour destructive. Une valeur corrigée ou ré-ingérée ne remplace
pas l'ancienne en place : une nouvelle ligne est créée, l'ancienne est bornée
par `valide_au`, et les lectures ne renvoient que la version courante. L'histoire
reste vérifiable.
