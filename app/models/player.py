"""
Models / player.py
Rôle:
- Définir la structure minimale d’un joueur (côté modèles Pydantic).

Champs:
- id: identifiant unique du joueur.
- name: nom d’affichage.
- role_id: identifiant éventuel du personnage attribué.
- indices: collection d’IDs d’indices associés à ce joueur (inventaire léger).
"""
from pydantic import BaseModel, Field
from typing import List

class Player(BaseModel):
    """Profil joueur minimal pour sérialisation/validation côté API."""
    id: str  # player_id unique
    name: str  # nom affiché (saisit à l’inscription)
    role_id: str | None = None  # personnage attribué (ou None si pas encore assigné)
    indices: List[str] = Field(default_factory=list)  # liste d'IDs d'indices en possession du joueur
