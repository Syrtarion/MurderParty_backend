# Backend — Index & Guide pour le Front

> **But** : offrir au Front une vue claire et à jour de l’API, des flux temps réel, des fichiers de données et des points d’attention.  
> **Scope** : projet MurderParty_backend (FastAPI + WS).

---

## 📦 Arborescence (vue logique)

```
app/
├─ main.py                         # Point d’entrée FastAPI (CORS, montage des routers)
├─ routes/                         # Endpoints REST + WebSocket
│  ├─ admin.py                     # MJ : lecture events & sessions runtime
│  ├─ admin_reset.py               # MJ : reset complet fichiers runtime
│  ├─ auth.py                      # Register/Login joueurs (hash mdp)
│  ├─ debug_ws.py                  # Dev : envoi WS de test (optionnel)
│  ├─ game.py                      # État public simple (+ canon brut ⚠ à filtrer)
│  ├─ game_leaderboard.py          # Leaderboard simple (score_total)
│  ├─ health.py                    # Healthchecks (service + LLM)
│  ├─ master.py                    # MJ : narration dynamique / indices / join lock
│  ├─ master_canon.py              # MJ : génération canon (LLM) + coupable
│  ├─ master_epilogue.py           # MJ : génération épilogue (LLM)
│  ├─ master_intro.py              # MJ : intro publique + canon minimal
│  ├─ master_objectives.py         # MJ : attribution points objectifs
│  ├─ master_reveal.py             # MJ : révélation coupable + missions secrètes
│  ├─ minigames.py                 # MJ : sessions mini-jeux (create/scores/resolve)
│  ├─ party.py                     # MJ : charger un plan (séquence de jeux)
│  ├─ party_mj.py                  # MJ : phases macro (start/envelopes/roles)
│  ├─ players.py                   # Inscription simple (sans mdp)
│  ├─ public.py                    # Intro publique sans spoiler
│  ├─ session.py                   # MJ : moteur de rounds (intro/active/cooldown)
│  ├─ timeline.py                  # Timeline filtrable (public/private/admin)
│  ├─ trial.py                     # MJ : votes & verdict de procès
│  └─ websocket.py                 # Endpoint WS unique (identify/ping/ack)
│
├─ services/                       # Cœur métier (état, LLM, narratif, etc.)
│  ├─ character_service.py         # Attribution personnages / enveloppes (seed/legacy)
│  ├─ game_state.py                # Singleton GAME_STATE (players/state/events)
│  ├─ io_utils.py                  # I/O JSON (orjson)
│  ├─ llm_engine.py                # Appels LLM (chat/generate) + anti-spoiler
│  ├─ minigame_catalog.py          # Référentiel des mini-jeux
│  ├─ minigame_runtime.py          # Sessions mini-jeux (active/history)
│  ├─ mission_service.py           # Missions secrètes (coupable/autres)
│  ├─ mj_engine.py                 # Phases macro MJ + WS
│  ├─ narrative_core.py            # Canon narratif + timeline + banlist
│  ├─ narrative_dynamic.py         # Événements narratifs dynamiques (LLM + WS)
│  ├─ narrative_engine.py          # Génération canon minimal + intro (LLM)
│  ├─ objective_service.py         # Attribution de points d’objectifs
│  ├─ session_engine.py            # Orchestration micro de rounds + timer
│  ├─ session_plan.py              # Plan de soirée (cursor + JSON)
│  ├─ trial_service.py             # Votes procès + verdict + MAJ scores
│  └─ ws_manager.py                # Gestionnaire WebSocket + wrappers safe
│
├─ engine/
│  └─ rewarder.py                  # Résolution mini-jeu + indices récompense
│
├─ deps/
│  └─ auth.py                      # Dependency FastAPI `mj_required` (Bearer)
│
├─ config/
│  └─ settings.py                  # Settings (LLM, MJ_TOKEN, DATA_DIR…)
│
├─ models/                         # Modèles Pydantic
│  ├─ event.py
│  ├─ game.py
│  └─ player.py
│
└─ utils/
   └─ team_utils.py                # Tirage d’équipes aléatoire
```

---

## ⚙️ Démarrage & Configuration

### Prérequis
- Python 3.11+
- (Optionnel) [Ollama](https://ollama.ai) en local si usage LLM

### Installation rapide
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt  # ou poetry install
uvicorn app.main:app --reload --port 8000
```

- Ajoute `.env` au `.gitignore` et purge-le de l’historique si déjà committé.

---

## 🗃️ Données (par défaut `app/data/`)

| Fichier                | Rôle |
|---|---|
| `players.json`         | Profils joueurs runtime |
| `game_state.json`      | État global (phase, flags, session…) |
| `events.json`          | Journal runtime |
| `canon_narratif.json`  | Vérité verrouillée + timeline + intro |
| `story_seed.json`      | Seed narratif (persos, enveloppes, missions, contraintes) |
| `minigames.json`       | Catalogue mini-jeux |
| `session_plan.json`    | Plan de soirée (⚠ schéma à unifier, voir TODO) |
| `trial_state.json`     | Votes + historique du procès |

---

## 🔐 Authentification

- **MJ** : Bearer via `Authorization: Bearer <MJ_TOKEN>`  
  Protège `master/*`, `party/*`, `session/*`, `minigames/*`, `trial/*`, etc.  
- **Joueurs** : `/auth/register` (avec mdp) ou `/players/join` (rapide, sans mdp).

---

## 🧭 Endpoints utiles pour le Front

### Public / joueurs
- `GET /` : ping
- `GET /public/intro` : texte d’intro **sans spoilers**
- `GET /timeline?scope=public|all&spoiler=bool&player_id=...` : flux filtré
- `GET /game/leaderboard` : classement simple (score_total)
- *(WS)* `GET /ws` : voir protocole ci-dessous

### MJ (Back-office)
- **Phases & plan** :  
  `POST /party/start` → `POST /party/players_ready` → `POST /party/envelopes_done`  
  `POST /party/load_plan` → `POST /party/next_round`
- **Rounds (moteur session)** :  
  `POST /session/start_next` → `POST /session/confirm_start` → `POST /session/result`
- **Mini-jeux** :  
  `POST /minigames/create` → `POST /minigames/submit_scores` → `POST /minigames/resolve`
- **Narration / canon** :  
  `POST /master/intro` (génère intro + canon minimal), `POST /master/reveal_culprit`  
- **Procès** :  
  `POST /trial/vote`, `GET /trial/tally`, `POST /trial/verdict`, `GET /trial/leaderboard`

> ⚠️ `GET /game/canon` expose le canon complet : **réserver à l’UI MJ**.

---

## 🔌 WebSocket (`/ws`)

### Handshake & Identify
1. client → **connect** `ws://<host>/ws`  
2. client → `{"type":"identify","player_id":"<id>"}`  
3. serveur → `{"type":"identified","player_id":"<id>"}`

### Heartbeat
- client → `{"type":"ping"}`  
- serveur → `{"type":"pong"}`

### Messages émis par le serveur (exemples)
- Narration: `{"type":"narration","event":"round_intro","text":"..."}`  
- Indice privé: `{"type":"clue","scope":"private","payload":{...}}`  
- Mission secrète: `{"type":"secret_mission","mission":{...}}`  
- Prompts UI: `{"type":"prompt","kind":"start_minigame","round_index":N}`  
- Événements système: `{"type":"event","kind":"missions_ready","payload":{...}}`

---

## 🧪 Flux typiques

### Démarrage de partie
1. MJ → `/party/start` (ouvre inscriptions)  
2. Joueurs → `/auth/register` **ou** `/players/join`  
3. MJ → `/master/intro` → Front lit `/public/intro`

### Un round de mini-jeu
1. MJ → `/session/start_next` → WS “round_intro” + prompt “start_minigame”  
2. MJ → `/session/confirm_start` → optional timer  
3. MJ → `/session/result` (winners/meta) → WS “round_end” + indices (rewarder)

### Procès
1. (selon UX) Votes via `/trial/vote`  
2. MJ → `/trial/tally` pour l’agrégat  
3. MJ → `/trial/verdict` → maj scores + verdict final

---

## ⚠️ Points d’attention (connus)

- **Guard d’inscription** : `/auth/register` respecte `join_locked`, `/players/join` non → **à harmoniser**.
- **Canon** : structures différentes selon générateurs (intro vs canon MJ) → **à normaliser** (`culprit_player_id`, etc.).
- **Plan de session** : `session_engine` lit `rounds[]`, `party/session_plan` écrit `games_sequence[]` → **unifier schéma**.
- **/game/canon** : ne pas consommer côté joueurs (spoilers).
- **LLM endpoint** : `run_llm` hardcode `/api/generate`, `generate_indice` utilise `settings.LLM_ENDPOINT` → **centraliser**.

---

## 🧰 Dépendances & Tech

- **FastAPI** (+ Pydantic), **starlette.websockets**
- **orjson** pour I/O JSON
- **Ollama** (par défaut) pour LLM — configurable via `.env`

---

## ✅ Checklist Front (écrans)

- **Accueil / Intro** : `GET /public/intro` + écoute WS `narration`
- **Inscription** : POST `/auth/register` ou `/players/join`
- **Lobby / Timeline** : `GET /timeline?scope=public` + WS (narration, prompt)
- **Mini-jeux** : affichage prompts WS ; résultats via WS / endpoints MJ
- **Indice perso** : WS `clue` (scope private)
- **Classement** : `GET /game/leaderboard` (live), `/trial/leaderboard` (procès)

---

## 🧭 Maintenance de ce document

- Ce fichier **est la source de vérité** pour le Front.  
- Quand un endpoint ou un flux change : **mettre à jour ce doc** dans la même PR.  
- En parallèle, on garde un **canvas** dans ChatGPT comme bloc-notes ; je fournis les diffs à reporter ici.
