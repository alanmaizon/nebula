from __future__ import annotations

from pydantic import BaseModel, Field


class IntakePayload(BaseModel):
    country: str = Field(default="Ireland", min_length=2, max_length=80)
    organization_type: str = Field(default="Non-profit", min_length=2, max_length=120)
    charity_registered: bool = False
    tax_registered: bool = False
    has_group_bank_account: bool = False
    funder_track: str = Field(default="community-foundation", min_length=2, max_length=80)
    funding_goal: str = Field(default="project", min_length=2, max_length=80)
    sector_focus: str = Field(default="general", min_length=2, max_length=120)
    timeline_quarters: int = Field(default=4, ge=1, le=12)
    has_evidence_data: bool = False


class TemplateRecommendation(BaseModel):
    template_key: str = Field(..., min_length=2)
    template_name: str = Field(..., min_length=2)
    rationale: list[str] = Field(default_factory=list)
    required_checklist: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def recommend_template(intake: IntakePayload) -> TemplateRecommendation:
    track = intake.funder_track.strip().lower()
    sector = intake.sector_focus.strip().lower()
    goal = intake.funding_goal.strip().lower()

    template_key = "irish_project_grant"
    template_name = "Irish Project Grant (General)"
    rationale = [
        "Prioritizes evidence-backed need and measurable outcomes.",
        "Aligns with common Ireland grant portal submission patterns.",
    ]

    if "community" in track:
        template_key = "cfi_project_grant"
        template_name = "Community Foundation Ireland - Project Grant"
        rationale.insert(0, "Funder track indicates Community Foundation workflow and portal-based submission.")
    elif "eu" in track:
        template_key = "eu_programme_grant"
        template_name = "EU Programme Grant (Ireland Applicant)"
        rationale.insert(0, "Funder track indicates EU opportunity with stronger compliance/timeline detail.")
    elif "government" in track or "county" in track or "dfa" in track:
        template_key = "irish_public_sector_grant"
        template_name = "Irish Government / Local Authority Grant"
        rationale.insert(0, "Funder track indicates public-sector requirements and strict eligibility checks.")

    if "heritage" in sector:
        template_key = "irish_heritage_grant"
        template_name = "Irish Heritage Funding Application"
        rationale.insert(0, "Sector focus is heritage-specific and benefits from dedicated attachment structure.")
    elif "rural" in sector:
        template_key = "irish_rural_development_grant"
        template_name = "Irish Rural Development Grant"
        rationale.insert(0, "Sector focus is rural development with timeline and delivery milestones.")

    if "core" in goal:
        rationale.append("Funding goal is core support, so narrative balance shifts toward organizational capacity.")
    else:
        rationale.append("Funding goal is project delivery, so template emphasizes activities, milestones, and outcomes.")

    required_checklist = [
        "Formal establishment and governing constitution available",
        "Organization bank account in group name",
        "Tax registration details available",
        "Evidence dataset ready for need statement",
        "Quarter-by-quarter implementation timeline",
    ]
    warnings: list[str] = []
    if not intake.charity_registered:
        warnings.append("Charity registration is not confirmed; verify Charities Act applicability before submission.")
    if not intake.tax_registered:
        warnings.append("Tax registration is not confirmed; many funders require Revenue reference details.")
    if not intake.has_group_bank_account:
        warnings.append("Group bank account is not confirmed; most grant disbursement requires this.")
    if not intake.has_evidence_data:
        warnings.append("No evidence dataset indicated; strengthen need statement with quantitative baseline data.")

    return TemplateRecommendation(
        template_key=template_key,
        template_name=template_name,
        rationale=rationale,
        required_checklist=required_checklist,
        warnings=warnings,
    )
