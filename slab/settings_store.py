"""설정 페이지에서 바꾸는 값의 설명과 저장(user_settings.json).

- 통과/미달 판정 기준은 두지 않는다(두께 현황 파악이 목적). 예전 파일의 design_mm 등 모르는 값은 무시한다.
- 저장 파일은 프로그램 폴더의 user_settings.json (환경변수 LSATS_SETTINGS 로 위치 변경).
  UPDATE.bat 은 새 버전에 들어 있는 파일만 바꾸므로 이 파일은 업데이트해도 남는다.
- pending=True 는 담당자 확인 전이라 기본값이 확정되지 않은 항목이다 (설정 페이지에 표시).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path

from .core import Settings

FIXED: tuple[str, ...] = ()  # 화면에서 바꾸지 않는 값 (지금은 없음)


@dataclass(frozen=True)
class Field:
    key: str
    group: str
    label: str
    help: str
    options: dict | None = None  # 고르기 항목: 값 -> 화면 이름
    min: float | None = None
    max: float | None = None
    step: float | None = None
    pending: bool = False


GROUPS = {
    "match": "위·아래층 점 맞추기",
    "units": "입력 단위",
    "exclude": "결과 상태 기준",
    "rooms": "방·세대 나누기",
    "output": "그림·엑셀·보고서",
}

FIELDS: list[Field] = [
    Field("method", "match", "맞추는 방법",
          "직접 대응 우선: 같은 위치(허용 거리 안)의 아래층 점을 먼저 쓰고, 없으면 주변 세 점으로 만든 "
          "삼각형(TIN)으로 천장 높이를 구합니다. 삼각형 밖은 추정하지 않습니다.",
          {"auto": "직접 대응 우선 → 실패 시 TIN", "nearest": "직접 대응만", "interpolate": "TIN 보간만"}),
    Field("max_match_dist_m", "match", "위·아래층 격자점 최대 거리 (m)",
          "위층 격자 교차점에서 가장 가까운 아래층 격자 교차점까지의 수평 거리입니다. 이보다 멀면 직접 대응하지 "
          "않고 주변 세 점(TIN)으로 계산합니다. 1.5m 격자 기준 1.2m (담당자 확인값).", None, 0.01, 5.0, 0.05),
    Field("allow_reuse", "match", "아래층 점 하나를 여러 위층 점에 써도 됨",
          "끄면 가까운 쌍부터 1:1로 짝지어, 이미 쓴 아래층 점은 다시 쓰지 않습니다(남은 점은 TIN)."),
    Field("tin_max_edge_m", "match", "TIN 삼각형 가장 긴 변 한도 (m, 0=제한 없음)",
          "이보다 큰 삼각형으로는 보간하지 않습니다. 측정점이 듬성듬성한 곳을 걸러냅니다.",
          None, 0.0, 20.0, 0.1, True),
    Field("tin_cross_room", "match", "다른 방의 아래층 점을 쓴 경우",
          "벽을 사이에 둔 점으로 계산했을 수 있습니다.",
          {"warn": "검토 메모만 남김", "exclude": "미산출로 처리"}),
    Field("xy_unit", "units", "좌표(X·Y) 단위",
          "자동: 측정점 간격으로 판단합니다(간격이 20 넘으면 mm).", {"auto": "자동", "m": "m", "mm": "mm"}),
    Field("z_unit", "units", "높이(Z) 단위",
          "자동: 층고(천장-바닥)로 판단합니다(100 넘으면 mm). 한 파일 안에서 단위가 섞이면 알려 줍니다.",
          {"auto": "자동", "m": "m", "mm": "mm"}),
    Field("max_surface_error_mm", "exclude", "기준면에서 벗어난 정도 (mm) → 미산출 'Z값 확인 필요'",
          "바닥·천장이 층 기준 높이보다 이만큼 높거나 낮으면 바닥 위 물건·천장 설비 등으로 보고 두께를 비워 둡니다.",
          None, 1.0, 1000.0, 1.0),
    Field("review_above_mm", "exclude", "'두께 범위 검토' 기준 (mm 이상)",
          "두께가 이 값 이상이면 '두께 범위 검토'로 표시합니다. 값은 그대로 보여 주지만 방 평균에는 넣지 않습니다. "
          "받은 결과 엑셀 기준 140mm.", None, 0.0, 2000.0, 1.0, True),
    Field("low_limit_mm", "exclude", "'두께 비정상(하한 이하)' 기준 (mm 이하)",
          "두께가 이 값 이하이면 측정 오류로 보고 '두께 비정상(하한 이하)'로 표시합니다. 받은 결과 엑셀 기준 0mm.",
          None, -1000.0, 1000.0, 1.0, True),
    Field("outlier_method", "exclude", "'이상치 검토' 방식",
          "주변과 두께가 크게 다른 점을 '이상치 검토'로 표시합니다. MAD: 두께 중앙값에서 얼마나 떨어졌는지로 판단(기본). "
          "IQR: 두께를 순서대로 놓고 가운데 절반(25%~75%)의 폭을 기준으로, 그 폭의 몇 배 넘게 벗어나면 표시합니다.",
          {"mad": "MAD (중앙값 기준)", "iqr": "IQR (사분위 범위)", "none": "사용 안 함"}),
    Field("outlier_scope", "exclude", "이상치를 무엇과 비교할지",
          "같은 방: 방 안의 점끼리 비교합니다(받은 결과 엑셀과 같음). 층 전체: 그 층의 모든 점과 비교합니다.",
          {"room": "같은 방의 점끼리", "all": "층 전체 점과"}),
    Field("outlier_min_points", "exclude", "이상치를 따질 최소 점 수",
          "비교할 점이 이보다 적으면 이상치를 따지지 않습니다.", None, 3, 50, 1),
    Field("outlier_mad_k", "exclude", "MAD 배수", "클수록 덜 표시합니다. 받은 결과 엑셀 기준 3.5.", None, 0.5, 20.0, 0.5),
    Field("outlier_iqr_k", "exclude", "IQR 배수",
          "IQR 방식을 고를 때만 씁니다. 보통 1.5이고, 클수록 덜 표시합니다.", None, 0.5, 10.0, 0.1),
    Field("outlier_side", "exclude", "이상치로 볼 쪽",
          "'두꺼운 쪽만'이면 실제로 얇은 곳이 이상치로 표시되지 않습니다.",
          {"both": "얇은 쪽·두꺼운 쪽 모두", "thick": "두꺼운 쪽만"}),
    Field("unit_pattern", "rooms", "세대 ID 찾는 규칙 (정규식)",
          "방 이름에서 세대를 뽑습니다. 기본값은 '101호_거실' → '101호', '코아2_EV홀' → '코아2'."),
    Field("unit_fallback", "rooms", "세대 ID가 없을 때 이름", "예: 공용"),
    Field("overlap_policy", "rooms", "방 경계가 겹친 곳의 점",
          "도면에서 두 방 경계가 겹치는 곳에 있는 점을 어떻게 할지 정합니다.",
          {"smallest": "작은 방에 넣고 검토 메모", "exclude": "미산출로 처리"}),
    Field("boundary_tol_mm", "rooms", "경계선 위로 볼 거리 (mm)",
          "방 경계선에서 이 거리 안의 점은 그 방에 넣습니다.", None, 0.0, 500.0, 1.0),
    Field("color_min_mm", "output", "두께 색 막대 시작 (mm, 초록)",
          "위치도의 색 막대 양 끝입니다. 이보다 얇으면 가장 진한 초록으로 칠합니다. 모든 층에 같은 색 기준을 씁니다.",
          None, -1000.0, 2000.0, 1.0),
    Field("color_max_mm", "output", "두께 색 막대 끝 (mm, 주황)",
          "이보다 두꺼우면 가장 진한 주황으로 칠합니다.", None, -1000.0, 2000.0, 1.0),
    Field("map_px_per_m", "output", "포인트 위치도 그림 해상도 (1m 당 픽셀)",
          "클수록 엑셀 위치도의 이름표가 크고 선명하지만 파일이 커집니다.", None, 60, 400, 10),
    Field("excel_layout", "output", "엑셀 구성",
          "", {"basic": "결과 + 포인트 위치도 + 방별 두께도", "full": "위 + 방별 현황·계산 상세·설정 (전체)"}),
    Field("excel_room_map", "output", "엑셀에 방별 두께도(서브 자료) 넣기", "도면(DXF)이 있을 때만 들어갑니다."),
    Field("excel_tin_detail", "output", "계산 상세에 TIN 세 점·가중치 열 펼치기",
          "전체 구성의 '계산 상세' 시트에 TIN 보간에 쓴 아래층 세 점의 번호·좌표·높이·가중치를 넣습니다."),
    Field("report_draft", "output", "'검토 전 초안' 표시",
          "실측 기준점과 비교해 검증하기 전에는 켜 두세요."),
    Field("report_draft_text", "output", "초안 표시 문구", ""),
]

FIELD_BY_KEY = {f.key: f for f in FIELDS}


def settings_path() -> Path:
    env = os.environ.get("LSATS_SETTINGS")
    return Path(env) if env else Path(__file__).resolve().parents[1] / "user_settings.json"


def _coerce(key: str, value, default):
    f = FIELD_BY_KEY.get(key)
    if isinstance(default, bool):
        return bool(value)
    if isinstance(default, int):
        v = int(round(float(value)))
    elif isinstance(default, float):
        v = float(value)
    else:
        v = str(value)
        if f and f.options and v not in f.options:
            raise ValueError(key)
        return v
    if f and f.min is not None:
        v = max(v, type(default)(f.min))
    if f and f.max is not None:
        v = min(v, type(default)(f.max))
    return v


def from_dict(data: dict) -> tuple[Settings, list[str]]:
    """사전에서 설정을 만든다. 잘못된 값은 기본값을 쓰고 키 목록을 돌려준다."""
    base = Settings()
    vals, bad = {}, []
    for fl in fields(Settings):
        if fl.name in FIXED or fl.name not in data:
            continue
        try:
            vals[fl.name] = _coerce(fl.name, data[fl.name], getattr(base, fl.name))
        except (TypeError, ValueError):
            bad.append(fl.name)
    return replace(base, **vals), bad


def to_dict(s: Settings) -> dict:
    return {k: v for k, v in asdict(s).items() if k not in FIXED}


def load_settings(path: Path | None = None) -> Settings:
    p = path or settings_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    return from_dict(data if isinstance(data, dict) else {})[0]


def _read(p: Path) -> dict:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(s: Settings, path: Path | None = None) -> Path:
    p = path or settings_path()
    data = {**to_dict(s)}
    ui = _read(p).get(UI_KEY)
    if isinstance(ui, dict):
        data[UI_KEY] = ui  # 화면 설정은 그대로 둔다
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


# ------------------------------------------------------------------ 화면 설정 (계산과 무관)
# 작업마다 저장하는 계산 설정(Settings)과 달리, 화면을 어떻게 보일지만 정한다. 바꿔도 작업 결과는 그대로다.
UI_KEY = "ui"
UI_DEFAULTS = {"preview_mode": False}


def load_ui(path: Path | None = None) -> dict:
    ui = _read(path or settings_path()).get(UI_KEY)
    out = dict(UI_DEFAULTS)
    if isinstance(ui, dict):
        out.update({k: bool(ui[k]) for k in UI_DEFAULTS if k in ui})
    return out


def save_ui(ui: dict, path: Path | None = None) -> Path:
    p = path or settings_path()
    data = _read(p)
    data[UI_KEY] = {k: bool(ui.get(k, v)) for k, v in UI_DEFAULTS.items()}
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def changed(s: Settings) -> dict:
    """기본값과 다른 항목만."""
    d, base = to_dict(s), to_dict(Settings())
    return {k: v for k, v in d.items() if base.get(k) != v}
