# AI 에이전트용 안내

레이저 스캔 데이터로 층별·측정점별 슬래브 두께 현황을 산출하는 Streamlit 웹 앱입니다. **대상 환경은 Windows PC**입니다.
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
- 테스트는 모두 통과해야 합니다(`sample_data/`가 없으면 일부는 건너뜀) (`test.bat`으로도 실행 가능).
- `demo_data/`는 `tools/make_demo_data.py`로 만든 가상 데이터입니다. 실제 현장 데이터(`sample_data/` 등)는 공개 저장소이므로 커밋하지 마세요.

macOS/Linux: `./run.sh`, 또는 `.venv/bin/python`으로 같은 명령을 실행합니다.
- 서버 관리: `run.bat`/`run.sh` 에 `start`(뒤에서 실행·브라우저 열기) · `stop` · `restart` · `status` · `log`(`.run/server.log`, 커밋 안 함). 인자가 없거나 `--` 옵션만 주면 예전처럼 그 창에서 실행합니다. 포트는 `LSATS_PORT`(기본 8501), `LSATS_NO_BROWSER=1`이면 브라우저를 열지 않습니다. 화면 확인 전 서버를 다시 띄울 때는 `restart`를 씁니다. Windows 쪽 명령은 CI(`test.yml`의 windows-run-bat)가 실제로 돌려 봅니다.

## 현장 PC(Windows)에서 작업할 때

- 이 저장소는 현장 Windows PC에서 직접 실행·개발합니다(`git clone` → `run.bat`). 현장 원본(LAS·CSV·DXF)은 그 PC에만 두고 커밋하지 않습니다.
- 그 PC에서 먼저 확인할 일과 지금까지의 검증 결과는 `docs/DEVELOPER_PROMPT.md`의 '현장 PC' 절에 있습니다.
- 사용자 작업 방식: 한국어로 답합니다. 개발 중에는 테스트를 매번 돌리지 말고 기능부터 만들되, 커밋·배포 전에는 `test.bat`(또는 pytest)으로 모두 통과를 확인합니다.
  현장 결과값(두께가 얇다 등)에 맞춰 계산을 바꾸지 말고 계산이 맞는지만 봅니다. 화면을 확인할 때 포트 8501 이 이미 쓰이고 있으면 기존 서버를 끄고 8501 로 다시 띄웁니다.

## 핵심 규칙

- **통과/미달 판정은 하지 않습니다(현황 파악이 목적, v0.3에서 135mm 기준 삭제).** 측정점마다 결과 상태를 붙입니다:
  `산출 완료` / `두께 범위 검토`(140mm 이상) / `이상치 검토`(같은 방 5점 이상, MAD 3.5배) / `두께 비정상(하한 이하)`(0mm 이하) /
  `미산출`(사유 `대응점 없음`·`Z값 확인 필요`) / `영역 외`. 기준값은 받은 결과 엑셀에 맞춘 `Settings` 기본값이고 설정에서 바꿀 수 있습니다.
  방·층 평균·최소·최대는 `산출 완료` 점으로만 냅니다.
- 두께(mm) = (상부층 `floor_z` − 하부층 `ceiling_z`) × 1000. `floor_z`는 콘크리트 윗면입니다.
- 상·하부층은 같은 측량 기준점이지만 **포인트 번호와 격자 배치가 다릅니다.** `point_id`로 병합하지 말고 XY 좌표로 대응시킵니다.
- DXF는 mm 단위 도면 좌표, CSV는 m 단위 측량 좌표(회전되어 있음, 데모 데이터는 23.5°)입니다. 변환은 도면의 측정점 라벨(P001…)로 구합니다.
- 여러 층 파일을 한꺼번에 받습니다. `slab/batch.py`가 파일 안의 바닥 높이(`Global_Floor_m`, 없으면 바닥 Z 중앙값)로 층 순서를 정하고 바로 아래층과 짝짓습니다(층 이름은 파일 이름의 `8F` 등). 도면은 위층 기준이며 파일 이름의 층 → 층 표기 없는 도면 하나는 공용 → 여러 개면 측정점 좌표로 배정합니다. 사용자가 층 이름·도면을 고칠 수 있습니다(`floor_labels`, `cad_choice`). 100개 층도 들어올 수 있으니 층마다 계산은 캐시합니다.
- 계산 로직은 `slab/` 패키지에 두고, 화면은 `app.py`(왼쪽 메뉴) → `views/dashboard.py`(홈) · `views/analysis.py`(두께 분석) · `views/report.py`(보고서·내려받기) · `views/jobs.py`(작업 내역) · `views/settings.py`(설정, 메뉴 맨 아래)가 담당합니다. 올린 파일·계산 결과는 `views/shared.py`가 세션에 두어 화면을 옮겨도 남습니다(`compute()`).
- 계산한 작업은 `slab/history.py`가 `work_history/history.json`(+ `files/<ID>/` 입력 파일 사본)에 자동 저장합니다(커밋 금지, 테스트는 `LSATS_HISTORY`). 작업마다 그때 설정을 함께 저장해 다시 열어도 같은 결과가 나옵니다. 화면에 '데모' 데이터를 자동으로 띄우지 않습니다(`demo_data/`는 테스트용). 화면 색은 `.streamlit/config.toml`의 `[theme]`에서 정합니다.
- 바꿀 수 있는 계산·출력 값은 `slab/core.py`의 `Settings`에 두고, 설정 페이지 항목·설명은 `slab/settings_store.py`의 `FIELDS` 한 곳에서 정합니다. 저장 파일은 프로그램 폴더의 `user_settings.json`(커밋 금지, 테스트는 `LSATS_SETTINGS`로 임시 파일 사용)입니다. 담당자 확인 전인 값은 `pending=True`로 둡니다.
- 대응 순서: 직접 대응(허용 거리 안·정상 천장점) → 실패 시 TIN 보간(외삽 금지) → 미산출. 미산출은 두께를 비워 두고 0으로 채우지 않습니다. 방 집계는 `room_id` 기준이며 영역외 점은 넣지 않습니다.
- 화면은 처음 쓰는 사람 기준입니다. 홈에는 간단한 소개와 최근 분석만, 두께 분석 화면에는 ① 파일 올리기(여러 파일·폴더) → ② 층별 현황 → ③ 층 보기(콤보박스·위층/아래층 버튼으로 층 이동, 측정점 위치도가 메인·방별 두께도가 서브, 방·포인트 확대와 점 상세) → ④ 다음 할 일만 두고, 전문 설정·상세 표는 「자세히 보기」에 둡니다. 쉬운 말을 쓰세요.
- **메인 자료는 측정점 위치도**(점마다 `P013 / 338mm` 이름표, 두께 색, 미산출 회색 ×, 영역 외 회색 ○), **방별 두께도는 서브 자료**입니다(실무자 요청).
  두께 색 막대(옅은 초록 얇음 → 옅은 주황 두꺼움, 채도 낮게)는 `slab/plot.py`의 `THICK_COLORS`, 상태별 표시는 `STATUS` 한 곳에서 정합니다.
- 측정점 위치도·방별 두께도는 `views/plan_viewer.py`(커스텀 컴포넌트 v2, 캔버스)가 그립니다. 회전·점 글자·점 상세 카드는 **브라우저 안에서만** 처리하고 Python 으로 값을 보내지 않습니다(보내면 화면 전체가 다시 실행되며 깜빡임). 확대 한계: 가장 축소 = 도면 전체 + 여백 30%, 가장 확대 = 가장 작은 방 하나. 점 테두리는 모두 같은 얇은 선(검토 대상은 표·카드로 구분).
- 내려받기 버튼에 넘기는 함수는 누를 때 화면 실행 밖에서 돌므로 `st.cache_data`·`st.progress`·`st.session_state`를 쓰지 말고 `views/shared.py`의 `memo`를 씁니다(안 그러면 "missing ScriptRunContext" 경고가 쏟아짐).
- 「새 분석」 뒤 올린 파일은 같은 파일이어도 새 작업으로 쌓입니다. 새 접속(재시작 등)이면 마지막 작업을 자동으로 엽니다(`open_last_job`).
- 설정 맨 아래 **미리보기 모드**(`user_settings.json`의 `ui.preview_mode`, `slab/settings_store.py`의 `load_ui`/`save_ui`)를 켜면 `app.py`가 꾸밈 없는 화면(`views/preview.py`, 주소 `pg_*_v01`)으로 바꿉니다. 계산·보고서·엑셀 코드는 같아야 합니다. 작업마다 저장하는 `Settings`에는 넣지 않습니다.
- **LAS 변환**(`slab/las.py`, 화면 `views/las.py`, 명령 `python -m slab.las`, 휴대용 `LAS_TO_GRID.bat`): 층마다 한 LAS/LAZ(1GB+)를 조금씩(`CHUNK`) 읽어 모든 층에 **같은 격자**(건물 축 방향, `grid.json`에 저장·재사용)의 바닥·천장 Z 를 `grid_analysis_floor_level_<층>.csv` 형식으로 냅니다. 메뉴는 별도 그룹 「데이터 준비」. 파일은 올리지 않고 서버 PC 의 폴더 경로로 읽으므로 그 PC(localhost)에서 쓰는 기능입니다(원격 접속이면 `st.context.ip_address`로 알아 '이 PC 에서만 쓸 수 있음' 안내만 보이고 멈춤). 1차 훑기는 파일 전체의 5 %(최소 1000만 점)만 건너뛰며 읽고(`iter_points(sample=True)`), 2차 훑기는 점을 모아 두지 않고 1 mm 높이 분포(`_SurfaceHist`)로 쌓아 14 GB 파일도 메모리가 일정합니다. 격자점 ±0.1 m 안을 벽 단면 점이 `WALL_NODE_MIN`개 넘게 지나가면 '벽 위'(`on_wall`)로 바닥·천장 값을 비웁니다(벽이 덮어 슬라브 면을 잴 수 없음, 두께 분석에서 미산출). 변환 기록 `LSATS_grid/manifest.json`(층마다 LAS 크기·수정 시각·요약, `ALGO_VERSION`)으로 같은 파일·설정·격자면 다시 읽지 않고, 화면은 폴더를 열면 `stored_result`로 전 결과를 바로 보여 줍니다(계산 방식이 바뀌면 `ALGO_VERSION`을 올리세요). LAZ 는 laspy 가 여러 코어로 풀고(LazrsParallel), 디스크 읽기가 병목이라 따로 병렬 처리는 하지 않습니다. 2차 훑기 때 벽 단면(바닥 위 1.0~1.5 m)·바닥면 점을 5 cm 칸에 쌓아 층마다 `LAS_평면도_<층>.dxf`(스캔된 곧은 벽 면을 제자리 선으로·벽 띠(`wall_bands`: 마주 본 두 면 사이, 짝 없는 면은 바닥이 적은 바깥쪽으로 칸막이벽 두께 중앙값만큼 — 그림용 추정, `벽` 레이어 해치만 써서 두께 분석이 방으로 읽지 않음)·값이 있는 격자점만(`has_data`, 값 없는 점은 CSV 에만)과 높이, 건물 축 기준 mm, `slab/las_plan.py`)도 만듭니다. **방 배치**(`views/las_rooms.py`, `slab/las_layout.py`): 변환 때 층마다 `plan_<층>.npz`(벽·바닥 칸)를 저장하고, 벽 위치가 겹치는 비율로 층을 구조별로 묶어(`group_floors`, 0.55 이상 같은 구조) 실무자가 층마다 구조를 고칩니다. 구조마다 방(서로 겹치지 않는 가로·세로 변 다각형 + 이름, 건물 축 m)을 자동 나누기 초안 → 방 편집기(`views/room_editor.py`, CCv2 캔버스: 빈 곳 끌기=새 방, 방 클릭 선택·끌어 이동·변 끌어 경계 이동, 변 우클릭 → 「여기서 벽면 나누기」(같은 점 두 개를 넣어 한쪽 조각만 끌 수 있게, 저장 때 `clean_poly`로 남은 점 정리), 「방 위에 새 방 그리기」, 「방에서 빼기」(네모만큼 깎아 바로 저장, 가운데면 구멍 — 바깥과 곧은 다리로 이은 한 줄 다각형, `subtract_rect`), 꺾인 곳 우클릭 「벽면 합치기」, 벽 면에 자석처럼 붙음, 겹친 칸은 저장 때 마지막에 그리거나 고친 방 쪽으로 `resolve_overlaps`, 브라우저 안에서만 편집하고 「저장」 때만 Python 으로 보냄) → 표에서 이름 고치기로 정해 `LSATS_grid/layouts.json`에 두고, 같은 구조의 모든 층 DXF 의 `ROOM_BOUNDARY` 레이어에 넣습니다. DXF 에 격자점 이름(`G001-001`)이 있어 `core.POINT_LABEL_RE`가 P점처럼 읽어 측량 좌표에 자동으로 맞춥니다(좌표 맞춤 불필요). 방 이름은 '호수_실명'으로 쓰면 세대별로 묶입니다. CSV 의 `grid_angle_deg`·`grid_origin_*`로 `core.grid_alignment`가 도면 없이도 건물 축에 맞춰 정렬합니다. 설정은 `Settings.las_*`. 화면은 「폴더 선택」으로 OS 기본 폴더 선택 창(Windows 탐색기식 IFileOpenDialog·PowerShell / Mac `osascript choose folder`, `views/las.py`의 `native_pick`, 경로 붙여넣기도 됨) → 파일 체크 → 변환 → 결과 → 저장(층마다/한 파일, CSV/엑셀, `las.export_results`). 마지막 연 폴더·저장 폴더는 `user_settings.json`의 `ui.las_last_folder`/`ui.las_out_folder`(`update_ui`). 입력 칸 값은 그 칸을 그린 뒤 바꿀 수 없으니 폴더 이동은 콜백이나 화면 맨 위에서 합니다. 미리보기 모드에선 메뉴·설정 탭을 숨깁니다.
- 층별 엑셀은 받은 결과 엑셀 양식(`슬라브 두께 결과`: 제목·분포도·40행부터 표 / `포인트 위치도`)을 따르고 `방별 두께도`를 더합니다. 전체 층은 요약 엑셀 + 층별 엑셀 ZIP(`slab/report.py`의 `build_all`).
- 보고서 영역은 `slab/report_html.py`의 `SECTIONS`/`PRESETS`에 추가합니다.
- `.bat` 파일은 CRLF 줄바꿈과 ASCII 문자만 씁니다 (`.gitattributes`로 고정되어 있습니다).
- 프로그램을 모르는 사용자에게는 README 0장의 휴대용 ZIP(`START.bat`)을 안내합니다. 빌드는 `packaging/`과 `.github/workflows/release.yml`(태그 `v*` push)로 합니다. 릴리스에는 전체 ZIP과 프로그램 파일만 담은 `L-SATS-update.zip`이 함께 올라가고, 설치된 폴더의 `UPDATE.bat`이 이것을 받아 바꿉니다. `requirements.txt`를 바꾸면 사용자는 전체 ZIP을 다시 받아야 합니다(UPDATE.bat이 알아서 안내). `packaging/update.ps1`은 Windows PowerShell 5.1용이라 ASCII 문자만 씁니다.
