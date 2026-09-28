"""Scoring-Konfiguration (config/scoring.yaml). Bewusst kein KI-Scoring: feste, erklärbare Regeln."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from copilot.config import load_yaml
from copilot.domain.enums import ProspectStage
from copilot.errors import ConfigError


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SpecialtyFit(_M):
    default: float = 5
    overrides: dict[str, float] = Field(default_factory=dict)


class PracticeSize(_M):
    two_doctors: float = 3
    three_or_more: float = 6


class ReferralProximity(_M):
    observed: float = 20
    manual: float = 15
    derived: float = 8


class Exclusions(_M):
    customers: bool = True
    already_doctolib_recognised: bool = True
    prospect_stages: list[ProspectStage] = Field(default_factory=lambda: [ProspectStage.WON, ProspectStage.LOST, ProspectStage.PARKED])


class ScoringConfig(_M):
    specialty_fit: SpecialtyFit = SpecialtyFit()
    practice_size: PracticeSize = PracticeSize()
    referral_proximity: ReferralProximity = ReferralProximity()
    competitor_booking_signal: float = 4
    exclude: Exclusions = Exclusions()

    @classmethod
    def load(cls, config_dir: Path) -> "ScoringConfig":
        try:
            return cls.model_validate(load_yaml(config_dir / "scoring.yaml") or {})
        except ValidationError as exc:
            raise ConfigError(f"scoring.yaml ungültig: {exc.error_count()} Fehler", code="config_invalid") from exc
