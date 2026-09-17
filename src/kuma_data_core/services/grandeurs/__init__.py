"""Couche service de calcul des grandeurs Kuma F1 stockées.

Sous-package par grandeur : chaque module orchestre la lecture des mesures
amont (typiquement ``mesures_ressource``), l'agrégation selon la formule
documentée en fiche méthodologique, et l'insertion dans ``grandeurs_metier``.

Grandeurs stockées : ``hep`` (Heures équivalentes pleines, agrégation
cumulative GHI), ``kt``, ``fraction_diffuse``, ``productible_*``,
``variabilite_*``, ``humidex``, ``indicateur_qualite_donnees``.
"""
