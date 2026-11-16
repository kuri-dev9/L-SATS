"""설정 페이지에서 바꾸는 값의 설명과 저장(user_settings.json).

- 판정 기준(방 평균 135mm 이상, 허용 오차 0)은 고정이라 여기 없다. 파일에 적혀 있어도 무시한다.
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

FIXED = ("design_mm", "tolerance_mm")


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
    "exclude": "이상한 측정값 제외",
    "rooms": "방·세대 나누기",
    "output": "엑셀·보고서",
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
          {"warn": "검토 메모만 남김", "exclude": "계산에서 제외"}),
    Field("xy_unit", "units", "좌표(X·Y) 단위",
          "자동: 측정점 간격으로 판단합니다(간격이 20 넘으면 mm).", {"auto": "자동", "m": "m", "mm": "mm"}),
    Field("z_unit", "units", "높이(Z) 단위",
          "자동: 층고(천장-바닥)로 판단합니다(100 넘으면 mm). 한 파일 안에서 단위가 섞이면 알려 줍니다.",
          {"auto": "자동", "m": "m", "mm": "mm"}),
    Field("max_surface_error_mm", "exclude", "기준면에서 벗어난 정도 (mm)",
          "바닥·천장이 층 기준 높이보다 이만큼 높거나 낮으면 바닥 위 물건·천장 설비 등으로 보고 제외합니다.",
          None, 1.0, 1000.0, 1.0),
    Field("outlier_method", "exclude", "통계 이상치 방식",
          "다른 점들과 두께가 크게 다른 점을 뺍니다. MAD: 두께 중앙값에서 얼마나 떨어졌는지로 판단(기본). "
          "IQR: 두께를 순서대로 놓고 가운데 절반(25%~75%)의 폭을 기준으로, 그 폭의 몇 배 넘게 벗어나면 뺍니다.",
          {"mad": "MAD (중앙값 기준)", "iqr": "IQR (사분위 범위)", "none": "사용 안 함"}),
    Field("outlier_mad_k", "exclude", "MAD 배수", "클수록 덜 뺍니다.", None, 0.5, 20.0, 0.5),
    Field("outlier_iqr_k", "exclude", "IQR 배수",
          "IQR 방식을 고를 때만 씁니다. 보통 1.5이고, 클수록 덜 뺍니다.", None, 0.5, 10.0, 0.1),
    Field("outlier_side", "exclude", "이상치로 뺄 쪽",
          "'두꺼운 쪽만'이면 실제로 얇은 곳이 이상치로 지워지지 않습니다.",
          {"both": "얇은 쪽·두꺼운 쪽 모두", "thick": "두꺼운 쪽만"}),
    Field("min_thickness_mm", "exclude", "두께 하한 (mm, 0=사용 안 함)",
          "이보다 얇은 값은 측정 오류로 보고 제외합니다. 판정 기준(135mm)과는 별개입니다.",
          None, 0.0, 1000.0, 1.0, True),
    Field("max_thickness_mm", "exclude", "두께 상한 (mm, 0=사용 안 함)",
          "이보다 두꺼운 값은 측정 오류로 보고 제외합니다. 담당자 요청값 140mm의 뜻 확인 필요 — "
          "판정 기준(135mm)과는 별개입니다.", None, 0.0, 2000.0, 1.0, True),
    Field("unit_pattern", "rooms", "세대 ID 찾는 규칙 (정규식)",
          "방 이름에서 세대를 뽑습니다. 기본값은 '101호_거실' → '101호', '코아2_EV홀' → '코아2'."),
    Field("unit_fallback", "rooms", "세대 ID가 없을 때 이름", "예: 공용"),
    Field("overlap_policy", "rooms", "방 경계가 겹친 곳의 점",
          "도면에서 두 방 경계가 겹치는 곳에 있는 점을 어떻게 할지 정합니다.",
          {"smallest": "작은 방에 넣고 검토 메모", "exclude": "계산에서 제외"}),
    Field("boundary_tol_mm", "rooms", "경계선 위로 볼 거리 (mm)",
          "방 경계선에서 이 거리 안의 점은 그 방에 넣습니다.", None, 0.0, 500.0, 1.0),
    Field("excel_layout", "output", "엑셀 구성",
          "", {"simple": "포인트 결과 + 위치도 (2시트)", "full": "요약·방별·포인트·제외·판정도·위치도 (전체)"}),
    Field("excel_map_scale_pct", "output", "엑셀 위치도 그림 크기 (%)",
          "그림 크기 비율입니다. CAD 도면 축척과는 관계없습니다.", None, 10, 200, 5),
    Field("excel_freeze_panes", "output", "엑셀 첫 행 틀고정", ""),
    Field("excel_show_pass_rate", "output", "엑셀에 적합률 표시", "끄면 적합률은 프로그램 화면에만 나옵니다."),
    Field("excel_tin_detail", "output", "TIN 세 점·가중치 열 펼치기",
          "포인트 결과에 TIN 보간에 쓴 아래층 세 점의 번호·좌표·높이·가중치를 넣습니다."),
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


def save_settings(s: Settings, path: Path | None = None) -> Path:
    p = path or settings_path()
    p.write_text(json.dumps(to_dict(s), ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def changed(s: Settings) -> dict:
    """기본값과 다른 항목만."""
    d, base = to_dict(s), to_dict(Settings())
    return {k: v for k, v in d.items() if base.get(k) != v}
