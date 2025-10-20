"""
Application FastAPI — Point d'entrée
====================================

Rôle
----
- Instancie l'app FastAPI, configure le CORS pour le front,
- Monte tous les routeurs (REST + WebSocket),
- Affiche la configuration LLM et la liste des routes au démarrage.

Notes
-----
- Les importations des routeurs sont explicites pour éviter les surprises d’auto-discovery.
- `debug_ws` est monté seulement si `ROUTER_ENABLED` est True (pratique en dev).
- Garder la liste `ALLOWED_ORIGINS` en phase avec les URLs du front.
- ⚠️ Le middleware CORS doit être ajouté AVANT les include_router.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Imports directs des routeurs (robuste, évite le lookup de sous-modules)
from app.routes.game import router as game_router
from app.routes.players import router as players_router
from app.routes.master import router as master_router
from app.routes.websocket import router as ws_router
from app.routes.minigames import router as minigames_router
from app.routes.health import router as health_router
from app.routes.admin import router as admin_router
from app.routes.public import router as public_router
from app.routes.trial import router as trial_router
from app.routes.game_leaderboard import router as leaderboard_router
from app.routes.master_objectives import router as master_objectives_router
from app.routes.master_canon import router as master_canon_router
from app.routes.master_reveal import router as master_reveal_router
from app.routes.master_intro import router as master_intro_router
from app.routes.admin_reset import router as admin_reset_router
# Si tu utilises le plan de partie :
from app.routes.party import router as party_router
from app.routes.party_mj import router as party_mj_router
from app.routes.session import router as session_router
from app.routes.timeline import router as timeline_router
from app.routes.master_epilogue import router as master_epilogue_router
from app.routes import debug_ws
from app.routes import auth as auth_router
from app.routes.auth_mj import router as auth_mj_router
from app.routes.debug_ws import router as debug_ws_router

from app.config.settings import settings

# --- App FastAPI principale  ---
app = FastAPI(title="Murderparty Backend")

# ===========================
# CORS (dev: permissif)
# ===========================
# En dev on autorise localhost, en prod pense à restreindre.
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    # "http://192.168.1.xx:3000",  # front sur une autre machine du LAN
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,   # ← whitelist des frontends autorisés
    allow_credentials=True,          # ← nécessaire si tu passes des cookies
    allow_methods=["*"],             # ← autorise toutes les méthodes HTTP
    allow_headers=["*"],             # ← autorise tous les headers custom (dont Authorization)
)

# ===========================
# Montage des routers
# ===========================
# ⚠️ Laisse les protections MJ au niveau DES ROUTES (Depends(mj_required) sur les routes),
#    pas sur le router entier, pour ne pas bloquer les préflights OPTIONS.
app.include_router(game_router)
app.include_router(players_router)
app.include_router(master_router)
app.include_router(ws_router)                  # WebSocket endpoint (/ws)
app.include_router(minigames_router)
app.include_router(health_router)
app.include_router(admin_router)
app.include_router(public_router)
app.include_router(trial_router)
app.include_router(leaderboard_router)
app.include_router(master_objectives_router)
app.include_router(master_canon_router)
app.include_router(master_reveal_router)
app.include_router(master_intro_router)
app.include_router(admin_reset_router)
app.include_router(party_router)               # routes /party (avec Depends(mj_required) PAR ROUTE)
app.include_router(party_mj_router)
app.include_router(session_router)
app.include_router(timeline_router)
app.include_router(master_epilogue_router)
app.include_router(auth_mj_router)
app.include_router(debug_ws_router)

# Router de debug WS optionnel (en dev)
if getattr(debug_ws, "ROUTER_ENABLED", False):
    app.include_router(debug_ws.router)

# Auth joueurs (register/login)
app.include_router(auth_router.router)

# --- Racine utile pour "ping" simple (sans /health) ---
@app.get("/")
async def root():
    """Ping basique : permet de vérifier que l'app tourne (sans dépendance LLM)."""
    return {"ok": True, "service": "murderparty-backend"}

# --- Hook de démarrage ---
@app.on_event("startup")
async def list_routes():
    """
    Au démarrage:
    - affiche la config LLM courante (provider, modèle, endpoint),
    - liste les routes (path + méthodes) dans la console (diagnostic).
    """
    print("== LLM config ==", settings.LLM_PROVIDER, settings.LLM_MODEL, settings.LLM_ENDPOINT)
    print("== Registered routes ==")
    for r in app.routes:
        try:
            print(r.path, r.methods)
        except Exception:
            # Certains objets routes peuvent ne pas exposer ces attributs; on ignore.
            pass
