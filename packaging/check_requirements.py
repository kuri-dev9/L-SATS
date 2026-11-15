"""휴대용 Python 에 설치된 패키지가 새 requirements.txt 를 만족하는지 확인한다 (UPDATE.bat 용).

만족하면 0, 아니면 부족한 패키지를 출력하고 1 을 돌려준다.
"""
import sys
from importlib.metadata import PackageNotFoundError, version

from packaging.requirements import Requirement


def main(path: str) -> int:
    missing = []
    for line in open(path, encoding="utf-8"):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        req = Requirement(line)
        try:
            v = version(req.name)
        except PackageNotFoundError:
            missing.append(f"{req.name} (not installed)")
            continue
        if not req.specifier.contains(v, prereleases=True):
            missing.append(f"{req.name} {v} (needs {req.specifier})")
    for m in missing:
        print("  - " + m)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
