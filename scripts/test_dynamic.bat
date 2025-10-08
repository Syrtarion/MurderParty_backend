@echo off
chcp 65001 >nul
color 0B
title [MurderParty] Test Dynamic
echo.
echo ================================================
echo [TEST DYNAMIQUE] Narration, mini-jeux et indices
echo ================================================
echo.

REM --- MINI-JEU SOLO ---
echo [1] Mini-jeu SOLO...
curl -s -X POST http://localhost:8000/master/narrate_mg_end ^
     -H "Authorization: Bearer changeme-super-secret" ^
     -H "Content-Type: application/json" ^
     -d "{\"mode\":\"solo\",\"winners\":[\"player_1\"],\"losers\":[\"player_2\",\"player_3\",\"player_4\",\"player_5\"],\"mini_game\":\"enigme_clef\"}" > nul
if errorlevel 1 (echo ❌ Erreur solo & pause & exit /b 1) else (echo ✅ Mini-jeu solo OK.)

REM --- MINI-JEU TEAM ---
echo.
echo [2] Mini-jeu TEAM...
curl -s -X POST http://localhost:8000/master/narrate_mg_end ^
     -H "Authorization: Bearer changeme-super-secret" ^
     -H "Content-Type: application/json" ^
     -d "{\"mode\":\"team\",\"winners\":[\"player_1\",\"player_3\"],\"losers\":[\"player_2\",\"player_4\",\"player_5\"],\"mini_game\":\"duel_alibi\"}" > nul
if errorlevel 1 (echo ❌ Erreur team & pause & exit /b 1) else (echo ✅ Mini-jeu team OK.)

REM --- ENVELOPPE ---
echo.
echo [3] Enveloppe scannée...
curl -s -X POST http://localhost:8000/master/narrate_envelope ^
     -H "Authorization: Bearer changeme-super-secret" ^
     -H "Content-Type: application/json" ^
     -d "{\"player_id\":\"player_4\",\"envelope_id\":\"A3\"}" > nul
if errorlevel 1 (echo ❌ Erreur enveloppe & pause & exit /b 1) else (echo ✅ Enveloppe OK.)

REM --- NARRATION AUTO ---
echo.
echo [4] Narration automatique...
curl -s -X POST http://localhost:8000/master/narrate_auto ^
     -H "Authorization: Bearer changeme-super-secret" ^
     -H "Content-Type: application/json" ^
     -d "{\"theme\":\"ambiance\",\"context\":{\"situation\":\"Un orage éclate sur le manoir.\"}}" > nul
if errorlevel 1 (echo ❌ Erreur narration & pause & exit /b 1) else (echo ✅ Narration auto OK.)

echo.
echo --------------------------------
echo ✅ PHASE DYNAMIQUE TERMINÉE
echo --------------------------------
pause
exit /b 0
