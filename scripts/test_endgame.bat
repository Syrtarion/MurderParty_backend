@echo off
chcp 65001 >nul
color 0E
title [MurderParty] Test Endgame
echo.
echo ================================================
echo [TEST ENDGAME] Verdict, scores et cohérence finale
echo ================================================
echo.

REM --- VERDICT ---
echo [1] Simulation du verdict...
curl -s -X POST http://localhost:8000/trial/verdict ^
     -H "Authorization: Bearer changeme-super-secret" > nul
if errorlevel 1 (echo ❌ Erreur verdict & pause & exit /b 1) else (echo ✅ Verdict OK.)

REM --- LEADERBOARD ---
echo.
echo [2] Leaderboard final...
curl -s http://localhost:8000/trial/leaderboard ^
     -H "Authorization: Bearer changeme-super-secret"
if errorlevel 1 (echo ❌ Erreur leaderboard & pause & exit /b 1) else (echo ✅ Classement affiché.)

REM --- ASSERTIONS FINALES ---
echo.
echo [3] Vérification de cohérence JSON...
python -m json.tool app/data/game_state.json >nul 2>&1
if errorlevel 1 (echo ❌ game_state.json invalide & pause & exit /b 1)
python -m json.tool app/data/canon_narratif.json >nul 2>&1
if errorlevel 1 (echo ❌ canon_narratif.json invalide & pause & exit /b 1)
echo ✅ JSON valides.

REM --- TIMELINE ---
echo.
echo [4] Vérification du nombre d’événements...
for /f %%i in ('find /c "\"event\"" app/data/canon_narratif.json') do set count=%%i
echo Nombre d’événements : %count%
if %count% LSS 10 (echo ❌ Trop peu d’événements & pause & exit /b 1)
echo ✅ Timeline cohérente.

echo.
echo --------------------------------
echo ✅ PHASE ENDGAME TERMINÉE
echo --------------------------------
pause
exit /b 0
