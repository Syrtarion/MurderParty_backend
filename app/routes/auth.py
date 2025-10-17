"""
Module routes/auth.py
Rôle:
- Gère l'inscription et la connexion des joueurs.
- Attribue automatiquement un personnage à l'inscription.
  (⚠️ Les enveloppes sont désormais distribuées après le verrouillage des inscriptions
   via /master/lock_join et le service dédié, pour une répartition équitable.)

Intégrations:
- `GAME_STATE`: création des joueurs, log d'événements, persistance.
- `CHARACTERS`: attribution des personnages via story_seed.
- Hash de mot de passe: `bcrypt` si dispo, sinon fallback PBKDF2 (sécurisé).

Sécurité:
- Stocke `password_hash` côté joueur.
- `login` vérifie les credentials via `verify_password`.

Garde-fous:
- Inscription conditionnée par `GAME_STATE.state["join_locked"]` (fermée par défaut).
- Unicité du `display_name` (insensible à la casse / espaces).
"""
# app/routes/auth.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any

from app.services.character_service import CHARACTERS
from app.services.game_state import GAME_STATE

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
        Vérifie un hash au format "pbkdf2$<iters>$<salt_b64>$<hash_b64>"
        en comparant avec un dérivé recalculé via HMAC-SHA256.
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

# ---------- Modèles ----------
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


# ---------- Helpers ----------
def _find_player_by_name(name: str) -> Optional[Dict[str, Any]]:
    """
    Recherche d’un joueur par `display_name` (normalisé en lower/strip).
    Retourne le dict joueur si trouvé, sinon None.
    """
    name_norm = name.strip().lower()
    for p in GAME_STATE.players.values():
        if str(p.get("display_name", "")).strip().lower() == name_norm:
            return p
    return None


# ---------- Routes ----------
@router.post("/register", response_model=AuthOut)
def register(data: RegisterIn):
    """
    Inscription d’un joueur (si inscriptions ouvertes).
    Étapes:
    1) Ajout joueur via `GAME_STATE.add_player` + hash du mot de passe.
    2) Attribution d’un personnage (CHARACTERS.assign_character).
    3) Log + persist via `GAME_STATE.save()`.

    ⚠️ Changement de règle (équité) :
       ➜ PAS d’attribution d’enveloppes ici.
       ➜ Les enveloppes sont distribuées équitablement APRÈS le verrouillage des inscriptions
         via /master/lock_join (service envelopes).
    """
    # Autorisé uniquement si les inscriptions sont ouvertes
    # FIX: par défaut les inscriptions sont OUVERTES (False), et le MJ les verrouille ensuite
    join_locked = bool(GAME_STATE.state.get("join_locked", False))  # FIX
    if join_locked:
        raise HTTPException(403, "Registration is closed.")

    name = data.name.strip()
    if not name:
        raise HTTPException(400, "Missing name.")

    # nom unique
    if _find_player_by_name(name):
        raise HTTPException(409, "Name already taken.")

    # 1) créer le joueur (via le flow GAME_STATE existant)
    pid = GAME_STATE.add_player(display_name=name)
    p = GAME_STATE.players[pid]
    p["password_hash"] = hash_password(data.password)

    # 2) attribuer un personnage depuis story_seed (via service)
    character = CHARACTERS.assign_character(pid)
    if character:
        p["character"] = character.get("name")
        p["character_id"] = character.get("id")

    # (plus d'attribution d'enveloppes ici — voir /master/lock_join)

    # 3) log + save (pas de missions ici)
    GAME_STATE.log_event(
        "player_join",
        {
            "player_id": pid,
            "display_name": name,
            "character": character.get("name") if character else None,
        },
    )
    GAME_STATE.save()

    return AuthOut(player_id=pid, name=p["display_name"], character_id=p.get("character_id"))


@router.post("/login", response_model=AuthOut)
def login(data: LoginIn):
    """
    Connexion d’un joueur par nom + mot de passe.
    - 404 si joueur inconnu.
    - 401 si mot de passe invalide.
    - Retourne `player_id`, `name` (display_name) et `character_id` si existante.
    """
    name = data.name.strip()
    if not name:
        raise HTTPException(400, "Missing name.")

    p = _find_player_by_name(name)
    if not p:
        raise HTTPException(404, "Player not found.")
    hashed = p.get("password_hash")
    if not (isinstance(hashed, str) and verify_password(data.password, hashed)):
        raise HTTPException(401, "Invalid credentials.")
    return AuthOut(
        player_id=p["player_id"],
        name=p.get("display_name", name),
        character_id=p.get("character_id"),
    )


@router.get("/me", response_model=AuthOut)
def me(player_id: str):
    """
    Récupération du profil joueur minimal (pour hydrater le front).
    - Le front appelle /auth/me?player_id=...
    - Renvoie name (display_name) & character_id.
    - Les enveloppes (vue {num,id}) sont dans GAME_STATE.players[pid]["envelopes"] si besoin côté /game/state.
    """
    p = GAME_STATE.players.get(player_id)
    if not p:
        raise HTTPException(404, "Player not found.")
    return AuthOut(
        player_id=p["player_id"],
        name=p.get("display_name", ""),
        character_id=p.get("character_id"),
    )
