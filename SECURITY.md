# Politique de sécurité

## Signaler une vulnérabilité

Si vous découvrez une faille de sécurité dans Kuma Data Core, signalez-la
en privé, sans ouvrir d'issue publique. Deux voies possibles :

- le signalement privé de GitHub (onglet **Security** du dépôt, « Report a
  vulnerability ») ;
- un contact direct avec le mainteneur (Siba Kalivogui, via
  [kumascience.com](https://kumascience.com)).

Merci d'inclure une description du problème, les étapes de reproduction et,
si possible, une évaluation de l'impact. Laissez un délai raisonnable pour
un correctif avant toute divulgation publique.

## Versions supportées

Le projet suit un versionnement sémantique. Les correctifs de sécurité
sont appliqués à la dernière version publiée.

## Bonnes pratiques du dépôt

- Aucun secret n'est commité : chaînes de connexion, mots de passe, clés
  d'API tierces ou internes, jetons, clés privées. `gitleaks` s'exécute en
  pre-commit pour les détecter avant qu'ils n'atteignent le dépôt.
- Les secrets de développement local vivent dans un fichier `.env` non
  versionné à la racine. Voir `docker/.env.example` pour le modèle.
- Aucune donnée personnelle ni donnée de production n'est commitée. Les
  jeux de test sont synthétiques ou issus de sources publiques ouvertes.

## En cas de fuite de secret

1. Rotation immédiate du secret côté fournisseur. Tant qu'il n'est pas
   remplacé chez l'émetteur, l'historique Git reste exposé.
2. Révocation des accès dérivés (sessions, jetons, clés secondaires).
3. Réécriture de l'historique si nécessaire, en sachant qu'elle ne suffit
   pas si le dépôt a déjà été cloné par un tiers.

L'étape 1 est non négociable et précède toute autre considération.
