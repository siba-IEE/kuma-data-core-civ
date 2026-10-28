# ADR-0037 — Révision du mensuel CAMS 2021-2025, gravée par versionnement

Date : 2026-10-28. Statut : accepté — **gravé** (migration 0056).

## Contexte

Le mensuel CAMS Radiation (GHI, DNI, DHI) est gravé aux 142 localités :
2005-2020 par les migrations 0014, 0022, 0025 et 0027 (ADR-0011, ADR-0013,
ADR-0015), puis 2021-2025 par l'extension 0030 (ADR-0018, sondage du
2026-09-30).

En gravant le journalier CAMS (migration 0054, ADR-0035), on a constaté que CAMS
a **révisé 2021-2025** depuis ce sondage, sans changer de version de service
(v4.6) et sans documentation publique trouvée. 2005-2020 est inchangé. La
moyenne des jours servis s'écartait donc du mensuel gravé sur ces cinq années.
0054 a conservé les valeurs gravées et ajouté une mise en garde aux 426 séries
mensuelles. La décision de graver la révision était restée ouverte.

L'utilisateur a choisi de graver la révision. Les données restent brutes, en
confiance B.

## Décision

1. **Données** : le mensuel CAMS servi le 2026-10-28, téléchargé à nouveau pour
   les 142 localités sur 2005-2025 (`ingest_cams_radiation_mensuel.py
   --revision`, même requête que 0030).
   - L'ingesteur **exige** que 2005-2020 soit identique, valeur par valeur, aux
     valeurs gravées (seeds pilotes et lots nationaux). Sinon il s'arrête.
   - Il écrit les 60 mois 2021-2025 dans un CSV gzip par grandeur,
     `cams_<grandeur>_mensuel_revision_2026_10_28.csv.gz` (`LOT_REVISION_CAMS`,
     même contrat que l'extension). Le CSV d'extension, que 0030 relit, reste
     inchangé.
2. **Versionnement temporel non destructif**, premier usage des colonnes
   `valide_du` / `valide_au` prévues par le schéma (ADR-0001) :
   - pour chaque (série, année, mois) dont la valeur change, la ligne courante
     est **close** (`valide_au` = instant de la révision) ;
   - une nouvelle ligne courante la remplace (`valide_du` = même instant,
     statut `brut`, même confiance), marquée en commentaire éditorial :
     « Révision CAMS du 2026-10-28 (migration 0056, ADR-0037). » ;
   - rien n'est supprimé. L'API et les services lisent déjà les seules lignes
     courantes (`valide_au IS NULL`) ;
   - l'instant est lu une fois par `clock_timestamp()` : lors d'un rejeu
     intégral, toutes les migrations tournent dans une seule transaction, et
     `now()` serait égal au `valide_du` des lignes insérées par 0030.
3. **Grandeurs dérivées du mensuel CAMS**, recalculées sur 2021-2025 par les
   formules de leurs migrations d'origine, à partir des valeurs courantes, puis
   versionnées de la même façon là où la valeur change. `version_formule` est
   inchangée : la méthode est la même, seules les données sont révisées.
   - écarts relatifs CAMS − NASA POWER, GHI, DNI et DHI (prolongés par 0032,
     ADR-0017, ADR-0018) ;
   - fraction diffuse CAMS, mensuelle et annuelle (0040, ADR-0025) ;
   - heures équivalentes pleines CAMS, puis productible spécifique théorique
     (0038, ADR-0023) ;
   - indice de clarté `kt` CAMS (0041, ADR-0026), mêmes fonctions pures et
     paramètres.

   La dégénérescence de pixel (0042, ADR-0027) dépend seulement des groupes de
   séries identiques : la migration vérifie qu'ils sont les mêmes avant et
   après.
4. **Notes publiques** :
   - la mise en garde de 0054 sur les 426 séries mensuelles est remplacée par
     celle de la révision gravée, qui en donne l'ampleur ;
   - la phrase des 426 séries journalières dit que la moyenne des jours redonne
     désormais le mensuel courant, 2021-2025 compris ;
   - une phrase est ajoutée aux 994 séries dérivées CAMS.

## Résultats

**2005-2020** : identique, valeur par valeur, aux valeurs gravées, pour les
trois grandeurs et les 142 localités.

**2021-2025** (révisé − gravé en 0030, 8 520 mois-localités par grandeur) :

| Grandeur | Mois changés | Écart moyen (kWh/m²/jour) | Relatif | Écart maximal | Par localité |
|---|---:|---:|---:|---|---|
| GHI | 8 489 | +0,018 | +0,33 % | +0,118 (Sandégué, 09/2022) | de −0,008 (Méagui) à +0,041 (Tanda) |
| DNI | 8 502 | +0,025 | +0,65 % | +0,154 (Bongouanou, 09/2022) | de −0,006 (Méagui) à +0,051 (Tanda) |
| DHI | 8 481 | −0,002 | −0,09 % | −0,031 (Facobly, 08/2021) | de −0,007 (région du Guémon) à +0,005 (Tabou) |

- Le GHI monte d'année en année : +0,014 en 2021, +0,019 en 2025. Il n'y a pas
  de rupture.
- Ces chiffres redonnent ceux que 0054 avait obtenus avec la moyenne des jours
  servis.

**Grandeurs dérivées versionnées** : 62 299 lignes. Chaque valeur révisée
change toutes les grandeurs qui en dépendent. La fraction diffuse change
chaque mois, car le DHI ou le GHI y est révisé à chaque fois. Effet de la
révision sur les lignes versionnées (nouvelle − ancienne) :

| Grandeur | Lignes | Écart moyen | Écart maximal (absolu) | Moyenne avant → après |
|---|---:|---:|---:|---|
| Écart relatif GHI CAMS − NASA | 8 489 | +0,42 point | 3,32 points | 11,87 % → 12,30 % |
| Écart relatif DNI CAMS − NASA | 8 502 | +1,49 point | 15,14 points | 60,28 % → 61,77 % |
| Écart relatif DHI CAMS − NASA | 8 481 | −0,09 point | 1,34 point | 6,16 % → 6,06 % |
| Fraction diffuse, mensuelle | 8 520 | −0,0026 | 0,0188 | 0,4948 → 0,4923 |
| Fraction diffuse, annuelle | 710 | −0,0021 | 0,0055 | 0,4871 → 0,4850 |
| HEP, mensuelles | 8 489 | +0,55 h | 3,55 h | 164,69 h → 165,24 h |
| HEP, annuelles | 710 | +6,5 h | 16,6 h | 1 977 h → 1 984 h |
| Productible théorique, mensuel | 8 489 | +0,44 kWh/kWc | 2,84 kWh/kWc | 131,76 → 132,19 |
| Productible théorique, annuel | 710 | +5,2 kWh/kWc | 13,3 kWh/kWc | 1 582 → 1 587 |
| `kt`, mensuel | 8 489 | +0,0018 | 0,0115 | 0,5488 → 0,5506 |
| `kt`, annuel | 710 | +0,0018 | 0,0046 | 0,5471 → 0,5489 |

Les groupes de séries CAMS identiques sont les mêmes avant et après : la
dégénérescence de pixel est inchangée.

**Cohérence retrouvée** : la moyenne des jours CAMS des mois complets redonne
le mensuel courant à 0,0001 kWh/m²/jour près sur 2005-2025, soit 35 446
mois-localités par grandeur.

**Reproductibilité** :
- régénérer les CSV de révision depuis le cache redonne les mêmes octets ;
- l'aller-retour `downgrade`/`upgrade` redonne la même empreinte.

## Conséquences

- Le mensuel CAMS courant et le journalier CAMS sont de nouveau cohérents sur
  toute la période : la moyenne des jours des mois complets redonne le mensuel
  à 0,0001 kWh/m²/jour près, 2021-2025 compris.
- Les valeurs remplacées restent consultables en base, avec leur période de
  validité ; une lecture « à date » reste possible.
- Une future révision d'une source suivra le même chemin : nouveau CSV daté,
  migration qui clôt et remplace, notes mises à jour, dérivées recalculées.
- Le CSV d'extension de 0030 n'est plus la valeur courante de CAMS 2021-2025 :
  les tests de fidélité lisent le CSV de révision par-dessus.
