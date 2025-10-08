@echo off
chcp 65001 >nul
color 0A
title [MurderParty] Test Core
echo.
echo ================================================
echo [TEST CORE] Initialisation et génération du canon
echo ================================================
echo.

REM --- RESET VIA API ---
echo [1] Reset complet via l'API...
curl -s -X POST http://localhost:8000/admin/reset_game ^
     -H "Authorization: Bearer changeme-super-secret" ^
     -H "Content-Type: application/json" > temp_reset.json
if errorlevel 1 (
    echo ❌ Erreur lors du reset via API
    type temp_reset.json
    del temp_reset.json >nul 2>&1
    pause
    exit /b 1
)
echo ✅ Reset via API OK.
echo Réponse :
type temp_reset.json
del temp_reset.json >nul 2>&1

REM --- CREATION JOUEURS ---
echo.
echo [2] Création de 5 joueurs...
for %%A in (1 2 3 4 5) do (
    curl -s -X POST http://localhost:8000/players/join ^
         -H "Content-Type: application/json" ^
         -d "{\"nickname\":\"Player%%A\"}" >nul
)
echo ✅ 5 joueurs ajoutés.

REM --- GENERATION DU CANON ---
echo.
echo [3] Génération du canon narratif...
curl -s -X POST http://localhost:8000/master/generate_canon ^
     -H "Authorization: Bearer changeme-super-secret" ^
     -H "Content-Type: application/json" ^
     -d "{\"style\":\"dramatique et immersif\"}" > temp_canon.json
if errorlevel 1 (
    echo ❌ Erreur génération canon
    type temp_canon.json
    del temp_canon.json >nul 2>&1
    pause
    exit /b 1
)
echo ✅ Canon généré.
echo Résumé :
findstr "culprit weapon location motive" temp_canon.json
del temp_canon.json >nul 2>&1

REM --- INTRODUCTION ---
echo.
echo [4] Génération de l’introduction...
curl -s -X POST http://localhost:8000/master/intro ^
     -H "Authorization: Bearer changeme-super-secret" ^
     -H "Content-Type: application/json" ^
     -d "{\"style\":\"mystérieux et cinématographique\"}" > temp_intro.json
if errorlevel 1 (
    echo ❌ Erreur génération intro
    type temp_intro.json
    del temp_intro.json >nul 2>&1
    pause
    exit /b 1
)
echo ✅ Introduction générée.
echo Extrait :
findstr "intro_text" temp_intro.json
del temp_intro.json >nul 2>&1

REM --- MISSIONS & COUPABLE ---
echo.
echo [5] Attribution du coupable et missions secrètes...
curl -s -X POST http://localhost:8000/master/reveal_culprit ^
     -H "Authorization: Bearer changeme-super-secret" > temp_reveal.json
if errorlevel 1 (
    echo ❌ Erreur attribution missions
    type temp_reveal.json
    del temp_reveal.json >nul 2>&1
    pause
    exit /b 1
)
echo ✅ Missions attribuées.
echo Résumé :
findstr "culprit_player_id culprit_name" temp_reveal.json
del temp_reveal.json >nul 2>&1

echo.
echo --------------------------------
echo ✅ PHASE CORE TERMINÉE AVEC SUCCÈS
echo --------------------------------
pause
exit /b 0
