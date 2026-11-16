"""휴대용 폴더(dist/L-SATS)에 VERSION 을 쓰고, 전체 ZIP 과 업데이트용 ZIP 을 만든다.

- L-SATS-windows.zip: 폴더 전체 (Python 포함)
- L-SATS-update.zip: python 폴더를 뺀 프로그램 파일만 (UPDATE.bat 이 받는다)
사용: python make_zips.py dist/L-SATS v0.1.5
"""
import sys
import zipfile
from pathlib import Path


def write_zip(pkg: Path, out: Path, skip_python: bool) -> list[str]:
    names = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(pkg.rglob("*")):
            rel = f.relative_to(pkg)
            if "__pycache__" in rel.parts or (skip_python and rel.parts[0] == "python"):
                continue
            arc = (Path(pkg.name) / rel).as_posix()
            z.write(f, arc)
            names.append(arc)
    return names


def main(pkg: str, version: str) -> None:
    pkg_dir = Path(pkg).resolve()
    (pkg_dir / "VERSION").write_text(version, encoding="ascii")
    dist = pkg_dir.parent
    full = dist / "L-SATS-windows.zip"
    update = dist / "L-SATS-update.zip"
    write_zip(pkg_dir, full, skip_python=False)
    names = write_zip(pkg_dir, update, skip_python=True)
    print(f"full   {full.stat().st_size / 2**20:.0f} MB")
    print(f"update {update.stat().st_size / 2**20:.2f} MB")
    print(*names, sep="\n")
    for need in ("VERSION", "app.py", "views/analysis.py", "views/settings.py", "views/plan_viewer.py",
                 "views/preview.py", "views/las.py", "slab/core.py", "slab/batch.py", "slab/las.py", "LAS_TO_GRID.bat",
                 "tools/update.ps1", "requirements.txt"):
        assert f"{pkg_dir.name}/{need}" in names, need


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
