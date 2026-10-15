# ADR-0031 — Journalier aux 108 départements et audit par série des gravures massives

Date : 2026-10-15. Statut : accepté — **gravé** (migrations 0046-0049).

## Contexte

Le journalier ne couvrait que 34 localités (3 pilotes + 31 régions) : rayonnement
NASA POWER (ADR-0016), météo NASA POWER (ADR-0020), particules CAMS EAC4
(ADR-0022). Les calculs de l'API qui exigent une série journalière — POA
paramétrable et bifacial, correction thermique, énergie ECS, degrés-jours,
salissure, PR réaliste — et les grandeurs dérivées du journalier (variabilité,
humidex) s'arrêtaient donc aux régions ; les 108 autres départements n'avaient
que du mensuel.

Étendre le journalier aux 108 départements représente **13 057 092 mesures**
(11 familles × 108 localités), trois fois tout le journalier existant. Or le
trigger d'audit `trg_audit_mesures_ressource` recopie chaque ligne insérée ou
supprimée dans `audit_log` (`to_jsonb` de la ligne) : à la révision 0045, l'audit
pesait **5,4 Go sur 7,1 Go** de base (76 %). Ce lot y aurait ajouté environ
11 Go, pour des valeurs déjà versionnées une à une dans des CSV gzip committés et
rejouables.

## Décision

1. **Audit par série pour les gravures massives** (décision de l'utilisateur,
   module `seeds/audit_par_serie.py`). Les migrations 0046-0048 suspendent le
   trigger d'audit de `mesures_ressource` le temps de leur insertion ou
   suppression, dans la transaction de migration, et écrivent **une entrée
   d'audit par série** : opération `I` ou `D`, `id_ligne_auditee =
   'serie:<id>'`, et le code de série, le nombre de mesures, le premier et le
   dernier jour, le fichier CSV et son empreinte SHA-256, la révision. Les
   séries elles-mêmes, les grandeurs dérivées, les migrations antérieures et
   toute écriture applicative gardent l'audit ligne à ligne.
2. **Lot `departements`** (`seeds/journalier_departements_civ.py`) : les 108
   départements hors pilotes, aux contrats du lot pilotes + régions, période
   d'un seul tenant (un CSV par famille, 1991-2025 ; 2001-2025 pour le DNI, le
   DHI et l'albédo ; 2003-2025 pour les particules).
3. **Migrations** :
   - 0046 — rayonnement NASA POWER (GHI, DNI, DHI) : 324 séries, 3 352 968 mesures ;
   - 0047 — météo NASA POWER (T2M, RH2M, vent à 2 et 10 m, pluie, albédo) :
     648 séries, 7 889 508 mesures ;
   - 0048 — particules CAMS EAC4 (PM2.5, PM10) : 216 séries, 1 814 616 mesures ;
   - 0049 — grandeurs dérivées : variabilité journalière (3 780 lignes) et
     humidex (49 140 lignes), mêmes définitions que 0039 et 0045.

## Résultats et constats

**Audit par série.** 0046 écrit 648 entrées d'audit (324 séries + 324 entrées
par série) au lieu d'environ 2,8 Go d'audit ligne à ligne ; 0047, 1 296 entrées
(1,6 Mo) au lieu d'environ 6,7 Go ; 0048, 432 entrées (0,7 Mo). Un aller-retour
écrit les entrées `D` puis `I` par série, sans aucune entrée ligne à ligne pour
les mesures. Coût en table : environ 250 octets par mesure (+0,83 Go pour 0046,
+1,96 Go pour 0047, +0,72 Go pour 0048). Les CSV gzip ajoutent 66 Mo au dépôt.

Deux défauts de l'utilitaire relevés pendant la gravure ont été corrigés : le
paramètre de révision passé à `jsonb_build_object` doit être typé (`CAST ... AS
text`), et la réactivation du trigger ne se fait plus dans un `finally`, où elle
masquait l'erreur d'origine d'une transaction déjà en échec.

**Rayonnement (0046).**
- 35 séries distinctes sur les 108 départements pour GHI, DNI et DHI, et
  toujours 35 sur les 142 localités. La partition journalière est identique à
  la partition mensuelle (cellules CERES de 1°, ADR-0027).
- Moyenne des jours de chaque mois = mensuel NASA à 0,000175 kWh/m²/jour près
  (110 160 mois).
- Aucun jour DHI > GHI sur 986 148 paires.
- GHI journalier de 0,39 (Sassandra, 2008-06-29) à 8,03 kWh/m²/jour (Tengréla,
  2015-03-31) ; DNI nul trois jours (Tabou 2007-04-08, Minignan 2010-05-02 et
  2022-08-12), déjà présents dans la même cellule au lot pilotes + régions.

**Météo (0047).**
- MERRA-2 distingue 76 séries sur 108 départements, avec la même partition pour
  les cinq grandeurs ; 77 sur les 142 localités. L'albédo (CERES) en distingue 35.
- Moyenne des jours = mensuel 0034 à 0,005 près (arrondi du mensuel servi,
  259 200 mois).
- T2M de 16,93 °C (Minignan, 2016-01-06) à 35,94 °C (Tengréla, 2024-03-14) ;
  22 des 24 jours-localités au-delà de 35 °C tombent en 2024-2025, ce qui est
  cohérent avec la hausse de la T2M NASA non confirmée par ERA5 (ADR-0021).
- RH > 90 % : 6,4 % des jours (8,4 % au sud de 6° N, 1,75 % au nord de 8,5° N).
- **Pluie, gravée telle quelle avec une mise en garde sourcée.** 20 jours au-delà
  de 200 mm, dont 15 en septembre 2022 : San-Pédro 726,74 mm et Sassandra
  710,75 mm le 16, Taï 403,43 mm le 23. S'y ajoutent Ouangolodougou 321,59 mm le
  2025-12-02 en saison sèche, Téhini 288,76 mm le 2023-03-17 et Tabou trois fois
  en 2024. La **rupture vers 2017** se confirme aux 108 départements : de 16,1
  jours > 50 mm par an (1991-2015) à 192,0 (2017-2025), soit ×11,9, contre ×12,5
  aux 34 localités. Les 108 départements sont tous touchés, alors que le nombre
  de jours de pluie bouge peu (−3,5 % à 1 mm). C'est l'intensité qui change,
  probablement dans le produit NASA ; la cause n'est pas établie et les valeurs
  sont à recouper avec ERA5.

**Particules (0048).**
- Les 108 départements tombent sur 48 mailles EAC4 de 0,75°, dont 23 nouvelles
  par rapport aux 34 localités. 69 séries sur 108 par grandeur sont identiques
  à une série déjà gravée.
- Extrêmes journaliers plus élevés qu'aux 34 localités : PM2.5 1 401,7 et PM10
  1 920,0 µg/m³ (Danané et Sipilou, 2016-02-21).
- Aucun jour PM2.5 > PM10.
- Journalier = mensuel 0037 à 0,0003 µg/m³ près, **sauf mars 2024** : jusqu'à
  6,0 % d'écart (Doropo), dans 61 départements sur 108 au-dessus du mensuel.
  C'est une incohérence de la source (ADR-0022), bornée à moins de 6,5 % par les
  tests.
- Deux précisions à l'ADR-0022 :
  - la seule analyse 3-horaire où PM2.5 > PM10 (2004-07-23, 15 UTC) tombe dans
    la maille de Méagui et San-Pédro ;
  - EAC4 sert aussi quelques analyses nulles avant 12 UTC (3 sur les 48 mailles,
    le 2025-07-11).

**Grandeurs dérivées (0049).** Variabilité journalière (3 780 lignes annuelles) et
humidex (45 360 mensuelles et 3 780 annuelles) aux 108 départements, recalculés
à 10⁻¹² près en relatif par les fonctions pures des services hérités. Les 34
séries du lot pilotes + régions sont inchangées.

## Conséquences

- Avec les 3 pilotes, les **111 départements** ont un journalier complet
  (rayonnement, météo, particules) : les calculs journaliers de l'API et les
  grandeurs dérivées du journalier couvrent tout le territoire.
- L'audit des mesures massives se lit par série : pour retrouver une valeur, on
  rejoue le CSV dont l'empreinte est consignée. Une correction applicative
  ultérieure d'une mesure reste auditée ligne à ligne.
- La pluie NASA aberrante (septembre 2022, hausse des fortes pluies depuis 2017,
  ADR-0020) et l'incohérence EAC4 de mars 2024 (ADR-0022) valent aussi pour ce lot.
