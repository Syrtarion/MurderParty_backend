from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class StorySeedLLMDirectives(BaseModel):
    language: str = "fr"
    tone: Optional[str] = None
    constraints: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")


class StorySeedTimingPolicy(BaseModel):
    target_total_minutes: Optional[int] = None
    llm_interlude_picker: bool = False
    must_confirm_on_tablet: bool = True

    model_config = ConfigDict(extra="allow")


class StorySeedMeta(BaseModel):
    version: str = "2.0"
    title: Optional[str] = None
    estimated_duration_minutes: Optional[int] = None
    players_min: Optional[int] = None
    players_max: Optional[int] = None
    llm_directives: StorySeedLLMDirectives = Field(default_factory=StorySeedLLMDirectives)
    timing_policy: StorySeedTimingPolicy = Field(default_factory=StorySeedTimingPolicy)

    model_config = ConfigDict(extra="allow")


class StorySeedRoundNarration(BaseModel):
    intro_seed: Optional[str] = None
    outro_seed: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class StorySeedHintSharingRules(BaseModel):
    discoverer_major_others: Optional[str] = None
    discoverer_vague_others: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class StorySeedHintPolicy(BaseModel):
    tiers: List[str] = Field(default_factory=lambda: ["major", "minor", "vague", "misleading"])
    sharing_rules: StorySeedHintSharingRules = Field(default_factory=StorySeedHintSharingRules)

    model_config = ConfigDict(extra="allow")


class StorySeedRoundLLM(BaseModel):
    difficulty: Optional[str] = None
    must_be_solvable: bool = True
    hint_policy: StorySeedHintPolicy = Field(default_factory=StorySeedHintPolicy)

    model_config = ConfigDict(extra="allow")


class StorySeedRound(BaseModel):
    id: Optional[int] = None
    code: Optional[str] = None
    kind: Optional[str] = None
    mode: Optional[str] = None
    theme: Optional[str] = None
    max_seconds: Optional[int] = None
    narration: StorySeedRoundNarration = Field(default_factory=StorySeedRoundNarration)
    llm: StorySeedRoundLLM = Field(default_factory=StorySeedRoundLLM)

    model_config = ConfigDict(extra="allow")


class StorySeedRules(BaseModel):
    killer: Dict[str, Any] = Field(default_factory=lambda: {"destroy_quota": 2})
    scoring: Dict[str, Any] = Field(default_factory=lambda: {"win_bonus": 1, "wrong_penalty": 0})

    model_config = ConfigDict(extra="allow")


class StorySeed(BaseModel):
    meta: StorySeedMeta = Field(default_factory=StorySeedMeta)
    setting: Dict[str, Any] = Field(default_factory=dict)
    characters: List[Dict[str, Any]] = Field(default_factory=list)
    missions: List[Dict[str, Any]] = Field(default_factory=list)
    culprit_missions: List[Dict[str, Any]] = Field(default_factory=list)
    envelopes: List[Dict[str, Any]] = Field(default_factory=list)
    canon_constraints: Dict[str, Any] = Field(default_factory=dict)
    rules: StorySeedRules = Field(default_factory=StorySeedRules)
    rounds: List[StorySeedRound] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")

    def to_dict(self) -> Dict[str, Any]:
        """Dump the story seed as a standard Python dict (deep copy)."""
        return self.model_dump(mode="python", round_trip=True)
