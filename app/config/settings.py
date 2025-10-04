from pydantic_settings import BaseSettings, SettingsConfigDict
import os


class Settings(BaseSettings):
    APP_NAME: str = "Murderparty Backend"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Mot de passe MJ (maître du jeu)
    MJ_TOKEN: str = "changeme-super-secret"

    # Configuration LLM (par défaut Ollama dolphin-mixtral)
    LLM_PROVIDER: str = "ollama"
    LLM_MODEL: str = "dolphin-mixtral"
    LLM_ENDPOINT: str = "http://localhost:11434/api/chat"

    # Répertoire des données
    DATA_DIR: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
