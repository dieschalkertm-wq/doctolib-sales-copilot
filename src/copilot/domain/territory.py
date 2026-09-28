"""Vertriebsgebiet (config/territory.yaml): Regionen, Orte, Auflösung von Ort/PLZ -> Region."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from copilot.config import load_yaml
from copilot.domain.geo import GeoPoint
from copilot.domain.models import Practice
from copilot.domain.normalize import fold
from copilot.errors import ConfigError


class Region(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    name: str
    plz_prefixes: list[str] = Field(default_factory=list)


class Place(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    region: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    aliases: list[str] = Field(default_factory=list)
    uncertainty_km: float | None = Field(default=None, ge=0)   # überschreibt geo.place_uncertainty_km


@dataclass(frozen=True)
class Resolution:
    region: str | None
    place: Place | None


@dataclass(frozen=True)
class Scope:
    """Ergebnis von Territory.parse_scope: entweder ein Ort oder eine ganze Region."""
    kind: str  # "place" | "region"
    place: Place | None = None
    region: Region | None = None

    @property
    def label(self) -> str:
        return self.place.name if self.place else self.region.name  # type: ignore[union-attr]


class Territory:
    def __init__(self, regions: list[Region], places: list[Place], place_uncertainty_km: float = 5.0):
        self.regions = {r.key: r for r in regions}
        self.places = places
        self.default_place_uncertainty_km = place_uncertainty_km
        for p in places:
            if p.region not in self.regions:
                raise ConfigError(f"territory: Ort mit unbekannter Region '{p.region}'", code="config_invalid")
        self._by_name: dict[str, Place] = {}
        for p in places:
            for label in [p.name, *p.aliases]:
                self._by_name[fold(label)] = p
        # "Neunkirchen/Saar" wird auch als "Neunkirchen" gefunden (Alias) – Kollisionen sind Konfig-Sache.

    @classmethod
    def load(cls, config_dir: Path) -> "Territory":
        data = load_yaml(config_dir / "territory.yaml") or {}
        try:
            return cls([Region(**r) for r in data.get("regions", [])], [Place(**p) for p in data.get("places", [])],
                       float((data.get("geo") or {}).get("place_uncertainty_km", 5.0)))
        except (ValidationError, TypeError) as exc:
            raise ConfigError("territory.yaml ungültig", code="config_invalid") from exc

    def place_uncertainty_km(self, place: Place) -> float:
        return place.uncertainty_km if place.uncertainty_km is not None else self.default_place_uncertainty_km

    def place_center(self, place: Place) -> GeoPoint:
        """Suchzentrum 'um Ort X': der Ortsmittelpunkt ist per Definition der Mittelpunkt (Unsicherheit 0)."""
        return GeoPoint(place.lat, place.lon, 0.0, "definition")

    def point_for(self, practice: Practice) -> GeoPoint | None:
        """Position einer Praxis samt Unsicherheit; None, wenn keine Geodaten vorliegen (nie raten)."""
        if practice.lat is None or practice.lon is None:
            return None
        if practice.geo_precision is not None and practice.geo_precision.value == "exact":
            return GeoPoint(practice.lat, practice.lon, 0.0, "exact")
        place = self.find_place(practice.ort)
        uncertainty = self.place_uncertainty_km(place) if place else self.default_place_uncertainty_km
        return GeoPoint(practice.lat, practice.lon, uncertainty, "place")

    def find_place(self, ort: str | None) -> Place | None:
        return self._by_name.get(fold(ort)) if ort else None

    def resolve(self, ort: str | None, plz: str | None = None) -> Resolution:
        place = self.find_place(ort)
        if place:
            return Resolution(place.region, place)
        if plz:
            for region in self.regions.values():
                if any(plz.startswith(prefix) for prefix in region.plz_prefixes):
                    return Resolution(region.key, None)
        return Resolution(None, None)

    def parse_scope(self, text: str) -> Scope | None:
        key = fold(text)
        place = self._by_name.get(key)
        if place:
            return Scope("place", place=place)
        for region in self.regions.values():
            if fold(region.name) == key or fold(region.key) == key:
                return Scope("region", region=region)
        return None
