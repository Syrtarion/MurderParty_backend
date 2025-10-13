"""
Configuration de l'application (Settings)
=========================================

Rôle
----
- Centraliser les paramètres de l'app (nom, host/port, secrets, chemins, LLM…).
- Les valeurs par défaut conviennent pour un environnement de dev local.
- Les variables peuvent être surchargées via un fichier `.env` ou l'environnement.

Intégrations
------------
- `pydantic-settings` charge automatiquement les variables d'env et `.env`.
- Les services/routers importent `from app.config.settings import settings`.

Bonnes pratiques
----------------
- *Ne commitez pas* une valeur réelle de `MJ_TOKEN`. Utilisez `.env`.
- `LLM_ENDPOINT` pointe par défaut vers Ollama local (http://localhost:11434).
- `DATA_DIR` calcule un chemin relatif au repo : `<repo>/app/data`.

Exemples de `.env`
------------------
APP_NAME="Murderparty Backend (Staging)"
HOST="0.0.0.0"
PORT=8080
MJ_TOKEN="mettre-une-valeur-secrète-en-prod"
LLM_PROVIDER="ollama"
LLM_MODEL="dolphin-mixtral"
LLM_ENDPOINT="http://localhost:11434/api/chat"
DATA_DIR="/var/opt/murderparty/data"
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
import os


class Settings(BaseSettings):
    # Nom du service (apparaît dans /health)
    APP_NAME: str = "Murderparty Backend"
    # Bind réseau (FastAPI / Uvicorn)
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Jeton MJ (Maître du Jeu) utilisé par la dépendance `mj_required`
    # ⚠️ Remplacez en production via .env
    MJ_TOKEN: str = "changeme-super-secret"

    # Configuration du LLM (par défaut : Ollama local + modèle dolphin-mixtral)
    LLM_PROVIDER: str = "ollama"
    LLM_MODEL: str = "dolphin-mixtral"
    # Endpoint par défaut pour /api/chat (Ollama) — peut être adapté selon provider
    LLM_ENDPOINT: str = "http://localhost:11434/api/chat"

    # Répertoire des fichiers persistés (JSON de runtime, seeds, etc.)
    # Par défaut: <repo>/app/data
    DATA_DIR: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

    # Paramétrage pydantic-settings :
    # - lit le fichier .env (UTF-8) si présent
    # - ignore les clés supplémentaires pour éviter les erreurs
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


# Instance unique importable partout : `settings`
settings = Settings()
