# BarChart Creator를 배포용 독립 실행 폴더(deploy/)로 빌드한다.
# PyInstaller로 클린 재빌드 후 dist/BarChartCreator를 deploy/로 정리한다.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

Write-Host "=== BarChart Creator 배포 빌드 시작 ===" -ForegroundColor Cyan

# 1. PyInstaller 설치 확인
$pyinstallerCheck = pip show pyinstaller 2>$null
if (-not $pyinstallerCheck) {
    Write-Error "PyInstaller가 설치되어 있지 않습니다. 'pip install pyinstaller'로 설치 후 다시 실행하세요."
    exit 1
}

# 2. 이전 빌드 산출물 정리
foreach ($dir in @("build", "dist", "deploy")) {
    $path = Join-Path $root $dir
    if (Test-Path $path) {
        Write-Host "기존 $dir\ 삭제 중..."
        Remove-Item -Recurse -Force $path
    }
}

# 3. PyInstaller 클린 빌드
Write-Host "PyInstaller 빌드 중 (수 분 소요될 수 있음)..." -ForegroundColor Cyan
pyinstaller barchart.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller 빌드에 실패했습니다. 위 로그를 확인하세요."
    exit 1
}

$exePath = Join-Path $root "dist\BarChartCreator\BarChartCreator.exe"
if (-not (Test-Path $exePath)) {
    Write-Error "빌드 결과물(BarChartCreator.exe)을 찾을 수 없습니다."
    exit 1
}

# 4. dist/BarChartCreator -> deploy/
$deployPath = Join-Path $root "deploy"
Move-Item -Path (Join-Path $root "dist\BarChartCreator") -Destination $deployPath

# 5. data/ 폴더 정리
#    - 실제 수집 데이터(xlsx)는 배포판에 포함하지 않는다 (deploy/data/에는 애초에 없음).
#    - 저장/불러오기(시나리오) 데이터는 개발자가 만든 내용을 그대로 배포판에 포함시킨다.
$dataPath = Join-Path $deployPath "data"
$scenariosDestPath = Join-Path $dataPath "scenarios"
New-Item -ItemType Directory -Path $scenariosDestPath -Force | Out-Null

$scenariosSrcPath = Join-Path $root "data\scenarios"
$scenarioCount = 0
if (Test-Path $scenariosSrcPath) {
    $scenarioFiles = Get-ChildItem -Path $scenariosSrcPath -Filter "*.json" -File
    foreach ($jsonFile in $scenarioFiles) {
        Copy-Item -Path $jsonFile.FullName -Destination $scenariosDestPath -Force
        $pklFile = Join-Path $scenariosSrcPath ($jsonFile.BaseName + ".pkl")
        if (Test-Path $pklFile) {
            Copy-Item -Path $pklFile -Destination $scenariosDestPath -Force
        }
    }
    $scenarioCount = $scenarioFiles.Count
}
Write-Host "시나리오 저장 데이터 ${scenarioCount}건 포함됨 (deploy/data/scenarios/)"

# 6. README.txt 작성
$readme = @'
BarChart Creator 배포판
=========================

[실행 방법]
1. BarChartCreator.exe 를 더블클릭하여 실행합니다.
2. 잠시 후 기본 브라우저가 자동으로 열리며 http://127.0.0.1:8000 에 접속됩니다.
   자동으로 열리지 않으면 브라우저 주소창에 위 주소를 직접 입력하세요.
3. 종료하려면 실행 중인 콘솔 창을 닫거나 Ctrl+C를 누르세요.

[인터넷 연결 관련 안내]
- 항공편 스케줄 "검색" 기능은 ubikais.fois.go.kr(항공정보시스템) 접속이 필요하므로
  인터넷 연결이 필요합니다.
- 바차트 화면은 d3js.org 에서 차트 라이브러리를 불러오므로 인터넷 연결이 필요합니다.
- 엑셀 업로드 기능(양식에 맞춰 작성한 파일 업로드)은 인터넷 연결 없이도 사용할 수 있습니다
  (단, 바차트 렌더링 자체는 위와 같이 인터넷이 필요합니다).

[데이터 폴더]
- data\ 폴더는 검색/업로드한 엑셀 데이터가 저장되는 공간이며, 최초 배포 시에는 비어 있습니다.
- data\scenarios\ 폴더는 예외로, 개발자가 미리 저장해 둔 시나리오가 포함되어 있을 수 있습니다.
  화면 상단의 "저장/불러오기" 버튼을 눌러 바로 확인하고 불러올 수 있습니다.
'@
Set-Content -Path (Join-Path $deployPath "README.txt") -Value $readme -Encoding UTF8

# 7. 결과 출력
$sizeBytes = (Get-ChildItem -Path $deployPath -Recurse -Force | Measure-Object -Property Length -Sum).Sum
$sizeMB = [math]::Round($sizeBytes / 1MB, 1)

Write-Host ""
Write-Host "=== 배포 폴더 생성 완료 ===" -ForegroundColor Green
Write-Host "경로: $deployPath"
Write-Host "용량: $sizeMB MB"
Write-Host "이 deploy 폴더를 그대로 압축/USB/공유폴더 등으로 전달하면 됩니다."
