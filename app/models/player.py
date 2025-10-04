from pydantic import BaseModel, Field
from typing import List

class Player(BaseModel):
    id: str
    name: str
    role_id: str | None = None
    indices: List[str] = Field(default_factory=list)  # liste d'IDs d'indices
