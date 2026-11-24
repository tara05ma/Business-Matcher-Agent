"""The agent's final answer for one document.

Every run ends in a MatchResult. Pydantic checks it when it is created, so an
answer that contradicts itself (for example "matched" with no dos_id) raises a
ValidationError instead of reaching the user.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DosId = str  # digits only, checked by the pattern on each field


class MatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a misspelled field name is an error

    status: Literal["matched", "unmatched"] = Field(
        description="'matched' only when sure; otherwise 'unmatched'.")
    dos_id: DosId | None = Field(
        default=None, pattern=r"^\d{1,12}$",
        description="The matched company's DOS ID. Empty when unmatched.")
    matched_name: str | None = Field(
        default=None, description="The register name of the matched company.")
    confidence: float = Field(
        ge=0.0, le=1.0, description="How sure the agent is, from 0 to 1.")
    candidates_considered: list[DosId] = Field(
        default_factory=list,
        description="DOS IDs of the companies the agent compared, best first. "
                    "Listed even when unmatched, so a person can pick quickly.")
    evidence: str = Field(
        min_length=1, description="Why the agent decided this, in plain words.")
    model_used: str = Field(description="The Claude model that made the decision.")
    steps_taken: int = Field(ge=0, description="How many steps the agent took.")

    @model_validator(mode="after")
    def _answer_is_consistent(self) -> "MatchResult":
        if any(not c.isdigit() for c in self.candidates_considered):
            raise ValueError("candidates_considered must hold DOS IDs (digits only)")
        if self.status == "matched":
            if not self.dos_id or not self.matched_name:
                raise ValueError("a match needs both dos_id and matched_name")
            if self.dos_id not in self.candidates_considered:
                raise ValueError("the matched dos_id must be one of candidates_considered")
        else:
            if self.dos_id or self.matched_name:
                raise ValueError("an unmatched result must leave dos_id and matched_name empty")
        return self
