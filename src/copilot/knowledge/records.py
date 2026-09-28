"""Kanonische Eingabe-Records: Alle Datenquellen-Adapter (CSV heute, CRM/Registries später) liefern dieses Format."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from copilot.domain.normalize import normalize_url


class DoctorRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    full_name: str = Field(min_length=1, max_length=200)
    title: str | None = Field(default=None, max_length=60)


class PracticeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    street: str | None = Field(default=None, max_length=200)
    plz: str | None = Field(default=None, pattern=r"^\d{5}$")
    ort: str | None = Field(default=None, max_length=120)
    specialty_labels: list[str] = Field(default_factory=list)  # Rohbezeichnungen, werden gegen den Katalog aufgelöst
    website: str | None = None
    doctors: list[DoctorRecord] = Field(default_factory=list)
    lat: float | None = Field(default=None, ge=-90, le=90)     # nur setzen, wenn die Quelle EXAKTE Koordinaten liefert
    lon: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def _geo_pair(self) -> "PracticeRecord":
        if (self.lat is None) != (self.lon is None):
            raise ValueError("lat and lon must be set together")
        return self

    @field_validator("website")
    @classmethod
    def _website(cls, v: str | None) -> str | None:
        return normalize_url(v)
