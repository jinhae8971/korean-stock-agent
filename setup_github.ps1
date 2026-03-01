# ============================================================
# Korean Stock Agent — GitHub 레포 자동 설정 스크립트
# 실행: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#        .\setup_github.ps1
# ============================================================
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding            = [System.Text.Encoding]::UTF8
chcp 65001 | Out-Null

# ─── 설정 값 ────────────────────────────────────────────────
$GH_USER    = "jinhae8971"
$GH_REPO    = "korean-stock-agent"
$GH_TOKEN   = "YOUR_GITHUB_TOKEN_HERE"
$REMOTE_URL = "https://$GH_TOKEN@github.com/$GH_USER/$GH_REPO.git"
$API_HDR    = @{
    "Authorization" = "token $GH_TOKEN"
    "Accept"        = "application/vnd.github+json"
    "User-Agent"    = "KoreanStockAgent-Setup"
}
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir
Write-Host "작업 디렉토리: $ScriptDir" -ForegroundColor Cyan

# ─── [1] Git 초기화 ─────────────────────────────────────────
Write-Host "`n[1/5] Git 초기화..." -ForegroundColor Yellow
git config --global --add safe.directory ($ScriptDir -replace '\\', '/') 2>$null

if (-not (Test-Path ".git")) {
    git init | Out-Null
    Write-Host "  git init 완료" -ForegroundColor Green
}

$prev = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
git remote remove origin 2>$null | Out-Null
$ErrorActionPreference = $prev

git remote add origin $REMOTE_URL
git config user.name  $GH_USER
git config user.email "YOUR_EMAIL_HERE"

# .gitignore 생성
@"
config.json
*.pyc
__pycache__/
.env
*.log
.DS_Store
.venv/
venv/
"@ | Set-Content -Encoding UTF8 ".gitignore"

Write-Host "  [1] Git 설정 완료" -ForegroundColor Green

# ─── [2] GitHub 레포 생성 ────────────────────────────────────
Write-Host "`n[2/5] GitHub 레포 확인/생성..." -ForegroundColor Yellow
try {
    Invoke-RestMethod -Uri "https://api.github.com/repos/$GH_USER/$GH_REPO" `
        -Headers $API_HDR | Out-Null
    Write-Host "  [2] 레포 이미 존재 — 스킵" -ForegroundColor Green
} catch {
    try {
        Invoke-RestMethod -Method Post -Uri "https://api.github.com/user/repos" `
            -Headers $API_HDR `
            -Body (@{
                name        = $GH_REPO
                description = "AI Multi-Agent Korean Stock Market Analysis System"
                private     = $false
                auto_init   = $false
            } | ConvertTo-Json) `
            -ContentType "application/json" | Out-Null
        Write-Host "  [2] 레포 생성 완료" -ForegroundColor Green
        Start-Sleep -Seconds 3
    } catch {
        Write-Host "  [2] 레포 수동 생성 필요: https://github.com/new (이름: $GH_REPO)" -ForegroundColor Red
        Read-Host "  레포 생성 후 Enter"
    }
}

# ─── [3] GitHub Pages 활성화 (docs/ 폴더) ────────────────────
Write-Host "`n[3/5] GitHub Pages 설정 (docs/ 폴더)..." -ForegroundColor Yellow
try {
    Invoke-RestMethod -Method Post `
        -Uri "https://api.github.com/repos/$GH_USER/$GH_REPO/pages" `
        -Headers $API_HDR `
        -Body (@{ source = @{ branch = "main"; path = "/docs" } } | ConvertTo-Json) `
        -ContentType "application/json" | Out-Null
    Write-Host "  [3] Pages 활성화 완료" -ForegroundColor Green
} catch {
    Write-Host "  [3] Pages 이미 설정되어 있거나 수동 설정 필요" -ForegroundColor Yellow
    Write-Host "      Settings -> Pages -> Source: main branch /docs" -ForegroundColor White
}

# ─── [4] 커밋 & 푸시 ─────────────────────────────────────────
Write-Host "`n[4/5] 코드 커밋 & 푸시..." -ForegroundColor Yellow

# 빈 .gitkeep 파일 생성
$dirs = @("data", "data/history", "docs/data")
foreach ($d in $dirs) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
    $gk = "$d/.gitkeep"
    if (-not (Test-Path $gk)) { "" | Set-Content -Encoding UTF8 $gk }
}

$ErrorActionPreference = "SilentlyContinue"
git add .
git commit -m "feat: initial deploy — Korean Stock Agent Quartet" 2>$null
if ($LASTEXITCODE -ne 0) {
    git commit --allow-empty -m "chore: initial deploy" 2>$null
}
git branch -M main
git push -u origin main --force 2>$null
$pushCode = $LASTEXITCODE
$ErrorActionPreference = "Stop"

if ($pushCode -ne 0) {
    Write-Host "  PUSH 실패! Token 'repo' 권한 확인:" -ForegroundColor Red
    Write-Host "  https://github.com/settings/tokens/new" -ForegroundColor White
    exit 1
}
Write-Host "  [4] Push 완료" -ForegroundColor Green

# ─── [5] Secrets 등록 ────────────────────────────────────────
Write-Host "`n[5/5] GitHub Actions Secrets 등록..." -ForegroundColor Yellow

$secrets = @{
    ANTHROPIC_API_KEY = ""   # <-- 여기에 Anthropic API Key 입력
    TELEGRAM_TOKEN    = "YOUR_TELEGRAM_TOKEN_HERE"
    TELEGRAM_CHAT_ID  = "YOUR_TELEGRAM_CHAT_ID_HERE"
}

if (-not $secrets["ANTHROPIC_API_KEY"]) {
    Write-Host "  ⚠️  ANTHROPIC_API_KEY가 비어 있습니다!" -ForegroundColor Red
    $key = Read-Host "  Anthropic API Key를 입력하세요"
    $secrets["ANTHROPIC_API_KEY"] = $key.Trim()
}

if (Get-Command gh -ErrorAction SilentlyContinue) {
    $env:GH_TOKEN = $GH_TOKEN
    foreach ($s in $secrets.GetEnumerator()) {
        gh secret set $s.Key --body $s.Value --repo "$GH_USER/$GH_REPO" 2>$null
        Write-Host "  Secret 등록: $($s.Key)" -ForegroundColor Green
    }
    Write-Host "  [5] Secrets 자동 등록 완료 (gh CLI)" -ForegroundColor Green
} else {
    Write-Host "  gh CLI 미설치 — 수동 등록 필요:" -ForegroundColor Yellow
    Write-Host "  URL: https://github.com/$GH_USER/$GH_REPO/settings/secrets/actions" -ForegroundColor White
    Write-Host ""
    foreach ($s in $secrets.GetEnumerator()) {
        Write-Host "  $($s.Key) = $($s.Value)" -ForegroundColor Cyan
    }
    Read-Host "`n  위 Secrets 등록 완료 후 Enter"
}

# ─── 완료 + 즉시 실행 ────────────────────────────────────────
Write-Host "`n워크플로우 즉시 실행 시도..." -ForegroundColor Yellow
try {
    $ErrorActionPreference = "SilentlyContinue"
    Invoke-RestMethod -Method Post `
        -Uri "https://api.github.com/repos/$GH_USER/$GH_REPO/actions/workflows/main.yml/dispatches" `
        -Headers $API_HDR `
        -Body '{"ref":"main"}' `
        -ContentType "application/json" | Out-Null
    $ErrorActionPreference = "Stop"
    Write-Host "  워크플로우 트리거 완료! (~3분 후 결과 확인)" -ForegroundColor Green
} catch {
    $ErrorActionPreference = "Stop"
    Write-Host "  수동 실행: https://github.com/$GH_USER/$GH_REPO/actions" -ForegroundColor White
}

Write-Host "`n============================================" -ForegroundColor Cyan
Write-Host " ✅ Korean Stock Agent 배포 완료!" -ForegroundColor Green
Write-Host "  GitHub: https://github.com/$GH_USER/$GH_REPO" -ForegroundColor White
Write-Host "  대시보드: https://$GH_USER.github.io/$GH_REPO/" -ForegroundColor White
Write-Host "  Actions:  https://github.com/$GH_USER/$GH_REPO/actions" -ForegroundColor White
Write-Host "============================================`n" -ForegroundColor Cyan
