"""Acquisition des entrées de la ressource depuis la base du Core.

Implémentation concrète de ``SourceCapsule`` (le protocole de ``construire``).
Lit trois choses au point :

- la **résolution** (lat, lon) → la localité dont la cellule échantillonne le
  point, et son code de climatologie (même logique que ``/v1/localites/resolution``) ;
- la **climatologie mensuelle** : moyenne par mois calendaire sur 1991-2020 des
  mesures mensuelles de cette série (12 valeurs, kWh/m²/j = HEP) ;
- la **séquence horaire satellite** : la série GHI horaire NASA de la localité,
  le brut au point (heure UTC = heure locale en Guinée).

Rien de calé ici : la séquence et la climatologie sortent brutes, le moteur cale
via le champ ``calage``, présent en ligne seulement. Aucun appel à kuma-calage
dans ce module.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from kuma_data_core.services.capsule.construire import EntreesRessource

# Période de référence des climatologies mensuelles du référentiel.
_CLIMATO_DEBUT = "1991-01-01"
_CLIMATO_FIN = "2020-12-31"


class PointHorsReferentielError(ValueError):
    """Le point ne se résout sur aucune localité, ou la localité n'a pas le brut."""


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class SourceCore:
    """Source d'acquisition adossée à une session du Core.

    ``annee_min`` / ``annee_max`` fenêtrent la séquence horaire (bornes UTC
    incluses). ``None`` prend toute la profondeur stockée : honnête mais lourd
    (25 ans ~ 219 000 points). L'appelant fixe le compromis.
    """

    session: Session
    annee_min: int | None = None
    annee_max: int | None = None

    def acquerir(self, latitude_deg: float, longitude_deg: float) -> EntreesRessource:
        localite = self._resoudre(latitude_deg, longitude_deg)
        climatologie, provenance_clim = self._climatologie_hep(localite["localite_id"])
        sequence, periode, provenance_seq = self._sequence_horaire(localite["localite_id"])
        temperatures, provenance_temp = self._extremes_temperature(localite["localite_id"])

        metadonnees = {
            "identite": {
                "nom": localite["nom"],
                "latitudeDeg": latitude_deg,
                "longitudeDeg": longitude_deg,
            },
            "edition": {
                "id": f"capsule-{localite['localite_code']}",
                "revisionSource": provenance_seq["code"],
            },
            # Les quatre series que le moteur exige a l'en-tete (audit E-7, hors
            # calcul) : la climatologie AU POINT vient du mensuel de la cellule,
            # la climatologie SOURCE et les deux sequences viennent de l'horaire
            # (la source est derivee de la sequence ; en v1 le contraignant EST
            # le type). La resolution reste en extra d'audit.
            "provenance": {
                "climatologieAuPoint": provenance_clim,
                "climatologieSource": provenance_seq,
                "sequenceType": provenance_seq,
                "sequenceContraignant": provenance_seq,
                "resolution": {
                    "localite": localite["localite_code"],
                    "serieReference": localite["serie_climatologie"],
                    "distanceKm": localite["distance_km"],
                    "memeCellule": localite["meme_cellule"],
                },
                # Present seulement quand les extremes sont servis (E-7 : une
                # serie embarquee cite sa provenance ; absente, pas de cle morte).
                **(
                    {"temperaturesConception": provenance_temp}
                    if provenance_temp is not None
                    else {}
                ),
            },
        }
        return EntreesRessource(
            metadonnees=metadonnees,
            periode=periode,
            domaine_validite=periode,
            climatologie_hep=climatologie,
            sequence=sequence,
            temperatures_conception=temperatures,
        )

    def _resoudre(self, lat: float, lon: float) -> dict[str, Any]:
        """Résout le point vers la localité qui échantillonne sa cellule."""
        rows = self.session.execute(
            text(
                """
                SELECT l.id, l.code, l.nom, l.latitude, l.longitude,
                       MIN(sm.code) AS serie_code
                FROM localites l
                JOIN series_metadonnees sm ON sm.localite_id = l.id
                WHERE l.actif AND l.latitude IS NOT NULL AND l.longitude IS NOT NULL
                  AND sm.actif AND sm.granularite = 'mensuel' AND sm.grandeur_code = 'ghi'
                  AND sm.periode_debut = :debut AND sm.periode_fin = :fin
                GROUP BY l.id, l.code, l.nom, l.latitude, l.longitude
                """
            ),
            {"debut": _CLIMATO_DEBUT, "fin": _CLIMATO_FIN},
        ).all()
        if not rows:
            raise PointHorsReferentielError("aucun point d'ingestion de climatologie GHI")

        cellule_lat, cellule_lon = math.floor(lat), math.floor(lon)
        meilleure: tuple[float, int] | None = None
        meme_cellule: tuple[float, int] | None = None
        for i, r in enumerate(rows):
            d = _haversine_km(lat, lon, float(r.latitude), float(r.longitude))
            if meilleure is None or d < meilleure[0]:
                meilleure = (d, i)
            dans_cellule = (
                math.floor(float(r.latitude)) == cellule_lat
                and math.floor(float(r.longitude)) == cellule_lon
            )
            if dans_cellule and (meme_cellule is None or d < meme_cellule[0]):
                meme_cellule = (d, i)

        assert meilleure is not None
        distance, i = meme_cellule if meme_cellule is not None else meilleure
        r = rows[i]
        return {
            "localite_id": int(r.id),
            "localite_code": str(r.code),
            "nom": str(r.nom),
            "serie_climatologie": str(r.serie_code),
            "distance_km": round(distance, 1),
            "meme_cellule": meme_cellule is not None,
        }

    def _climatologie_hep(self, localite_id: int) -> tuple[list[float], dict[str, Any]]:
        """Les 12 HEP mensuelles, moyenne par mois sur la mensuelle la plus profonde.

        La forme horaire est plafonnée à 25 ans (l'horaire NASA démarre en 2001),
        mais l'énergie mensuelle remonte à 1984 : on prend la série mensuelle NASA
        de plus grande profondeur de la localité (décision Siba 2026-08-17, pleine
        profondeur). La résolution reste, elle, sur la climatologie de référence
        1991-2020 (identification de la cellule).
        """
        meta = self.session.execute(
            text(
                """
                SELECT sm.code, sm.libelle, sm.methode_collecte,
                       sm.periode_debut, sm.periode_fin, s.code AS source_code, s.titre
                FROM series_metadonnees sm
                LEFT JOIN sources s ON s.id = sm.source_id
                WHERE sm.localite_id = :loc AND sm.grandeur_code = 'ghi'
                  AND sm.granularite = 'mensuel' AND sm.actif AND s.code = 'nasa_power'
                ORDER BY sm.periode_debut ASC, (sm.periode_fin - sm.periode_debut) DESC
                LIMIT 1
                """
            ),
            {"loc": localite_id},
        ).first()
        if meta is None:
            raise PointHorsReferentielError(
                f"pas de climatologie mensuelle NASA pour la localité {localite_id}"
            )
        rows = self.session.execute(
            text(
                """
                SELECT m.mois, avg(m.valeur) AS hep
                FROM mesures_ressource_mensuelles m
                JOIN series_metadonnees sm ON sm.id = m.serie_id
                WHERE sm.code = :code AND m.valide_au IS NULL AND m.statut <> 'deprecie'
                GROUP BY m.mois ORDER BY m.mois
                """
            ),
            {"code": meta.code},
        ).all()
        if len(rows) != 12:
            raise PointHorsReferentielError(
                f"climatologie {meta.code} incomplète : {len(rows)} mois sur 12"
            )
        provenance = {
            "code": meta.code,
            "libelle": meta.libelle,
            "methode": meta.methode_collecte,
            "source": meta.source_code,
            "sourceTitre": meta.titre,
            "periode": {
                "debut": meta.periode_debut.strftime("%Y-%m"),
                "fin": meta.periode_fin.strftime("%Y-%m"),
            },
        }
        return [float(r.hep) for r in rows], provenance

    def _extremes_temperature(
        self, localite_id: int
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Records de température au point : le plus froid des minima journaliers et
        le plus chaud des maxima journaliers, sur les séries ``t2m_min``/``t2m_max``.

        Bruts NASA, HORS calage : le calage corrige l'irradiance, pas la
        température. Rendus ``(None, None)`` tant que les séries ne sont pas
        seedées : la capsule omet alors le bloc et le dimensionnement des strings
        retombe sur une saisie manuelle côté application. Le record absolu est le
        cas ``percentile = 0`` (décision Siba 2026-08-18) ; un futur passage en
        P1/P99 ne changerait que l'agrégat, sans re-fetch.
        """
        row = self.session.execute(
            text(
                """
                SELECT
                    min(m.valeur) FILTER (WHERE sm.grandeur_code = 't2m_min') AS froid,
                    max(m.valeur) FILTER (WHERE sm.grandeur_code = 't2m_max') AS chaud,
                    min(sm.periode_debut) AS debut,
                    max(sm.periode_fin) AS fin,
                    min(s.code) AS source_code
                FROM mesures_ressource m
                JOIN series_metadonnees sm ON sm.id = m.serie_id
                LEFT JOIN sources s ON s.id = sm.source_id
                WHERE sm.localite_id = :loc
                  AND sm.grandeur_code IN ('t2m_min', 't2m_max')
                  AND sm.granularite = 'journalier' AND sm.actif
                  AND m.valide_au IS NULL AND m.statut <> 'deprecie'
                """
            ),
            {"loc": localite_id},
        ).first()
        if row is None or row.froid is None or row.chaud is None:
            return None, None

        fenetre = {
            "debut": row.debut.strftime("%Y-%m"),
            "fin": row.fin.strftime("%Y-%m"),
        }
        temperatures = {
            "froidC": round(float(row.froid), 2),
            "chaudC": round(float(row.chaud), 2),
            "fenetre": fenetre,
        }
        provenance = {
            "froid": "t2m_min",
            "chaud": "t2m_max",
            "source": row.source_code,
            "agregat": "record",
            "periode": fenetre,
        }
        return temperatures, provenance

    def _sequence_horaire(
        self, localite_id: int
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Séquence GHI horaire satellite de la localité : (séquence, période, provenance)."""
        meta = self.session.execute(
            text(
                """
                SELECT sm.code, sm.libelle, sm.methode_collecte,
                       sm.periode_debut, sm.periode_fin, s.code AS source_code, s.titre
                FROM series_metadonnees sm
                LEFT JOIN sources s ON s.id = sm.source_id
                WHERE sm.localite_id = :loc AND sm.grandeur_code = 'ghi'
                  AND sm.granularite = 'horaire' AND sm.actif
                  AND sm.methode_collecte = 'modele_satellitaire'
                ORDER BY sm.periode_fin DESC
                LIMIT 1
                """
            ),
            {"loc": localite_id},
        ).first()
        if meta is None:
            raise PointHorsReferentielError(
                f"pas de série GHI horaire satellite pour la localité {localite_id}"
            )

        clauses = [
            "sm.code = :code",
            "mh.statut = 'valide_auto'",
            "mh.valide_au IS NULL",
        ]
        params: dict[str, object] = {"code": meta.code}
        if self.annee_min is not None:
            clauses.append("extract(year from mh.instant_mesure at time zone 'UTC') >= :amin")
            params["amin"] = self.annee_min
        if self.annee_max is not None:
            clauses.append("extract(year from mh.instant_mesure at time zone 'UTC') <= :amax")
            params["amax"] = self.annee_max
        where = " AND ".join(clauses)

        rows = self.session.execute(
            text(
                f"""
                SELECT extract(month from mh.instant_mesure at time zone 'UTC')::int AS mois,
                       extract(hour from mh.instant_mesure at time zone 'UTC')::int AS heure,
                       mh.valeur
                FROM mesures_ressource_horaires mh
                JOIN series_metadonnees sm ON sm.id = mh.serie_id
                WHERE {where}
                ORDER BY mh.instant_mesure
                """
            ),
            params,
        ).all()
        if not rows:
            raise PointHorsReferentielError(f"série {meta.code} sans point horaire validé")

        sequence = {
            "mois": [int(r.mois) for r in rows],
            "heures": [int(r.heure) for r in rows],
            "ghi": [float(r.valeur) for r in rows],
        }
        # La période reflète la fenêtre réellement servie, pas la série entière.
        debut = (
            f"{self.annee_min}-01"
            if self.annee_min is not None
            else meta.periode_debut.strftime("%Y-%m")
        )
        fin = (
            f"{self.annee_max}-12"
            if self.annee_max is not None
            else meta.periode_fin.strftime("%Y-%m")
        )
        periode = {"debut": debut, "fin": fin}
        provenance = {
            "code": meta.code,
            "libelle": meta.libelle,
            "methode": meta.methode_collecte,
            "source": meta.source_code,
            "sourceTitre": meta.titre,
            "periode": periode,
        }
        return sequence, periode, provenance
