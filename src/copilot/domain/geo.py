"""Geo-Logik mit ehrlicher Genauigkeit: Jeder Punkt trägt seine Unsicherheit, Radiusprüfungen sind dreiwertig."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import asin, cos, radians, sin, sqrt


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 6371.0088 * 2 * asin(sqrt(a))


class Certainty(str, Enum):
    INSIDE = "inside"      # auch im ungünstigsten Fall innerhalb
    POSSIBLE = "possible"  # je nach tatsächlichem Standort innerhalb oder außerhalb
    OUTSIDE = "outside"    # auch im günstigsten Fall außerhalb

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lon: float
    uncertainty_km: float = 0.0   # 0 = exakt bzw. per Definition (z. B. Suchzentrum "Ortsmittelpunkt")
    precision: str = "exact"      # exact | place | definition

    def distance_km(self, other: "GeoPoint") -> float:
        return haversine_km(self.lat, self.lon, other.lat, other.lon)


def classify(center: GeoPoint, point: GeoPoint, radius_km: float) -> tuple[Certainty, float, float]:
    """(Sicherheit, Distanz der Näherungspunkte, kombinierte Unsicherheit). Unsicherheiten addieren sich (Worst Case)."""
    distance = center.distance_km(point)
    uncertainty = center.uncertainty_km + point.uncertainty_km
    if distance + uncertainty <= radius_km:
        return Certainty.INSIDE, distance, uncertainty
    if distance - uncertainty > radius_km:
        return Certainty.OUTSIDE, distance, uncertainty
    return Certainty.POSSIBLE, distance, uncertainty


def format_distance(distance_km: float, uncertainty_km: float) -> str:
    """Keine falsche Präzision: Näherungen werden als solche ausgegeben."""
    if uncertainty_km <= 0:
        return f"{distance_km:.1f} km"
    if distance_km < 0.5:   # gleicher Näherungspunkt: keine Distanz behaupten
        return f"gleicher Ortsmittelpunkt (Position ±{uncertainty_km:g} km)"
    return f"≈{distance_km:.0f} km (±{uncertainty_km:g} km)"
