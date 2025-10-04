from pydantic import BaseModel
from typing import Literal, Optional, Dict, Any
from datetime import datetime

EventType = Literal["indice_activated", "indice_found", "mini_game_result", "narration", "system"]

class Event(BaseModel):
    id: str
    type: EventType
    payload: Dict[str, Any] = {}
    timestamp: datetime = datetime.utcnow()
