---
name: deploy
description: BarChart Creator를 다른 사용자에게 전달 가능한 독립 실행 폴더(deploy/)로 빌드한다. PyInstaller 클린 재빌드 후 실행파일/의존성/정적파일을 deploy/ 폴더로 정리한다.
---

# deploy 스킬

BarChart Creator(`app.py`, FastAPI)를 Python 설치 없이도 실행 가능한 독립 폴더로 패키징한다.
`dist/BarChartCreator/`(PyInstaller onedir 빌드 결과)를 프로젝트 루트의 `deploy/` 폴더로 정리하는 방식이며,
빌드 스펙(`barchart.spec`)과 `app.py`의 frozen 대응 로직(`_get_base_path`, `_get_app_dir`)은 이미 구현되어 있으므로 수정하지 않는다.

## 실행 절차

1. 프로젝트 루트에서 `build_deploy.ps1`을 PowerShell로 실행한다.
   - 이 스크립트는 `build/`, `dist/`, `deploy/`를 삭제하고 `pyinstaller barchart.spec --noconfirm --clean`으로 클린 재빌드한 뒤,
     결과물을 `deploy/`로 옮기고 `deploy/data/`를 정리하며, `deploy/README.txt`를 생성한다.
     `deploy/data/`에는 실제 수집 데이터(xlsx)는 포함시키지 않되, 프로젝트 루트 `data/scenarios/`에
     있는 저장된 시나리오(`.pkl`/`.json`)는 `deploy/data/scenarios/`로 그대로 복사한다 — 개발자가
     만든 시나리오를 공유받는 사람도 동일하게 볼 수 있도록 하기 위함.
   - 클린 빌드이므로 numpy/pandas 전체 번들링 특성상 수 분 정도 걸릴 수 있다. 타임아웃을 넉넉히 준다.
2. PyInstaller가 설치되어 있지 않으면 스크립트가 에러로 안내하고 종료한다 — 이 경우 임의로 `pip install`을 실행하지 말고 사용자에게 먼저 확인한다.
3. 빌드 실패 시 로그에서 원인을 확인하여 보고한다. `barchart.spec`을 임의로 변경(예: `--onefile`로 전환)하지 않는다 — 스펙 변경이 필요해 보이면 사용자에게 먼저 확인한다.
4. 완료 후 다음을 검증한다:
   - `deploy/BarChartCreator.exe` 존재
   - `deploy/data/`에 사용자의 실제 수집 데이터 xlsx가 포함되지 않았는지 (xlsx는 항상 제외)
   - `deploy/data/scenarios/`에 개발자가 저장한 시나리오(`.pkl`/`.json` 쌍)가 프로젝트 루트
     `data/scenarios/`와 동일하게 복사되어 있는지 (의도된 포함 — 공유받는 사람도 개발자가
     저장한 시나리오를 저장/불러오기 화면에서 바로 볼 수 있어야 함)
   - `deploy/README.txt` 존재
5. 사용자에게 다음을 요약 보고한다:
   - `deploy/` 폴더 경로와 용량
   - "이 폴더를 그대로 압축/USB/공유폴더로 전달하면 다른 PC에서도 실행 가능" 안내
   - 인터넷 연결이 필요한 기능(스케줄 검색: `ubikais.fois.go.kr`, 바차트 렌더링: `d3js.org` CDN)과 인터넷 없이도 되는 기능(엑셀 업로드) 구분

## 주의사항

- `deploy/`는 매번 클린 재빌드로 덮어써지는 산출물 폴더다 (`.gitignore`에 등록됨). 사용자가 `deploy/` 안에 별도로 넣어둔 파일이 있다면 삭제되므로, 스크립트 실행 전 `deploy/`에 낯선 파일이 있는지 확인한다.
- `data/*.xlsx`(사용자가 실제로 수집한 운항 데이터)는 배포판에 포함하지 않는다. 앱이 최초 실행 시 자동으로 빈 `data/` 폴더를 생성하므로 문제되지 않는다.
- `data/scenarios/`(저장/불러오기 시나리오 데이터)는 위 xlsx 제외 규칙의 예외로, 배포판에 항상 포함시킨다. 개발자가 새로 저장한 시나리오를 배포판에서 빼고 싶다면 빌드 전 프로젝트 루트 `data/scenarios/`에서 해당 파일을 직접 정리해야 한다(스크립트가 자동으로 걸러주지 않음).
- `.mcp.json`, `.claude/`, `node_modules/`, `tests/` 등 개발 전용 파일은 애초에 `barchart.spec`의 `datas`에 포함되어 있지 않으므로 별도 제외 처리가 필요 없다.
