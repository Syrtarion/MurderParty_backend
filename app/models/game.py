from pydantic import BaseModel, Field
from typing import Dict, List, Optional

class GameState(BaseModel):
    started: bool = False
    culprit_id: Optional[str] = None
    step: str = "intro"  # intro -> mid -> end
    players: Dict[str, dict] = Field(default_factory=dict)
    activated_indices: List[str] = Field(default_factory=list)
    history: List[dict] = Field(default_factory=list)
