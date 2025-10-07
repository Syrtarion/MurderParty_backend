# PowerShell script : session_full_test.ps1
# Test complet du déroulement de deux rounds

Write-Host "`n[*] Test automatisé - Déroulement complet de 2 rounds" -ForegroundColor Cyan
Write-Host "--------------------------------------------`n"

$BASE_URL = "http://localhost:8000"
$AUTH_HEADER = "Authorization: Bearer changeme-super-secret"
$JSON_HEADER = "Content-Type: application/json"

function Show-Step($msg) {
    Write-Host "`n====> $msg" -ForegroundColor Yellow
}

# 1️⃣ Statut initial
Show-Step "Statut initial de la session"
Invoke-RestMethod -Uri "$BASE_URL/session/status" -Headers @{ Authorization = "Bearer changeme-super-secret" } -Method Get

# 2️⃣ Lancement du premier round
Show-Step "Lancement du premier round"
Invoke-RestMethod -Uri "$BASE_URL/session/start_next" -Headers @{ Authorization = "Bearer changeme-super-secret" } -Method Post

# 3️⃣ Confirmation du démarrage
Show-Step "Confirmation du démarrage du mini-jeu"
Invoke-RestMethod -Uri "$BASE_URL/session/confirm_start" -Headers @{ Authorization = "Bearer changeme-super-secret" } -Method Post

# 4️⃣ Résultats du round 1
Show-Step "Résultats du round 1 (2 gagnants)"
$body1 = @{
    winners = @("player_1", "player_2")
    meta = @{
        scores = @{
            player_1 = 12
            player_2 = 9
        }
    }
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Uri "$BASE_URL/session/result" -Headers @{ Authorization = "Bearer changeme-super-secret"; "Content-Type" = "application/json" } -Method Post -Body $body1

# 5️⃣ Lancement du second round
Show-Step "Lancement du second round"
Invoke-RestMethod -Uri "$BASE_URL/session/start_next" -Headers @{ Authorization = "Bearer changeme-super-secret" } -Method Post

# 6️⃣ Confirmation du démarrage du round 2
Show-Step "Confirmation du démarrage du round 2"
Invoke-RestMethod -Uri "$BASE_URL/session/confirm_start" -Headers @{ Authorization = "Bearer changeme-super-secret" } -Method Post

# 7️⃣ Fin du round 2
Show-Step "Fin du round 2 (1 gagnant)"
$body2 = @{
    winners = @("player_3")
    meta = @{
        scores = @{
            player_3 = 15
        }
    }
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Uri "$BASE_URL/session/result" -Headers @{ Authorization = "Bearer changeme-super-secret"; "Content-Type" = "application/json" } -Method Post -Body $body2

# 8️⃣ Statut final
Show-Step "État final de la session"
Invoke-RestMethod -Uri "$BASE_URL/session/status" -Headers @{ Authorization = "Bearer changeme-super-secret" } -Method Get

Write-Host "`n--------------------------------------------"
Write-Host "[*] Test terminé ✅" -ForegroundColor Green
pause
