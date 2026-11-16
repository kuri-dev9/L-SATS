# 개발 인계 프롬프트 (v0.2.0)

> 다른 개발자나 AI 개발 도구에 그대로 전달하는 프롬프트입니다. 먼저 `AGENTS.md`와 `README.md`를 읽게 하세요.

---

이 저장소(L-SATS, 레이저 스캔 기반 실별 슬래브 두께 산출 Streamlit 앱)를 이어서 개발해 주세요.
**실사용자는 Windows PC**에서 휴대용 ZIP(`START.bat`)이나 `run.bat`으로 씁니다. 개발은 macOS에서 해도 되지만,
Windows 배포(`packaging/`, `.github/workflows/`)가 깨지지 않게 하세요. 먼저 `AGENTS.md`와 `README.md`를 읽고,
`python -m pytest`로 기준 상태(64개 통과)를 확인한 뒤 시작하세요.

## 1. 지금 상태 (v0.2.0)

### 계산 (`slab/`)
- 두께(mm) = (상부층 `floor_z` − 하부층 `ceiling_z`) × 1000. 층간 대응은 **XY 좌표**로만 합니다(포인트 번호로 병합 금지).
- 대응 순서(`Settings.method="auto"`): 상부 격자 교차점에서 가장 가까운 하부 격자 교차점이 **1.2 m**(담당자 확인값) 안에 있고
  정상 천장점이면 **직접 대응** → 아니면 정상 하부점으로 만든 **TIN 보간**(삼각형 밖은 외삽 금지) → 둘 다 안 되면 **미산출**.
- TIN 근거(세 하부점 ID·X·Y·Z·가중치)를 포인트마다 `tin_*` 열로 보존합니다. 실패 사유는 삼각형 밖·퇴화·3점 미만·너무 큰 삼각형으로 나눕니다.
- 상태는 `산출 / 제외 / 미산출`. 미산출 두께는 NaN(0으로 채우지 않음). 사유는 `exclude_reason`, 참고 사항은 `review_note`.
- 하부점 재사용 허용(기본) 또는 가까운 쌍부터 1:1 배정. 단위(m/mm) 자동 판별, 한 파일 안 혼합 단위는 오류로 알림.
- 방 집계는 고유 `room_id` 기준(같은 이름의 다른 방을 합치지 않음). 세대 ID는 실명에서 추출(`7호_거실`→`7호`, `코아2_EV홀`→`코아2`, 그 외 `공용`).
  경계선 위 점은 그 방에, 경계 중첩은 검토 메모(설정으로 제외 가능), 방 밖은 **영역외**로 따로 세고 평균·판정에서 뺍니다.
- 판정: **방 평균 135 mm 이상이면 통과(허용 오차 0) — 고정**. 1 nm 단위 반올림으로 부동소수 잡음이 경계 판정을 뒤집지 않게 했습니다.
- 이상치: MAD(기본 5배) 또는 IQR, "두꺼운 쪽만" 옵션, 두께 하한·상한(기본 사용 안 함), 기준면 편차 30 mm.

### 출력
- 엑셀 기본 2시트(`포인트 결과` + `위치도` 40%), 틀고정 없음, 적합률은 앱에만, '검토 전 참고용 초안' 문구. 설정에서 전체 시트 구성으로 바꿀 수 있음.
- HTML 보고서(간단/상세, 영역 선택, 초안 표시), DXF(결과 레이어 + 방 평균), CSV, ZIP 묶음.
- 그림: 방 색은 방 평균 판정(통과 초록/미달 빗금 빨강, `slab/plot.py`의 `STATUS`), 점 색은 개별 두께. 3D 방 상자는 윗면·아랫면을 모두 막은 닫힌 상자.

### 화면 (`app.py` + `views/`)
- 왼쪽 메뉴: **홈**(`dashboard.py`) · **두께 분석**(`analysis.py`) · **보고서·내려받기**(`report.py`) · **작업 내역**(`jobs.py`) · **설정**(`settings.py`, 맨 아래).
- 공유 상태는 `views/shared.py`(`compute()`): 올린 파일·동/층·레이어·열 지정·방 이름을 세션에 두어 화면을 옮겨도 남습니다. 열린 작업은 URL `?job=<ID>`로 새로고침에도 유지됩니다.
- **데모 데이터는 화면에 자동으로 띄우지 않습니다.** `demo_data/`는 테스트용입니다.
- 색·여백은 `.streamlit/config.toml`의 `[theme]`(남색 사이드바, 파랑 강조). 사이드바의 현재 작업 표시는 일부러 수수하게 두었습니다(색 배지 없음).

### 설정·작업 내역 (JSON)
- 설정: 프로그램 폴더 `user_settings.json`. 항목·설명은 `slab/settings_store.py`의 `FIELDS` 한 곳. 판정 기준은 파일에 써도 무시됩니다.
- 작업 내역: `work_history/history.json` + `work_history/files/<ID>/`(입력 파일 사본). 계산되면 자동 저장되고, 작업마다 그때 설정을 함께 저장합니다
  (다시 열면 같은 결과, 설정이 바뀌었으면 「지금 설정으로 다시 계산」). 홈·작업 내역에서 열기, 작업 내역에서 이름·동·층·메모 수정과 삭제(확인 창).
- 두 파일 모두 `UPDATE.bat`이 건드리지 않습니다(새 버전 ZIP에 없는 파일). 커밋하지 않습니다(`.gitignore`).

## 2. 지켜야 할 것
- 판정 기준(방 평균 135 mm, 허용 오차 0)을 화면·설정에서 바꿀 수 있게 만들지 마세요.
- 계산은 `slab/`, 화면은 `views/`. 바꿀 수 있는 값은 `Settings` + `FIELDS`에 추가하고, 미확정 값은 `pending=True`.
- 실제 현장 데이터(`sample_data/`)는 커밋 금지. 이 폴더의 CSV/DXF가 원본 형식 기준입니다. 결과(미달 여부)에 맞춰 계산을 바꾸지 말고 계산의 정확성만 검증하세요.
- `.bat`은 CRLF·ASCII, `packaging/update.ps1`은 PowerShell 5.1용 ASCII. 새 폴더를 만들면 `packaging/build_windows.ps1`과 `packaging/make_zips.py`의 필수 목록에 넣으세요.
- Python 3.11도 CI 대상입니다. f-string 안에서 바깥과 같은 따옴표를 다시 쓰지 마세요(3.12 문법).
- 화면 문구는 처음 쓰는 사람 기준의 쉬운 말. 앱 실행 확인은 포트 8501(이미 떠 있으면 기존 서버를 끄고 같은 포트로 재시작).
- 테스트는 `LSATS_SETTINGS`/`LSATS_HISTORY`로 임시 위치를 씁니다(`tests/conftest.py`). 새 기능에는 테스트를 붙이세요.

## 3. 남은 일
1. 담당자 확인 대기(`pending=True`): TIN 삼각형 최대 변 길이, 두께 하한·상한(요청값 "140 mm"의 의미 — 판정 기준과 별개).
2. Windows 실기기에서 휴대용 ZIP 확인: 첫 실행, 작업 내역 저장 위치, `UPDATE.bat` 뒤 `work_history`·`user_settings.json` 유지, 한글 파일 이름.
3. 엑셀 위치도 40%와 인쇄 PDF를 Windows Excel·브라우저에서 눈으로 확인.
4. 작업 내역이 많아질 때(수백 건) 목록 속도와 디스크 사용량 점검, 필요하면 오래된 작업 정리 기능.
5. `views/report.py` 미리보기 폭은 1.1 : 3 비율 — 실제 화면에서 사용자 확인 필요.

## 4. 실행·검증
```bat
run.bat                                   :: 처음 실행 시 .venv 설치 후 http://localhost:8501
.venv\Scripts\python.exe -m pytest        :: 64개 (sample_data 없으면 9개 건너뜀)
.venv\Scripts\python.exe -m streamlit run app.py --server.headless true
```
릴리스: `slab/__init__.py`의 `__version__`을 올리고 `v*` 태그를 push하면 `.github/workflows/release.yml`이 전체 ZIP과 업데이트 ZIP을 만듭니다.
