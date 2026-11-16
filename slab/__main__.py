"""명령줄 실행: python -m slab 상부층.csv 하부층.csv --cad 도면.dxf -o 결과.xlsx"""
import argparse
import sys
from dataclasses import replace
from pathlib import Path

from . import analyze, load_cad, load_grid
from .report import build_dxf, build_excel, rooms_table
from .settings_store import load_settings


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m slab", description="실별 슬래브 두께 자동 산출")
    p.add_argument("upper", help="상부층 스캔 CSV/XLSX (바닥 Z 사용)")
    p.add_argument("lower", help="하부층 스캔 CSV/XLSX (천장 Z 사용)")
    p.add_argument("--cad", help="통합 CAD DXF (실 경계 + 실명 + 상부층 측정점 라벨)")
    p.add_argument("-o", "--output", default="슬래브두께_결과.xlsx", help="Excel 결과 경로")
    p.add_argument("--dxf-output", help="결과 DXF 경로 (지정 시 저장)")
    p.add_argument("--method", choices=["auto", "nearest", "interpolate"],
                   help="대응 방식 (기본: 설정 페이지에 저장한 값)")
    p.add_argument("--dong", default="", help="동 (예: 101동)")
    p.add_argument("--upper-floor", default="", help="상부층 (예: 8F)")
    p.add_argument("--lower-floor", default="", help="하부층 (예: 7F)")
    a = p.parse_args()
    # Windows 콘솔(cp949 등)에서 출력할 수 없는 문자가 있어도 중단되지 않게 한다
    sys.stdout.reconfigure(errors="replace")

    settings = load_settings()  # 설정 페이지에 저장한 값
    if a.method:
        settings = replace(settings, method=a.method)
    plan = load_cad(a.cad) if a.cad else None
    result = analyze(load_grid(a.upper), load_grid(a.lower), plan, settings)
    meta = {"동": a.dong, "상부층": a.upper_floor, "하부층": a.lower_floor}

    Path(a.output).write_bytes(build_excel(result, meta))
    if a.dxf_output:
        Path(a.dxf_output).write_bytes(build_dxf(result))

    sm = result.summary
    print(rooms_table(result).to_string(index=False))
    print(f"\n산출 완료 {sm['n_valid']}/{sm['n_points']}점, 평균 {sm['mean_mm']:.1f}mm, "
          f"검토 {sm['n_review']}점, 미산출 {sm['n_no_value']}점, 영역 외 {sm['n_outside']}점")
    print(f"저장: {a.output}" + (f", {a.dxf_output}" if a.dxf_output else ""))


if __name__ == "__main__":
    main()
