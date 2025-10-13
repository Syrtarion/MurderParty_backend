"""
Models / event.py
Rôle:
- Définir le modèle d'événement standard échangé dans l'app (timeline, WS, logs).

Notes:
- `type` restreint à un jeu de valeurs (Literal) pour éviter les fautes de frappe.
- `payload` est libre (clé/valeur) afin d’embarquer le contexte spécifique.
- `timestamp` par défaut en UTC (datetime naïf depuis `datetime.utcnow()`).
"""
from pydantic import BaseModel
from typing import Literal, Optional, Dict, Any
from datetime import datetime

# Typage strict des catégories d'événements supportées par l'app
EventType = Literal["indice_activated", "indice_found", "mini_game_result", "narration", "system"]

class Event(BaseModel):
    """Représente une entrée dans la timeline/les logs et pour la diffusion WS."""
    id: str  # identifiant unique (généré côté service/route appelante)
    type: EventType  # catégorie d'événement (contrainte par `EventType` ci-dessus)
    payload: Dict[str, Any] = {}  # contenu libre selon l’événement (ex: winners, clue, etc.)
    timestamp: datetime = datetime.utcnow()  # moment de création (UTC)
