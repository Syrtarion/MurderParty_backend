@echo off
REM === Murderparty Backend Launcher ===

REM Aller sur le disque H:
H:
cd H:\murderparty\murderparty_backend

echo.
echo [*] Activation de l'environnement virtuel...
call .venv\Scripts\activate.bat

echo.
echo [*] Installation des dépendances (si besoin)...
pip install -r requirements.txt >nul

echo.
echo [*] Lancement du serveur FastAPI...
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

echo.
pause
