# ADR-0033 — Pluie journalière GPM IMERG pour les épisodes de lessivage

Date : 2026-10-15. Statut : accepté — **gravé** (migration 0052).

## Contexte

Le proxy de salissure (`taux_salissure_proxy`, modèle HSU de pvlib) et le PR
réaliste de l'API calculent l'encrassement des modules et leur nettoyage par la
pluie. Le modèle HSU nettoie les modules les jours où la pluie dépasse un seuil :
il dépend donc directement de la pluie **journalière** et de ses épisodes.

Jusqu'ici, ces deux calculs prenaient la pluie journalière NASA POWER
(`PRECTOTCORR`). L'ADR-0032 a établi qu'elle ne convient pas aux épisodes :

- elle est recalée par pentade sur CMAP « temps réel » ;
- ses 25 jours-localités au-delà de 200 mm ne sont confirmés ni par ERA5, ni
  par CHIRPS, ni par IMERG ;
- ses jours > 50 mm sont multipliés par 12 vers 2016-2017, une hausse propre à
  NASA.

## Décision (choix de l'utilisateur)

1. **Source des épisodes de lessivage : GPM IMERG**, servi par NASA POWER
   (paramètre `IMERG_PRECTOT`, intégré à POWER le 2025-03-04, version de données
   10.0.5, « IMERG v7B »).
   - Produit satellite multi-capteurs au 0,1°, au jour UTC (identique au jour
     local en Côte d'Ivoire).
   - Le Final Run est calé mensuellement sur les pluviomètres GPCC, avec un
     rapport borné à [0,2 ; 3] qui corrige le cumul sans toucher à l'occurrence
     des pluies.
   - Gravé aux 142 localités sur 1998-2025 (migration 0052) : nouvelle source
     `gpm_imerg` (id 17), 142 séries, 1 452 234 mesures, audit par série.
   - **Fin du Final Run** : la série V07 Final s'arrête au 2025-09-30 (calendrier
     de transition V08 de GPM). POWER sert ensuite le **Late Run**, calé sur la
     climatologie seulement. Les 92 derniers jours (2025-10-01 → 2025-12-31) en
     viennent ; c'est signalé dans la note des séries. Aucune rupture nette n'y
     apparaît : décembre 2025 est humide aussi pour ERA5.
2. **L'API épingle cette source** (`SOURCE_PLUIE_SALISSURE`, résolveur
   `_chercher_serie_pluie_salissure`) pour le proxy de salissure et pour le PR
   réaliste, qui cherchait auparavant la pluie comme compagne de même source que
   le GHI (NASA). La pluie NASA POWER n'est jamais retenue. Si la série IMERG
   manque, la réponse est une erreur 400 explicite : il n'y a pas de repli vers
   NASA.
3. Les séries de pluie NASA et ERA5 restent en base comme sources de
   comparaison.

## Résultats

Recoupement en base aux 142 localités, 1998-2025 (1 452 234 triplets de jours).

- **Les 25 jours-localités où NASA dépasse 200 mm**
  - IMERG y donne au plus **59,4 mm** le jour même. Son cumul de trois jours ne
    dépasse pas 107,9 mm, contre 270 à 938 mm pour NASA.
  - Côte sud-ouest le 2022-09-16 : 0 à 2,5 mm.
  - Septembre 2022 à San-Pédro : IMERG 66,4 à 77,4 mm, ERA5 111,9 à 169,2 mm,
    NASA 1 688,5 mm.
- **Pas de rupture**
  - Jours-localités > 50 mm par an : IMERG 325,5 (1998-2015) puis 322,1
    (2017-2025), soit ×0,99. Sur les mêmes périodes : NASA ×11,1, ERA5 ×1,50.
  - Les jours > 100 mm baissent légèrement entre l'ère de calage TRMM
    (1998-2013 : 17,1 par an) et l'ère GPM (2015-2025 : 13,7). C'est cohérent
    avec la mise en garde des notes de version V07.
- **Cumul et jours de pluie**
  - Cumul annuel : IMERG +1,9 %, NASA +19,0 %, ERA5 −2,1 %.
  - IMERG compte environ deux fois moins de jours ≥ 1 mm (≈ 121 par an) que les
    deux réanalyses, qui bruinent.
  - 99,9ᵉ centile IMERG stable : 81,7 puis 78,5 mm.
- **Corrélations journalières** : IMERG/ERA5 0,35 → 0,39 (Pearson global),
  IMERG/NASA 0,36 → 0,32. NASA/ERA5 est la seule paire où le Spearman bondit
  en 2016-2017.
- **Plus forts jours IMERG**
  - Adiaké 235,0 mm et Abidjan 234,2 mm le 2002-08-06 : six localités du
    sud-est y reçoivent de 168 à 235 mm, contre 19 à 30 mm pour NASA et 5 à
    14 mm pour ERA5. Puis Tabou 220,3 mm (2011-09-21).
  - Jours-localités au-delà de 200 mm : 4 pour IMERG, 25 pour NASA, 17 pour ERA5.
- **Maille** : 120 séries distinctes pour 142 localités.
- **Limites documentées** (notes de version V07) : changement d'étalon
  TRMM → GPM en 2014, saut d'environ 10 % sur les terres tropicales en août
  2001 dans l'algorithme combiné de référence, habileté moindre en zone côtière.

**API.** Sur la base complète, le proxy de salissure et le PR réaliste (mode
salissure) aboutissent avec la pluie IMERG ; leurs tests recalculent le modèle
HSU depuis cette pluie. La pluie NASA n'est retenue par aucun des deux.

**Identité des sources.** Les sources 16 (0012) et 17 (0052) sont insérées à id
figé. L'identité de la table, restée à 15 depuis le seed 0002, aurait fait
heurter la prochaine source insérée sans id. La migration 0052 la recale sur
le plus grand id.

## Conséquences

- La salissure et le PR réaliste sont calculables aux **142 localités** avec une
  pluie sans rupture ni jours extrêmes fantômes connus.
- Les résultats de salissure antérieurs, calculés sur la pluie NASA, ne sont pas
  comparables aux nouveaux.
- IMERG commence en 1998 ; les PM EAC4 commencent en 2003 : la fenêtre de la
  salissure reste bornée par les PM.
