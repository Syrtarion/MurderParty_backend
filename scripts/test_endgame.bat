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

set "EVENTFILE=app\data\events.json"

if not exist "%EVENTFILE%" (
    echo ❌ Fichier introuvable - %EVENTFILE%
    goto :after_events
)

rem 1) Extraire toutes les occurrences de 'kind' dans un tmp
set "EVTMP=%TEMP%\_events_tmp_%RANDOM%.txt"
find /i "kind" "%EVENTFILE%" > "%EVTMP%"

rem 2) Compter le nombre de lignes du tmp (chaque ligne = 1 événement trouvé)
set "EVENTCOUNT="
for /f "tokens=2 delims=:" %%A in ('find /v /c "" "%EVTMP%"') do set /a EVENTCOUNT=%%A

del "%EVTMP%" >nul 2>&1

if not defined EVENTCOUNT set "EVENTCOUNT=0"
echo Nombre d’événements : %EVENTCOUNT%

if %EVENTCOUNT% LSS 10 (
    echo ❌ Trop peu d’événements
) else (
    echo ✅ Nombre d’événements suffisant
)

:after_events

echo.
echo --------------------------------
echo ✅ PHASE ENDGAME TERMINÉE
echo --------------------------------
pause
exit /b 0
