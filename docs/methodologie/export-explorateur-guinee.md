# Export de l'explorateur Guinée pour Kuma Science

**Statut** : note méthodologique support d'un script utilitaire one-shot
(`scripts/exporter_explorateur_guinee.py`). Mise à jour à chaque
évolution du format d'export.

**Référence aval** : dépôt séparé `kuma-science` (vitrine éditoriale
Astro), consommateur statique des fichiers produits sous
`out/explorateur-guinee/guinee/`.

---

## 1. Objectif

L'explorateur Guinée est la composante navigable du site
[kumascience.org](https://kumascience.org) qui rend visite par visite les
mesures du pilote guinéen : 6 villes × 16 grandeurs stockées,
avec accès direct aux séries en CSV. La vitrine est servie en statique
(pas d'appel runtime client vers l'API privée du Core), les
données étant figées au moment du build du site.

Le script génère l'arborescence statique attendue par le site :

- Une arborescence par ville sous `out/explorateur-guinee/guinee/<ville>/`.
- Un fichier CSV par série, nommé `<grandeur>.csv` (ou
  `<grandeur>_<variante>.csv` si plusieurs séries d'une même grandeur
  cohabitent pour la ville, typiquement journalier vs mensuel).
- Un `manifest.json` versionné par ville recensant les séries exposées,
  leurs métadonnées éditoriales et leur famille doctrinale.

Le script est **manuel** par construction : pas de cron, pas de CI, pas
d'endpoint API exposant les fichiers. Le fondateur le lance après chaque
ingestion susceptible de modifier ce que voit le visiteur de la vitrine.

---

## 2. Mode d'emploi

```powershell
# Depuis la racine du dépôt kuma-data-core, services Docker démarrés :
uv run python scripts/exporter_explorateur_guinee.py
```

Le script :

1. Lit `.env` pour les paramètres PostgreSQL via `Settings` (mêmes
   variables que l'API et Alembic), aucune lecture ni écriture de
   secret en dehors de cette source.
2. Ouvre une session SQLAlchemy via
   `kuma_data_core.db.session.get_session_factory`.
3. Liste les 6 villes pilotes et, pour chacune, les séries actives hors
   F2 paramétrables (cf. § 3.2 sur le périmètre exact).
4. Résout la table-cible de chaque série via
   `kuma_data_core.api.services.serie_lecture.resolve_table_from_series_metadata`
   (`mesures_ressource`, `mesures_ressource_mensuelles` ou
   `grandeurs_metier` via la vue `v_grandeurs_metier_courantes`).
5. Lit les mesures courantes (`valide_au IS NULL` + statut non
   déprécié) et les écrit en CSV avec encoding UTF-8.
6. Écrit le `manifest.json` par ville après contrôle du garde-fou
   doctrinal (cf. § 5).
7. Imprime un résumé console : nombre de villes, nombre de séries par
   famille, chemin absolu de la sortie, séries éventuellement ignorées
   (warning non bloquant).

Procédure de publication vers `kuma-science` (manuelle,
hors-périmètre du script) :

```powershell
# Depuis le poste fondateur, après génération réussie :
Copy-Item -Recurse out/explorateur-guinee/guinee ../kuma-science/public/data/explorateur-guinee
# Puis commit + push côté dépôt kuma-science.
```

---

## 3. Périmètre

### 3.1 Villes pilotes (énumération exhaustive)

Six villes pilotes, codes localités préfixés `gin_` :

- `gin_conakry_kaloum` (côtier, capitale)
- `gin_kankan` (intérieur soudanien)
- `gin_kindia` (basse Guinée, transition)
- `gin_labe` (Fouta-Djalon, altitude 1025 m WMO)
- `gin_mamou` (Fouta-Djalon, transition altitude)
- `gin_nzerekore` (sud forestier)

Les autres entrées de la table `localites` (continent, pays, régions
administratives, communes historiques Conakry non pilotes) ne sont pas
exposées : elles n'ont pas de séries de mesures associées à ce jour.

### 3.2 Grandeurs incluses (énumération exhaustive)

Toutes les séries actives des 6 villes vivant dans une des trois tables
de stockage :

- `mesures_ressource` (journalier) : 6 grandeurs brutes NASA POWER
  2021-2025 (`ghi`, `dni`, `dhi`, `t2m`, `rh2m`, `kt`).
- `mesures_ressource_mensuelles` : référentiels mensuels (SARAH-3 ICDR
  GHI 2021-2023 ; NASA POWER climatologie 1991-2020 OMM).
- `grandeurs_metier` (via `v_grandeurs_metier_courantes`) : grandeurs
  F1 stockée Kuma (`hep`, `fraction_diffuse`, `humidex`,
  `productible_specifique_theorique`, `variabilite_journaliere`,
  `indicateur_qualite_donnees`) et 3 grandeurs F1 calculée à la volée
  référentielles (`ecart_relatif_referentiel`,
  `rang_referentiel_temporel`, `rang_referentiel_spatial`).

### 3.3 Grandeurs exclues (énumération exhaustive)

Cinq grandeurs F2 paramétrables explicitement écartées par le script
(constante `_GRANDEURS_F2_EXCLUES`) car elles sont calculées à la volée
côté API et n'ont pas de séries fixes consultables sans paramètres
utilisateur :

- `poa_parametrable`
- `productible_correction_thermique`
- `productible_pr_fourni`
- `energie_utile_ecs`
- `degre_jour_climatisation`

Filtres SQL alignés sur le routeur `/v1/series` : `actif = TRUE` et
exclusion par `grandeur_code <> ALL(:grandeurs_exclues)`. Les séries
dépréciées éditorialement (`statut = 'deprecie'`) sont également
écartées par construction de la vue courante côté `grandeurs_metier`.

---

## 4. Structure de la sortie

### 4.1 Arborescence

```
out/explorateur-guinee/guinee/
├── manifest.json
├── conakry_kaloum/
│   ├── ghi.csv
│   ├── dni.csv
│   ├── ...
│   └── manifest.json
├── kankan/
│   └── ...
├── kindia/
├── labe/
├── mamou/
└── nzerekore/
```

Le slug ville est obtenu en retirant le préfixe pays `gin_` du code
localité (cf. fonction `_slug_ville`). La racine `out/` est ignorée
par git.

### 4.2 Format CSV par famille

Trois schémas CSV distincts selon la famille de la série :

| Famille | Provenance | Colonnes |
|---|---|---|
| journalier | `mesures_ressource` (brutes NASA POWER) | `date,valeur,unite,niveau_confiance,statut` |
| mensuel | `mesures_ressource_mensuelles` (SARAH-3, climato NASA) | `mois,valeur,unite,niveau_confiance,statut` |
| calculee / referentielle | `grandeurs_metier` (via vue courante) | `periode,valeur,unite,niveau_confiance,statut,periode_type` |

Encoding UTF-8, séparateur virgule, sans BOM. Le décodage côté
consommateur Astro est trivial (lecture native).

### 4.3 `manifest.json` par ville

Pour chaque ville, un objet JSON qui liste les séries exposées avec
métadonnées éditoriales : `code_serie`, `grandeur_code`,
`grandeur_label`, `unite_symbole`, `source_code`, `source_label`,
`famille` (`brute` / `mensuelle` / `calculee` / `referentielle`),
`granularite` (`journalier` / `mensuel` / `mixte`), `periode_debut`,
`periode_fin`, `nombre_mesures`, `niveau_confiance` dominant, `couche`
doctrinale (B actuellement, jamais A - cf. garde-fou § 5).

---

## 5. Garde-fou doctrinal

Le script applique un contrôle final avant l'écriture du `manifest.json`
(lignes 597-623 du script) : il refuse l'export par `RuntimeError` si
une série exposée sort en **couche A** ou avec un **niveau de confiance
A dominant**, tant qu'aucune mesure terrain n'est intégrée.

Cohérence avec la doctrine Kuma actée :

- **Couche A** = calibration terrain (mesures sol locales, ANM Guinée
  notamment). **Vide actuellement** ; activation conditionnée à
  l'ingestion effective de séries ANM Guinée.
- **Couche B** = substrat modélisé + cross-check inter-source (NASA
  POWER, SARAH-3 ICDR). Toutes les séries actuelles vivent ici.
- **Couche C** = post-traitement éditorial Kuma + conventions normatives
  (IEC 61724-1, WMO-No.8).

Si l'export bascule en `RuntimeError`, c'est le signe qu'une source
ou un override a été introduit sans mise à jour cohérente du mapping
`_COUCHE_PAR_SOURCE` ou sans arbitrage explicite de la doctrine. Le
correctif est éditorial avant d'être logiciel.

---

## 6. Sécurité

- Aucune lecture ni écriture de secret. Les paramètres de connexion
  PostgreSQL sont obtenus via `Settings` (lecture mémoïsée de `.env`),
  jamais inscrits dans les fichiers de sortie ni journalisés.
- Les CSV ne contiennent que des données scientifiques publiques du
  pilote guinéen (mesures de ressource solaire et climat, statuts et
  niveaux éditoriaux). L'accès libre du pilote a été acté en cadrage.
- Le dossier de sortie `out/` est `.gitignored` côté `kuma-data-core` ;
  l'inscription des fichiers se fait exclusivement dans le dépôt
  consommateur `kuma-science` après revue.

---

## 7. Limites connues

1. **Caractère manuel.** Pas d'automatisation : si le fondateur oublie
   de relancer le script après une ingestion susceptible de modifier la
   vitrine, le site affiche un état périmé. Acceptable tant que les mises
   à jour sont rares, à reconsidérer quand de nouvelles sources seront
   ingérées plus fréquemment.

2. **Aucun test automatisé.** Le script repose sur la lecture manuelle de
   son résumé console après chaque exécution. Un filet de sécurité (test
   de fumée sur structure de sortie, validation du manifest) reste
   candidat si la cadence d'exécution augmente.

3. **Périmètre figé aux 6 villes pilotes.** L'extension à de nouvelles
   localités exige une modification de la constante `_VILLES_PILOTES`
   du script et une revérification du mapping `_COUCHE_PAR_SOURCE` au
   cas où de nouvelles sources accompagneraient les nouvelles localités.

4. **Granularité `mixte` sur `grandeurs_metier`.** Une série
   `grandeurs_metier` peut contenir des lignes mensuelles, annuelles ou
   statiques. Le manifest expose `granularite: "mixte"` pour ce cas ;
   le consommateur Astro doit lire la colonne `periode_type` du CSV
   pour traiter chaque ligne correctement.

5. **Pas de filtre sur `statut` éditorial autre que `deprecie`.** Toutes
   les séries actives sont incluses indépendamment de leur statut
   (`brut`, `valide_auto`, `valide_humain`, `publie`,
   `passe_plat_non_valide`). Un filtre plus strict (typiquement
   `statut IN ('publie', 'valide_humain')`) sera probablement nécessaire
   avant exposition publique élargie.

6. **Pas d'inclusion des séries `valide_au IS NOT NULL`.** L'export ne
   reflète que l'état courant. Les anciennes versions des valeurs
   (rotation `valide_du` / `valide_au`) ne sont pas exposées dans
   l'explorateur.
