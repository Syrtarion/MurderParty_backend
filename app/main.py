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
from app.routes.trial import router as trial_router
from app.routes.game_leaderboard import router as leaderboard_router
from app.routes.master_objectives import router as master_objectives_router
from app.routes.master_canon import router as master_canon_router
from app.routes.master_reveal import router as master_reveal_router
from app.routes.admin_reset import router as admin_reset_router
# Si tu utilises le plan de partie :
from app.routes.party import router as party_router

from app.config.settings import settings

app = FastAPI(title="Murderparty Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Montage des routers
app.include_router(game_router)
app.include_router(players_router)
app.include_router(master_router)
app.include_router(ws_router)
app.include_router(minigames_router)
app.include_router(health_router)
app.include_router(admin_router)
app.include_router(trial_router)
app.include_router(leaderboard_router)
app.include_router(master_objectives_router)
app.include_router(master_canon_router)
app.include_router(master_reveal_router)
app.include_router(admin_reset_router)
app.include_router(party_router)  # commente cette ligne si tu n'utilises pas party.py

@app.get("/")
async def root():
    return {"ok": True, "service": "murderparty-backend"}

@app.on_event("startup")
async def list_routes():
    print("== LLM config ==", settings.LLM_PROVIDER, settings.LLM_MODEL, settings.LLM_ENDPOINT)
    print("== Registered routes ==")
    for r in app.routes:
        try:
            print(r.path, r.methods)
        except Exception:
            pass
