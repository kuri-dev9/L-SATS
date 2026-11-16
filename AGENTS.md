# AI 에이전트용 안내

레이저 스캔 데이터로 실별 슬래브 두께를 산출하는 Streamlit 웹 앱입니다. **대상 환경은 Windows PC**입니다.
사용자용 설명은 README.md에 있습니다.

## 실행 (Windows)

가장 쉬운 방법은 `run.bat`을 실행하는 것입니다. 처음 실행할 때 `.venv`를 만들고 패키지를 설치한 뒤 `http://localhost:8501`을 엽니다.

수동 실행 (cmd 또는 PowerShell, 가상환경 활성화 없이):

```bat
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m streamlit run app.py
```

- `py`가 없으면 `python`을 씁니다. Python 3.11 이상이 필요합니다.
- PowerShell의 `Activate.ps1`은 실행 정책 때문에 막힐 수 있으니 `.venv\Scripts\python.exe`를 직접 호출하세요.
- 서버만 띄우고 확인하려면 `--server.headless true`를 붙이고 `http://localhost:8501/_stcore/health`가 `ok`인지 봅니다.
- 테스트는 66개가 모두 통과해야 합니다(`sample_data/`가 없으면 그중 9개는 건너뜀) (`test.bat`으로도 실행 가능).
- `demo_data/`는 `tools/make_demo_data.py`로 만든 가상 데이터입니다. 실제 현장 데이터(`sample_data/` 등)는 공개 저장소이므로 커밋하지 마세요.

macOS/Linux: `./run.sh`, 또는 `.venv/bin/python`으로 같은 명령을 실행합니다.

## 핵심 규칙

- 판정 기준은 **방 평균 135mm 이상(허용 오차 0) 고정**입니다. 화면에 입력 칸을 두지 않습니다(`Settings` 기본값).
- 두께(mm) = (상부층 `floor_z` − 하부층 `ceiling_z`) × 1000. `floor_z`는 콘크리트 윗면입니다.
- 상·하부층은 같은 측량 기준점이지만 **포인트 번호와 격자 배치가 다릅니다.** `point_id`로 병합하지 말고 XY 좌표로 대응시킵니다.
- DXF는 mm 단위 도면 좌표, CSV는 m 단위 측량 좌표(회전되어 있음, 데모 데이터는 23.5°)입니다. 변환은 도면의 측정점 라벨(P001…)로 구합니다.
- 계산 로직은 `slab/` 패키지에 두고, 화면은 `app.py`(왼쪽 메뉴) → `views/dashboard.py`(홈) · `views/analysis.py`(두께 분석) · `views/report.py`(보고서·내려받기) · `views/jobs.py`(작업 내역) · `views/settings.py`(설정, 메뉴 맨 아래)가 담당합니다. 올린 파일·계산 결과는 `views/shared.py`가 세션에 두어 화면을 옮겨도 남습니다(`compute()`).
- 계산한 작업은 `slab/history.py`가 `work_history/history.json`(+ `files/<ID>/` 입력 파일 사본)에 자동 저장합니다(커밋 금지, 테스트는 `LSATS_HISTORY`). 작업마다 그때 설정을 함께 저장해 다시 열어도 같은 결과가 나옵니다. 화면에 '데모' 데이터를 자동으로 띄우지 않습니다(`demo_data/`는 테스트용). 화면 색은 `.streamlit/config.toml`의 `[theme]`에서 정합니다.
- 바꿀 수 있는 계산·출력 값은 `slab/core.py`의 `Settings`에 두고, 설정 페이지 항목·설명은 `slab/settings_store.py`의 `FIELDS` 한 곳에서 정합니다. 저장 파일은 프로그램 폴더의 `user_settings.json`(커밋 금지, 테스트는 `LSATS_SETTINGS`로 임시 파일 사용)입니다. 담당자 확인 전인 값은 `pending=True`로 둡니다.
- 대응 순서: 직접 대응(허용 거리 안·정상 천장점) → 실패 시 TIN 보간(외삽 금지) → 미산출. 미산출은 두께를 비워 두고 0으로 채우지 않습니다. 방 집계는 `room_id` 기준이며 영역외 점은 넣지 않습니다.
- 화면은 처음 쓰는 사람 기준입니다. 홈에는 간단한 소개와 최근 분석만, 두께 분석 화면에는 ① 파일 올리기 → ② 결과(통과/미달 판정) → ③ 다음 할 일만 두고, 전문 설정·상세 표는 「자세히 보기」에 둡니다. 쉬운 말을 쓰세요.
- 그림·보고서의 판정 색은 **방 평균 판정**을 따릅니다(통과 초록, 미달 빗금 빨강). 색은 `slab/plot.py`의 `STATUS` 한 곳에서 정합니다.
- 보고서 영역은 `slab/report_html.py`의 `SECTIONS`/`PRESETS`에 추가합니다.
- `.bat` 파일은 CRLF 줄바꿈과 ASCII 문자만 씁니다 (`.gitattributes`로 고정되어 있습니다).
- 프로그램을 모르는 사용자에게는 README 0장의 휴대용 ZIP(`START.bat`)을 안내합니다. 빌드는 `packaging/`과 `.github/workflows/release.yml`(태그 `v*` push)로 합니다. 릴리스에는 전체 ZIP과 프로그램 파일만 담은 `L-SATS-update.zip`이 함께 올라가고, 설치된 폴더의 `UPDATE.bat`이 이것을 받아 바꿉니다. `requirements.txt`를 바꾸면 사용자는 전체 ZIP을 다시 받아야 합니다(UPDATE.bat이 알아서 안내). `packaging/update.ps1`은 Windows PowerShell 5.1용이라 ASCII 문자만 씁니다.
