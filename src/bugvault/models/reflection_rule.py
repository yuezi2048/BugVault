"""Pydantic model for a single bug-prevention rule written to CLAUDE.md."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PreventionRule(BaseModel):
    """A single prevention rule entry stored in CLAUDE.md."""

    rule_number: int = Field(..., description="Sequential rule number")
    error_category: str = Field(
        ...,
        description=(
            "Classification: understanding_bias, code_logic_error, "
            "api_misuse, environment_issue, or other"
        ),
    )
    preventive_rule: str = Field(..., description="Concise actionable rule")
    reflection_text: str = Field(..., description="Detailed analysis of the bug")
    created_at: str = Field(..., description="ISO-8601 UTC timestamp")