from __future__ import annotations

from pydantic import BaseModel, Field


class IntakePayload(BaseModel):
    country: str = Field(default="Ireland", min_length=2, max_length=80)
    organization_type: str = Field(default="Non-profit", min_length=2, max_length=120)
    funder_track: str = Field(default="community-foundation", min_length=2, max_length=80)
    funding_goal: str = Field(default="project", min_length=2, max_length=80)
    sector_focus: str = Field(default="general", min_length=2, max_length=120)


def build_intake_context(intake: IntakePayload) -> dict[str, str]:
    return {
        "country": intake.country.strip(),
        "organization_type": intake.organization_type.strip(),
        "funder_track": intake.funder_track.strip(),
        "funding_goal": intake.funding_goal.strip(),
        "sector_focus": intake.sector_focus.strip(),
    }
