# L-SATS · 레이저 스캔 기반 실별 슬래브 두께 자동 산출

상·하부층 레이저 스캔 그리드 데이터와 통합 CAD 도면(DXF)으로 **실(방)별 슬래브 두께**를 계산하고,
설계 두께 대비 적합/미달을 판정해 **Excel 결과표와 DXF 도면**으로 출력하는 웹 프로그램입니다.
**Windows PC**에서 실행합니다.

```
   8F 바닥 (콘크리트 윗면)   ← 상부층 스캔 floor_z
 ████████████████████████    ← 슬래브
   7F 천장                   ← 하부층 스캔 ceiling_z

   두께(mm) = (상부층 floor_z − 하부층 ceiling_z) × 1000
```

---

## 0. 가장 쉬운 실행 방법 (프로그램을 몰라도 됩니다)

Python 설치 없이 **받고 → 압축 풀고 → 더블클릭**만 하면 됩니다.

1. **[여기를 눌러 L-SATS-windows.zip 받기](https://github.com/kuri-dev9/L-SATS/releases/latest/download/L-SATS-windows.zip)** (약 150~200MB)
2. 받은 파일을 **마우스 오른쪽 클릭 → 「압축 풀기」(또는 「모두 압축 풀기」) → 「압축 풀기」**
   - 바탕화면처럼 평범한 곳에 풀어 주세요. ZIP 파일 안에서 바로 실행하면 안 됩니다.
3. 풀린 `L-SATS` 폴더 안의 **`START.bat`을 더블클릭**
   - 「Windows의 PC 보호」 파란 창이 뜨면 **「추가 정보」 → 「실행」** 을 누릅니다.
4. 10~30초 뒤 브라우저에 프로그램이 열립니다. **검은 창은 사용하는 동안 닫지 마세요.** 끝낼 때 닫으면 됩니다.

처음 열면 가상 데모 데이터로 결과가 보입니다. 실제 분석은 맨 위 「① 파일 올리기」에 도면(DXF) 1개와 스캔 파일(CSV) 2개를 올리면 됩니다.

> 아래 1장 이후는 Python을 직접 설치해서 실행하거나 프로그램을 고치려는 분을 위한 내용입니다.

---

## 1. Windows에서 실행하기 (Python 직접 설치)

### 1-1. Python 설치 (처음 한 번)

1. https://www.python.org/downloads/windows/ 에서 **Python 3.11 이상**(권장 3.13)의 *Windows installer (64-bit)* 를 받습니다.
2. 설치 첫 화면에서 **`Add python.exe to PATH`를 반드시 체크**하고 *Install Now*를 누릅니다.

### 1-2. 프로그램 받기

- **Git이 있으면:**
  ```bat
  git clone https://github.com/kuri-dev9/L-SATS.git
  ```
- **Git이 없으면:** 저장소 페이지에서 **Code → Download ZIP**으로 받아 압축을 풉니다.

### 1-3. 실행

폴더 안의 **`run.bat`을 더블클릭**합니다.

- 처음 한 번은 필요한 패키지를 설치하느라 1~3분 걸립니다. 인터넷 연결이 필요합니다.
- 설치가 끝나면 브라우저에 `http://localhost:8501`이 자동으로 열립니다.
- 파일을 올리지 않으면 **데모 데이터(가상 8F/7F)** 로 결과를 바로 보여줍니다.
- 끝내려면 검은 명령 창을 닫습니다.

명령 프롬프트에서 직접 실행할 때 (`run.bat`과 같은 동작):

```bat
cd L-SATS
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m streamlit run app.py
```

> PowerShell에서 `Activate.ps1` 실행이 막히는 경우가 많습니다. 위처럼 `.venv\Scripts\python.exe`를 직접 호출하면 활성화 없이 실행됩니다.

### 1-4. 같은 사무실의 다른 PC에서 접속

```bat
run.bat --server.address 0.0.0.0
```

다른 PC 브라우저에서 `http://<실행 중인 PC의 IP>:8501`로 접속합니다. Windows 방화벽 허용 창이 뜨면 *허용*을 누릅니다.

### 1-5. 문제 해결

| 증상 | 해결 |
|---|---|
| `START.bat`이 바로 꺼짐 / `"python" folder is missing` | ZIP 안에서 실행한 경우입니다. 0장의 2번대로 압축을 먼저 푸세요 |
| 「Windows의 PC 보호」 창 | 「추가 정보」 → 「실행」 |
| `Python 3.11 or later is required` | 1-1대로 Python을 설치하고 `Add python.exe to PATH`를 체크했는지 확인 |
| 실행하면 Microsoft Store가 열림 | Windows의 가짜 `python` 바로가기입니다. 1-1대로 python.org 설치본을 설치하세요 |
| `Installation failed` | 인터넷·회사 프록시 확인 후 다시 실행. 계속 실패하면 `.venv` 폴더를 지우고 다시 실행 |
| 브라우저가 안 열림 | 브라우저에서 `http://localhost:8501` 직접 입력 |
| `Port 8501 is already in use` | 이미 실행 중인 창이 있습니다. 그 창을 닫거나 `run.bat --server.port 8502` |
| 위치도의 한글이 □로 보임 | Windows는 맑은 고딕을 자동으로 씁니다. Linux 서버라면 `sudo apt install fonts-nanum` |

---

## 2. 사용 방법

화면은 위에서 아래로 세 단계입니다.

| 단계 | 하는 일 |
|---|---|
| **① 파일 올리기** | 도면(DXF), 위층 스캔, 아래층 스캔 파일 3개를 올리고 동·층 이름, 설계 두께(기본 135mm), 허용 오차(기본 10mm)를 확인합니다. 파일을 올리기 전에는 연습용 데모 데이터가 보입니다. |
| **② 결과 한눈에 보기** | 맨 위에 **「모든 방 통과」(초록)** 또는 **「N개 방이 설계보다 얇아요」(빨강)** 가 크게 나옵니다. 아래에 평균 두께, 통과한 방 수, 방별 결과표(얇은 방이 위), 위치도가 있습니다. |
| **③ 결과 파일 받기** | 버튼 한 번으로 엑셀 보고서, CAD 도면(DXF), 포인트 목록(CSV)을 받습니다. |

맨 아래 **「자세히 보기」** 는 담당자용입니다. 보통은 건드리지 않아도 됩니다.

| 탭 | 내용 |
|---|---|
| 방 이름 고치기 | 도면의 방 이름이 틀렸거나 비어 있을 때(예: `실_08`) 새 이름 입력 |
| 포인트별 결과 | 측정점마다 두께·판정·좌표, 방별 상세 통계 |
| 제외된 측정점 | 자동으로 뺀 점과 이유 (바닥 위 물건, 천장 설비 등) |
| 계산 설정·도면 정합 | 위·아래층 점 맞추는 방법, 이상값 제외 기준, 입력 파일 열 지정, 방 경계 레이어, 도면↔측량 좌표 맞춤 결과 |

### 결과 파일

| 파일 | 내용 |
|---|---|
| Excel (`101동_8F-7F_슬래브두께.xlsx`) | `요약`(설정·통계), `실별 결과`, `포인트별 결과`, `제외 포인트`(사유 포함), `위치도`(그림) |
| DXF | 원본 도면 + 결과 레이어 `두께_적합`(초록), `두께_미달`(빨강), `두께_제외`(회색), `두께_실평균` |
| CSV | 포인트별 결과 (Excel에서 열리는 UTF-8 BOM) |

### 명령줄 실행 (화면 없이 일괄 처리)

```bat
.venv\Scripts\python.exe -m slab demo_data\grid_analysis_floor_level_8F.csv demo_data\grid_analysis_floor_level_7F.csv ^
  --cad demo_data\report_merge_8F.dxf -o 결과.xlsx --dxf-output 결과.dxf ^
  --design 135 --tolerance 10 --dong 101동 --upper-floor 8F --lower-floor 7F
```

옵션: `--method nearest|interpolate`. 전체 옵션은 `python -m slab -h`로 볼 수 있습니다.

---

## 3. 입력 파일

### 3-1. 상부층 / 하부층 스캔 (CSV, XLSX)

`grid_analysis_floor_level_*.csv` 형식을 기본으로 읽습니다. 열 이름이 다르면 화면의 **열 매핑**에서 지정합니다.
CSV 인코딩은 UTF-8과 CP949(한글 Excel 저장)를 모두 지원합니다.

| 열 | 의미 | 필수 |
|---|---|---|
| `point_id` | 포인트 번호 (층마다 따로 매겨짐) | |
| `x`, `y` | 측량 좌표 (m). 상·하부층이 **같은 측량 기준점** | ✔ |
| `floor_z` | 바닥 높이 (m), **콘크리트 윗면**. 상부층 값 사용 | ✔ (상부층) |
| `ceiling_z` | 천장 높이 (m). 하부층 값 사용 | ✔ (하부층) |
| `floor_error`, `ceiling_error` | 층 기준면 대비 편차 (m). 없으면 층 중앙값 대비 편차로 계산 | |
| `has_floor`, `has_ceiling`, `is_empty` | 측정 유무 플래그 | |

### 3-2. 통합 CAD (DXF)

| 요소 | 조건 |
|---|---|
| 실 경계 | 닫힌 폴리라인 (기본 레이어 `ROOM_BOUNDARY`, 화면에서 변경 가능) |
| 실명 | 실 경계 **안쪽**의 TEXT/MTEXT, 실 경계와 **같은 레이어** (예: `8호_거실`) |
| 측정점 라벨 | 상부층 포인트 번호 문자(`P001`…)와 원(CIRCLE). **3개 이상** 필요 |

측정점 라벨은 도면 좌표(mm, 회전 없음)를 측량 좌표(m, 회전됨)로 맞추는 기준점으로 씁니다.
도면이 이미 측량 좌표로 그려져 있다면 라벨이 없어도 됩니다.

---

## 4. 계산 방법

1. **대응점 매칭.** 상·하부층은 같은 측량 기준점을 쓰지만 **격자 배치와 포인트 번호가 층마다 다릅니다.**
   예를 들어 같은 위치가 8F에서는 `P001`, 7F에서는 `P007`입니다. 그래서 **번호가 아니라 XY 좌표**로 대응시킵니다.
   - **최근접 대응점**(기본): 상부층 점마다 가장 가까운 하부층 점의 `ceiling_z`를 씁니다.
   - **하부 천장면 보간**: 하부층 천장점으로 삼각망 면을 만들어 상부층 점 위치의 천장 높이를 계산합니다.
     층마다 격자 간격이나 방향이 크게 다를 때 씁니다.
2. **두께.** `(floor_z − ceiling_z) × 1000` mm
3. **이상값 자동 제외.** 제외한 점은 사유와 함께 결과에 남깁니다. 기준값은 화면에서 바꿀 수 있습니다.

   | 제외 사유 | 기준 (기본값) |
   |---|---|
   | 상부 바닥 측정 없음 | `has_floor=False` 또는 `is_empty=True` |
   | 하부층 대응점 없음 | 가장 가까운 하부층 점이 0.2 m보다 멂 |
   | 상부 바닥 이상 (바닥 위 물체 등) | 바닥 기준면 대비 편차가 30 mm보다 큼 |
   | 하부 천장 이상 (설비·돌출물 등) | 천장 기준면 대비 편차가 30 mm보다 큼 |
   | 두께 통계 이상치 | 중앙값에서 5×MAD 이상 벗어남 |

4. **실 배정.** 도면의 측정점 라벨로 도면↔측량 좌표 변환(축척·회전·이동)을 최소제곱으로 구하고,
   각 점이 들어가는 실 경계를 찾습니다. 경계 밖의 점은 `(실 외부)`로 집계합니다.
5. **판정.**
   - 포인트: `두께 ≥ 설계 − 허용 부족량`이면 **적합**, 아니면 **미달**
   - 실: 유효점의 **평균** 두께에 같은 기준을 적용

기본값은 **설계 135 mm, 허용 부족량 10 mm**입니다. 허용 부족량은 임시값이므로 현장 기준이 정해지면 화면에서 바꾸세요.

### 데모 데이터

저장소에는 실제 현장 데이터가 들어 있지 않습니다. 대신 `tools/make_demo_data.py`로 만든 **가상 데이터**가
`demo_data/`에 있습니다. 실제 데이터와 같은 형식이고, 실제처럼 층마다 격자 위치·포인트 번호가 어긋나 있으며,
바닥 위 물체·천장 설비 같은 이상값도 섞여 있습니다.

| 항목 | 값 (최근접 대응점 기준) |
|---|---|
| 구성 | 2세대 8실 (`실_08`은 실명 문자가 없는 경계 → 실명 편집 예시) |
| 포인트 | 상부층 58점 중 유효 46점, 제외 12점 |
| 두께 | 평균 130.2 mm, 범위 118~141 mm |
| 판정 | `101호_침실2`(평균 약 120 mm)만 미달, 나머지 7실 적합 |
| 도면 정합 | 회전 23.5°, 잔차 RMS 0.4 mm |

데모 데이터를 다시 만들려면 `.venv\Scripts\python.exe tools\make_demo_data.py`를 실행합니다. 결과는 항상 같습니다.

실제 현장 데이터는 공개 저장소에 올리지 마세요. 로컬 `sample_data/` 폴더는 `.gitignore`에 들어 있어 커밋되지 않습니다.

---

## 5. 개발자용

### 폴더 구조

```
app.py                 Streamlit 웹 화면 (화면만 담당)
slab/core.py           입력 읽기, CAD 해석, 좌표 정합, 대응점 매칭, 두께·판정·실별 집계
slab/plot.py           포인트 위치도 (matplotlib)
slab/report.py         Excel·DXF 결과 생성
slab/__main__.py       명령줄 실행 (python -m slab)
demo_data/             가상 데모 입력 (8F/7F)
tools/make_demo_data.py 데모 데이터 생성기
tests/                 pytest (계산 로직 + 웹 화면 스모크 테스트)
run.bat / run.sh       원클릭 실행 (Windows / macOS·Linux, Python 필요)
packaging/             Python 포함 Windows 휴대용 ZIP 빌드 (START.bat, build_windows.ps1)
test.bat               Windows 테스트 실행
.streamlit/config.toml 업로드 한도 500MB 등 Streamlit 설정
.github/workflows/     GitHub Actions: Windows·Ubuntu 테스트 + run.bat 실행 검증
```

### 테스트

```bat
test.bat
```

macOS/Linux: `pip install -r requirements-dev.txt && pytest`

GitHub에 push하면 Actions가 **Windows**와 Ubuntu에서 테스트를 돌리고, Windows에서 `run.bat`으로 실제 서버가 뜨는지도 확인합니다.

### Windows 휴대용 ZIP 배포

`v`로 시작하는 태그를 push하면 `release-windows` 워크플로가 Windows에서 Python 포함 ZIP을 만들고,
압축을 풀어 `START.bat`이 실제로 뜨는지 확인한 뒤 GitHub Releases에 올립니다.

```bash
git tag v0.1.1 && git push origin v0.1.1
```

0장의 다운로드 링크는 항상 최신 Release를 가리킵니다. 새 버전을 낼 때는 `slab/__init__.py`의 `__version__`도 함께 올립니다.

### 요구 사항

- Python 3.11 ~ 3.14 (휴대용 ZIP은 3.14 포함)
- 패키지: `requirements.txt` (streamlit, pandas, numpy, scipy, ezdxf, matplotlib, openpyxl)
