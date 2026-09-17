"""Emetteur de capsule (fichier Kuma), la ressource complete du moteur.

Assemble la ressource que le moteur mini-reseau consomme, a partir de la donnee
brute du Core et, en ligne seulement, des facteurs de calage. Deux
fonctionnements, un seul assembleur : la capsule hors-ligne est brute (calage
absent), le mode en ligne est calibre (calage present). Cf. le cadrage
``recherche/assembleur-ressource-capsule.md``.

Ce paquet ne fait que l'assemblage PUR (arithmetique + format). L'acces aux
donnees (resolution, horaire, climatologie, appel kuma-calage) est une couche a
part, branchee au-dessus.
"""
