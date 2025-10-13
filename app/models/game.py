"""
Models / game.py
Rôle:
- Définir un snapshot léger et typé de l'état global de la partie (côté modèles Pydantic).
- Ce modèle peut être utilisé pour sérialiser des réponses API ou stocker des états intermédiaires.

Champs:
- started: drapeau de démarrage de partie.
- culprit_id: identifiant du joueur coupable (s’il est déjà déterminé).
- step: étape macroscopique de narration (intro → mid → end).
- players: dictionnaire {player_id: {...}} (structure libre côté runtime).
- activated_indices: liste d’IDs d’indices déjà “activés” (ex: révélés).
- history: liste d’entrées libres pour tracer l’historique haut niveau.
"""
from pydantic import BaseModel, Field
from typing import Dict, List, Optional

class GameState(BaseModel):
    """Modèle d'état de jeu minimaliste pour échanges/stockage (Pydantic)."""
    started: bool = False  # True une fois la partie officiellement lancée
    culprit_id: Optional[str] = None  # player_id du coupable choisi (si disponible)
    step: str = "intro"  # étape macro: "intro" -> "mid" -> "end" (guidage UI)
    players: Dict[str, dict] = Field(default_factory=dict)  # profil joueurs à granularité libre
    activated_indices: List[str] = Field(default_factory=list)  # IDs d’indices “activés”
    history: List[dict] = Field(default_factory=list)  # traces libres (événements macro)
