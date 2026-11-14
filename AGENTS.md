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
- 테스트는 14개가 모두 통과해야 합니다 (`test.bat`으로도 실행 가능).
- `demo_data/`는 `tools/make_demo_data.py`로 만든 가상 데이터입니다. 실제 현장 데이터(`sample_data/` 등)는 공개 저장소이므로 커밋하지 마세요.

macOS/Linux: `./run.sh`, 또는 `.venv/bin/python`으로 같은 명령을 실행합니다.

## 핵심 규칙

- 두께(mm) = (상부층 `floor_z` − 하부층 `ceiling_z`) × 1000. `floor_z`는 콘크리트 윗면입니다.
- 상·하부층은 같은 측량 기준점이지만 **포인트 번호와 격자 배치가 다릅니다.** `point_id`로 병합하지 말고 XY 좌표로 대응시킵니다.
- DXF는 mm 단위 도면 좌표, CSV는 m 단위 측량 좌표(회전되어 있음, 데모 데이터는 23.5°)입니다. 변환은 도면의 측정점 라벨(P001…)로 구합니다.
- 계산 로직은 `slab/` 패키지에 두고, `app.py`는 화면만 담당합니다.
- 화면은 처음 쓰는 사람 기준입니다. 첫 화면에는 ① 파일 올리기 → ② 결과(통과/미달 판정) → ③ 파일 받기만 두고, 전문 설정·상세 표는 「자세히 보기」에 둡니다. 쉬운 말을 쓰세요.
- `.bat` 파일은 CRLF 줄바꿈과 ASCII 문자만 씁니다 (`.gitattributes`로 고정되어 있습니다).
- 프로그램을 모르는 사용자에게는 README 0장의 휴대용 ZIP(`START.bat`)을 안내합니다. 빌드는 `packaging/`과 `.github/workflows/release.yml`(태그 `v*` push)로 합니다.
