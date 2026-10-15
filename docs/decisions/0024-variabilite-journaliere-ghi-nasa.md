# ADR-0024 : Variabilité journalière du GHI NASA POWER (34 localités)

Date : 2026-10-15. Statut : accepté — **gravé** (migration 0039, 2026-10-15).

## Contexte

La grandeur `variabilite_journaliere` (id 5, F1 `stockee`, sans dimension) est
seedée depuis 0002 avec sa fiche méthodologique
(`docs/methodologie/grandeurs/variabilite_journaliere.md`) et son service
(`services/grandeurs/variabilite_journaliere.py`), hérités du moteur. Elle
demande le **GHI journalier** NASA POWER, grain désormais disponible aux 34
localités du lot « pilotes + régions » (ADR-0016), sur 1991-2025 (ADR-0018).
Utilité éditoriale de la fiche : le dimensionnement du stockage (plus le
coefficient de variation est élevé, plus il faut lisser).

## Décision

### Définition héritée, reproduite à l'identique (version 1)

```
CoV(annee) := écart-type(GHI_jour sur annee) / moyenne(GHI_jour sur annee)
```

Les deux points à trancher ont été lus dans le code du service, qui fait foi :

- **Écart-type de population** (division par N, `ddof=0`). La fiche écrit
  « écart-type d'échantillon (`ddof=0`, divisé par N) » : le terme est impropre
  (un écart-type d'échantillon divise par N − 1), mais la formule et le service
  divisent bien par N. L'écart-type d'échantillon donnerait des valeurs plus
  hautes d'un facteur √(N/(N−1)), soit +0,14 % sur 365 jours.
- **Complétude stricte des jours civils** : une année n'est gravée que si ses
  365 ou 366 jours sont présents (et si la moyenne est > 0). Contrairement à la
  fraction diffuse (ADR-0014), elle se vérifie ici **au grain journalier**.
  Comme le service, seules les mesures courantes (`valide_au IS NULL`, statut
  non `deprecie`) entrent dans le calcul.
- **Annuel uniquement** (pas de ligne mensuelle : 28 à 31 jours ne suffisent pas
  à un coefficient de variation robuste).

### Périmètre et gravure (migration 0039)

- 34 séries `variabilite_journaliere_nasa_power_<localité>`, source
  `kuma_calculs`, méthode `calcul_derive`, période 1991-2025 ;
- **1 190 lignes annuelles** (35 ans × 34 localités), confiance **B** (entrée
  satellite B). Les 1 190 années sont complètes : aucune n'est écartée, aucune
  valeur de remplissage (GHI journalier minimal : 0,39 kWh/m²/jour).
- Calcul **hors-ligne, en base**, par agrégation SQL sur `mesures_ressource`.
  `stddev_pop` et `avg` en `numeric` (sommes des valeurs et des carrés exactes,
  donc indépendantes de l'ordre d'agrégation), quotient converti en `float8`
  (patron ADR-0017).
- Garde-fous : grandeur conforme (id, stratégie, version de formule), aucune
  série ni ligne préexistante, 34 séries GHI journalières NASA en amont sur
  1991-2025, 1 190 lignes sur 34 séries et 35 années, toute valeur dans
  `]0, 1[`. `ANALYZE grandeurs_metier` en fin de migration. Le `downgrade`
  supprime lignes et séries ; la grandeur (seed 0002) est conservée.

### Vérifications

| Contrôle | Résultat |
|---|---|
| Recalcul indépendant depuis les CSV journaliers committés (`statistics.pstdev / fmean`) | écart relatif max 3·10⁻¹⁶ |
| Fonction pure du service hérité sur les mêmes données | identique (tolérance relative 10⁻¹²) |
| Écart-type d'échantillon (N − 1) | rejeté par la même tolérance |
| Aller-retour 0039 → 0033 → 0039 et reconstruction depuis 0033 | empreintes md5 identiques |

## Résultat (1991-2025)

Plage gravée **0,135 – 0,255**, moyenne 0,178 : entièrement dans la plage
intertropicale attendue par la fiche (`[0,10 ; 0,40]`).

| Bande de latitude | Localités | CoV moyen |
|---|---:|---:|
| < 6° N (littoral) | 7 | 0,197 |
| 6 – 7,5° N | 14 | 0,173 |
| 7,5 – 9° N | 6 | 0,174 |
| ≥ 9° N (nord) | 7 | 0,174 |

| Localité | Moyenne | Min (année) | Max (année) |
|---|---:|---:|---:|
| San-Pédro (région) ≡ Gbôklé | **0,226** | 0,211 (2004) | 0,255 (2002) |
| Abidjan ≡ Grands-Ponts | 0,191 | 0,153 (1994) | 0,230 (2024) |
| Yamoussoukro | 0,170 | 0,145 (2021) | 0,217 (2024) |
| Korhogo ≡ Poro ≡ Tchologo | 0,176 | 0,155 (1996) | 0,205 (2024) |
| Bafing | **0,158** | 0,140 (1994) | 0,177 (2020) |

**Lecture (constats, pas validation) :**

- **Gradient nord-sud : oui, mais côtier, pas monotone.** Le littoral (< 6° N)
  est le plus variable (0,197 ; maximum San-Pédro, 0,226) ; au-delà, le CoV est
  quasi constant (0,173-0,174) du centre au nord. Corrélation avec la latitude
  −0,46 (longitude +0,36). Les moins variables sont à l'ouest forestier et
  montagneux (Bafing 0,158, Tonkpi 0,161, Kabadougou 0,163, Guémon et Cavally
  0,165), pas au nord. L'hypothèse « le sud est plus variable » ne vaut que pour
  la frange côtière.
- **Le cycle saisonnier ne pèse qu'un quart de la variance.** En décomposant la
  variance annuelle des GHI journaliers en variance des moyennes mensuelles
  (saisonnière) et variance intra-mois, la part saisonnière vaut 27 % en
  moyenne (de 5 à 64 %). Le maximum côtier vient de la variabilité **d'un jour
  à l'autre** (CoV intra-mois 0,173 sur le littoral contre 0,139-0,156
  ailleurs), pas d'un cycle saisonnier plus marqué (0,090 sur le littoral contre
  0,101 en bande 6-7,5° N). C'est cette composante que le stockage lisse.
- **Tendance : faible, et portée par la composante saisonnière.** Moyenne
  nationale par décennie : 0,172 (1991-2000), 0,178 (2001-2010), 0,181
  (2011-2020), 0,188 (2021-2025) ; pente +0,005 par décennie sur 1991-2025
  (r² 0,31), positive aux 34 localités. Mais **aucune pente sur 2001-2020**
  (+0,0004 par décennie, r² 0,001). La composante intra-mois reste plate
  (0,150-0,153 par décennie) ; seule la composante saisonnière monte (0,080 →
  0,107). Ce creusement du contraste saisonnier **se retrouve dans CAMS**
  (coefficient de variation des 12 moyennes mensuelles de GHI, 142 localités,
  2005-2025 : +0,013 par décennie pour CAMS comme pour NASA). La décennie
  1991-2000 précède la frontière de produit NASA de 2001 (ADR-0013) : un effet
  de produit n'y est pas exclu.
- **Années extrêmes.** **2024** est l'année la plus variable (moyenne nationale
  0,209, maximum de 27 localités sur 34) : saison sèche plus ensoleillée et
  mousson plus sombre que d'habitude. Le motif est **corroboré par CAMS** au
  grain mensuel (142 localités, écart à 2005-2023 : janvier +0,29 / +0,25,
  novembre +0,30 / +0,40, août −0,41 / −0,52 kWh/m²/jour pour CAMS / NASA) :
  ce n'est pas un artefact de NASA seul. **1994** est la moins variable
  (0,155, minimum de 22 localités).
- **Maille NASA** (~1°) : 22 valeurs moyennes distinctes pour 34 localités
  (San-Pédro ≡ Gbôklé, Abidjan ≡ Grands-Ponts, Korhogo ≡ Poro ≡ Tchologo…),
  comme la fiche le signalait pour Kindia et Mamou.

## Conséquences

- Première grandeur dérivée calculée depuis le **journalier** de l'instance.
- La terminologie de la fiche (« échantillon » pour `ddof=0`) reste à corriger
  dans une révision éditoriale de la fiche ; la définition, elle, est inchangée.
- Une extension aux 108 départements suppose leur journalier NASA (non gravé,
  ADR-0016).
