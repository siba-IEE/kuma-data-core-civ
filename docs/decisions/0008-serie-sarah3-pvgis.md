# ADR-0008 : contrat de série — GHI mensuel SARAH-3 (PVGIS), écart inter-source

Date : 2026-09-17. Statut : accepté.

## Contexte

Après le GHI/DNI NASA POWER (ADR-0007), on ajoute une **deuxième source** de
GHI aux mêmes points, première brique de l'**écart inter-source** — le savoir
qui distingue ce moteur (une valeur porte sa source *et* son désaccord avec les
autres). Source retenue : **SARAH-3** (CM SAF), servie par l'API ouverte
**PVGIS** (JRC), déjà seedée (``sarah3_monthly``, id 11). Reconnaissance en
lecture seule confirmée : API joignable, couverture **2005-2023**, variable
``H(h)_m`` = irradiation horizontale **mensuelle totale** (kWh/m²/mois).

## Décision

**Contrat** — identique à ADR-0007 (grandeur ``ghi``, unité ``kwh_par_m2_jour``
héritée, granularité ``mensuel``, méthode ``modele_satellitaire``, confiance
**B**, statut ``brut``), à deux différences imposées par la source :

1. **Source** : ``sarah3_monthly`` (id 11).
2. **Couverture** : **2005-2020** (192 mois). SARAH-3/PVGIS démarre en 2005 ;
   on grave le **recouvrement** avec le GHI NASA POWER (comparaison stricte
   période-à-période). Les années 2021-2023 disponibles côté PVGIS sont
   écartées de cette passe (non couvertes côté NASA POWER déjà gravé).
3. **Normalisation** : PVGIS fournit l'irradiation **mensuelle totale**
   (``H(h)_m``, kWh/m²/mois) ; on la ramène en **moyenne journalière** en
   divisant par le **nombre de jours réel du mois** (années bissextiles
   incluses), pour respecter l'unité ``kwh_par_m2_jour`` de la grandeur et
   rester comparable au GHI NASA POWER. Conversion **déterministe et
   documentée**, pas une estimation ; la valeur reste ``brut`` (donnée source
   exprimée dans l'unité cible).

**Reproductibilité** : ``scripts/ingest_pvgis_sarah3_mensuel.py`` (accès réseau)
régénère le seed ``series_pvgis_sarah3_ghi_mensuel_civ`` ; la migration 0010 le
lit hors-ligne.

## Écart inter-source constaté (reconnaissance, GHI moyen 2005-2020)

| Point | SARAH-3 | NASA POWER | écart |
|---|---:|---:|---:|
| Abidjan | 4,97 | 4,66 | **+6,6 %** |
| Yamoussoukro | 5,37 | 4,60 | **+16,6 %** |
| Korhogo | 5,88 | 5,29 | **+11,1 %** |

*(kWh/m²/jour, moyenne des mois communs.)* SARAH-3 est systématiquement plus
haut que NASA POWER, avec un écart variable selon le point — un désaccord réel
entre modèles satellitaires, non une erreur. C'est précisément ce que le moteur
doit tracer.

## Conséquences

- Deux sources indépendantes de GHI cohabitent aux mêmes points, comparables
  (même grandeur, même unité, même granularité, période de recouvrement).
- L'**écart inter-source** devient une grandeur **dérivable** (couche
  éditoriale / Jalon 3) : différence relative par (localité, mois) entre les
  deux séries ``ghi`` de sources différentes. Cet ADR ne grave que le **brut**
  SARAH-3 ; le calcul de l'écart et son statut de confiance relèvent d'une
  passe ultérieure.
- La normalisation « total mensuel → moyenne journalière » est le point de
  vigilance pour toute source à convention différente ; elle est isolée dans
  l'ingesteur et documentée par série.
- Ajouter DNI SARAH-3, d'autres points ou CAMS suivra le même schéma (une
  série = un ajout), en réévaluant couverture et convention d'unité par source.
