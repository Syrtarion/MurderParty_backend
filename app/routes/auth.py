"""

Module routes/auth.py

RÃƒÂ´le:

- GÃƒÂ¨re l'inscription et la connexion des joueurs.

- Attribue automatiquement un personnage ÃƒÂ  l'inscription.

  (Ã¢ÂšÂ Ã¯Â¸Â Les enveloppes sont dÃƒÂ©sormais distribuÃƒÂ©es aprÃƒÂ¨s le verrouillage des inscriptions

   via /master/lock_join et le service dÃƒÂ©diÃƒÂ©, pour une rÃƒÂ©partition ÃƒÂ©quitable.)

IntÃƒÂ©grations:

- `GAME_STATE`: crÃƒÂ©ation des joueurs, log d'ÃƒÂ©vÃƒÂ©nements, persistance.

    2) Attribution d'un personnage différée : réalisée lors de /party/roles_assign.

- Hash de mot de passe: `bcrypt` si dispo, sinon fallback PBKDF2 (sÃƒÂ©curisÃƒÂ©).

SÃƒÂ©curitÃƒÂ©:

- Stocke `password_hash` cÃƒÂ´tÃƒÂ© joueur.

- `login` vÃƒÂ©rifie les credentials via `verify_password`.

Garde-fous:

- Inscription conditionnÃƒÂ©e par `GAME_STATE.state["join_locked"]` (fermÃƒÂ©e par dÃƒÂ©faut).

- UnicitÃƒÂ© du `display_name` (insensible ÃƒÂ  la casse / espaces).

"""

# app/routes/auth.py
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, Dict, Any, Tuple

from app.services.game_state import GameState
from app.services.session_store import (
    DEFAULT_SESSION_ID,
    find_session_by_player_id,
    find_session_by_player_name,
    find_session_id_by_join_code,
    get_session_state,
)

# --- bcrypt optionnel (fallback si absent) ---

try:

    import bcrypt  # type: ignore

    def hash_password(pw: str) -> str:

        return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    def verify_password(plain: str, hashed: str) -> bool:

        try:

            return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))

        except Exception:

            return False

except Exception:

    # Fallback PBKDF2 robuste si `bcrypt` indisponible

    import os, hashlib, base64, hmac

    def _pbkdf2_hash(pw: str, salt: bytes | None = None, iters: int = 200_000) -> str:

        salt = salt or os.urandom(16)

        dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, iters)

        return "pbkdf2$%d$%s$%s" % (

            iters,

            base64.b64encode(salt).decode("ascii"),

            base64.b64encode(dk).decode("ascii"),

        )

    def hash_password(pw: str) -> str:

        return _pbkdf2_hash(pw)

    def verify_password(plain: str, hashed: str) -> bool:

        """

        VÃƒÂ©rifie un hash au format "pbkdf2$<iters>$<salt_b64>$<hash_b64>"

        en comparant avec un dÃƒÂ©rivÃƒÂ© recalculÃƒÂ© via HMAC-SHA256.

        """

        try:

            parts = hashed.split("$")

            if parts[0] != "pbkdf2" or len(parts) != 4:

                return False

            iters = int(parts[1])

            salt = base64.b64decode(parts[2].encode("ascii"))

            expected = base64.b64decode(parts[3].encode("ascii"))

            dk = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, iters)

            return hmac.compare_digest(dk, expected)

        except Exception:

            return False

router = APIRouter(prefix="/auth", tags=["auth"])

def _resolve_session(session_id: Optional[str], join_code: Optional[str]) -> Tuple[str, GameState]:
    sid = (session_id or "").strip()
    if sid:
        return sid, get_session_state(sid)
    resolved = find_session_id_by_join_code(join_code)
    if join_code and not resolved:
        raise HTTPException(status_code=404, detail="session_not_found")
    sid = resolved or DEFAULT_SESSION_ID
    return sid, get_session_state(sid)

def _find_player_by_name(name: str, state: GameState) -> Optional[Dict[str, Any]]:
    name_norm = name.strip().lower()
    for player in state.players.values():
        if str(player.get("display_name", "")).strip().lower() == name_norm:
            return player
    return None

# ---------- ModÃƒÂ¨les ----------

class RegisterIn(BaseModel):

    name: str

    password: str

class LoginIn(BaseModel):

    name: str

    password: str

class AuthOut(BaseModel):

    player_id: str

    name: str

    character_id: Optional[str] = None

    session_id: Optional[str] = None

# ---------- Helpers ----------

# ---------- Routes ----------

@router.post("/register", response_model=AuthOut)

def register(
    data: RegisterIn,
    session_id: str | None = Query(default=None, description="Identifiant de session"),
    join_code: str | None = Query(default=None, description="Code de session partagÃ©"),
):
    """
    Inscription dâ€™un joueur (si inscriptions ouvertes).
    Ã‰tapes:
    1) Ajout joueur via `GameState.add_player` + hash du mot de passe.
    2) Personnage attribué plus tard via /party/roles_assign.
    3) Log + persist via `state.save()`.

    âš ï¸ Changement de rÃ¨gle (Ã©quitÃ©) :
       âžœ PAS dâ€™attribution dâ€™enveloppes ici.
       âžœ Les enveloppes sont distribuÃ©es Ã©quitablement APRÃˆS le verrouillage des inscriptions
         via /master/lock_join (service envelopes).
    """
    sid, state = _resolve_session(session_id, join_code)

    join_locked = bool(state.state.get("join_locked", False))
    if join_locked:
        raise HTTPException(403, "Registration is closed.")

    name = data.name.strip()
    if not name:
        raise HTTPException(400, "Missing name.")

    if _find_player_by_name(name, state):
        raise HTTPException(409, "Name already taken.")

    pid = state.add_player(display_name=name)
    player = state.players[pid]
    player["password_hash"] = hash_password(data.password)

    character = None  # attribué plus tard via /party/roles_assign
    
    state.save()
    state.log_event(
        "player_register",
        {
            "player_id": pid,
            "display_name": name,
            "character": None,
            "session_id": sid,
        },
    )

    return AuthOut(
        player_id=pid,
        name=player.get("display_name", name),
        character_id=player.get("character_id"),
        session_id=sid,
    )

@router.post("/login", response_model=AuthOut)

def login(
    data: LoginIn,
    session_id: str | None = Query(default=None, description="Identifiant de session"),
    join_code: str | None = Query(default=None, description="Code de session partagÃ©"),
):
    """
    Connexion dâ€™un joueur par nom + mot de passe.
    - 404 si joueur inconnu.
    - 401 si mot de passe invalide.
    - Retourne `player_id`, `name` (display_name) et `character_id` si existante.
    """
    name = data.name.strip()
    if not name:
        raise HTTPException(400, "Missing name.")

    sid, state = _resolve_session(session_id, join_code)
    player = _find_player_by_name(name, state)

    if not player and not session_id and not join_code:
        found = find_session_by_player_name(name)
        if found:
            sid, state, player = found

    if not player:
        raise HTTPException(404, "Player not found.")

    hashed = player.get("password_hash")
    if not (isinstance(hashed, str) and verify_password(data.password, hashed)):
        raise HTTPException(401, "Invalid credentials.")

    return AuthOut(
        player_id=player["player_id"],
        name=player.get("display_name", name),
        character_id=player.get("character_id"),
        session_id=sid,
    )

@router.get("/me", response_model=AuthOut)

def me(
    player_id: str,
    session_id: str | None = Query(default=None, description="Identifiant de session"),
):
    """
    RÃ©cupÃ©ration du profil joueur minimal (pour hydrater le front).
    - Le front appelle /auth/me?player_id=...
    - Renvoie name (display_name) & character_id.
    - Les enveloppes (vue {num,id}) sont dans GameState.players[pid]["envelopes"] si besoin cÃ´tÃ© /game/state.
    """
    sid = (session_id or "").strip()
    state: Optional[GameState] = None
    player: Optional[Dict[str, Any]] = None

    if sid:
        state = get_session_state(sid)
        player = state.players.get(player_id)

    if player is None:
        found = find_session_by_player_id(player_id)
        if found:
            sid, state = found
            player = state.players.get(player_id) if state else None

    if not player:
        raise HTTPException(404, "Player not found.")

    return AuthOut(
        player_id=player["player_id"],
        name=player.get("display_name", ""),
        character_id=player.get("character_id"),
        session_id=sid or DEFAULT_SESSION_ID,
    )
