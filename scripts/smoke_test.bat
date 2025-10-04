@echo off
setlocal ENABLEDELAYEDEXPANSION

set BASE=http://localhost:8000
set TOKEN=changeme-super-secret

echo [1] Create 5 players
for /l %%i in (1,1,5) do (
  for /f "usebackq tokens=2 delims=:,{}\" " %%A in (`curl -s -X POST %BASE%/players/join -H "Content-Type: application/json" -d "{}"`) do (
    if "%%A" NEQ "" (
      set PID=%%A
      set PID=!PID:,=!
      set PID=!PID: =!
      set players=!players!!PID!,
    )
  )
)
rem trim trailing comma
set players=%players:~0,-1%
echo players=[%players%]

echo [2] Create minigame session (team, auto 2)
set body={"game_id":"quizz_rapide","mode":"team","participants":[%players%],"auto_team_count":2}
for /f "usebackq tokens=2 delims=:,{}\" " %%A in (`
  curl -s -X POST %BASE%/minigames/create -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "%body%"
`) do (
  if "%%A" NEQ "" set SID=%%A
)
echo session_id=%SID%

echo [3] Get participants (T1,T2) and submit scores
curl -s %BASE%/admin/sessions/active -H "Authorization: Bearer %TOKEN%" > tmp_active.json
for /f "tokens=1,2 delims=,[]\"" %%A in ('findstr /i /c:"participants" tmp_active.json') do (
  set T1=%%B
  set T2=%%C
)
set scoreBody={"session_id":"%SID%","scores":{"%T1%":12,"%T2%":9}}
curl -s -X POST %BASE%/minigames/submit_scores -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "%scoreBody%" >NUL

echo [4] Resolve (LLM generates clues)
curl -s -X POST %BASE%/minigames/resolve -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"session_id\":\"%SID%\"}"
echo.
endlocal
