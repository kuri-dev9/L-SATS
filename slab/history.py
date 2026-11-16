"""작업 내역 저장 (JSON).

- 목록: 프로그램 폴더의 work_history/history.json (환경변수 LSATS_HISTORY 로 폴더 변경)
- 입력 파일: work_history/files/<작업 ID>/ 에 그대로 복사해 두어, 나중에 같은 결과를 다시 열 수 있다.
UPDATE.bat 은 새 버전에 들어 있는 파일만 바꾸므로 이 폴더는 업데이트해도 남는다.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path

KINDS = ("cad", "upper", "lower")


def history_dir() -> Path:
    env = os.environ.get("LSATS_HISTORY")
    return Path(env) if env else Path(__file__).resolve().parents[1] / "work_history"


def _index() -> Path:
    return history_dir() / "history.json"


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def digest(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def list_jobs() -> list[dict]:
    """최근에 고친 작업이 앞에 온다."""
    try:
        jobs = json.loads(_index().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    jobs = [j for j in jobs if isinstance(j, dict) and "id" in j] if isinstance(jobs, list) else []
    return sorted(jobs, key=lambda j: j.get("updated", ""), reverse=True)


def _write(jobs: list[dict]) -> None:
    d = history_dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = _index().with_suffix(".tmp")
    tmp.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_index())  # 쓰다가 꺼져도 목록 파일이 깨지지 않게


def get_job(job_id: str) -> dict | None:
    return next((j for j in list_jobs() if j["id"] == job_id), None)


def _save_files(job_id: str, files: dict[str, tuple[str, bytes]]) -> dict:
    folder = history_dir() / "files" / job_id
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    out = {}
    for kind, (name, data) in files.items():
        if kind not in KINDS:
            continue
        (folder / f"{kind}_{Path(name).name}").write_bytes(data)
        out[kind] = {"name": Path(name).name, "md5": digest(data)}
    return out


def create_job(files: dict[str, tuple[str, bytes]], record: dict) -> str:
    job_id = _dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    job = {"id": job_id, "name": "", "memo": "", **record, "created": _now(), "updated": _now(),
           "files": _save_files(job_id, files)}
    _write([*list_jobs(), job])
    return job_id


def update_job(job_id: str, files: dict[str, tuple[str, bytes]] | None = None, **fields) -> bool:
    """필드를 고친다. files 가 주어지고 저장된 파일과 다르면 파일도 바꾼다. 바뀐 게 있으면 True."""
    jobs = list_jobs()
    job = next((j for j in jobs if j["id"] == job_id), None)
    if job is None:
        return False
    changed = {k: v for k, v in fields.items() if job.get(k) != v}
    if files is not None:
        want = {k: {"name": Path(n).name, "md5": digest(d)} for k, (n, d) in files.items() if k in KINDS}
        if want != job.get("files"):
            changed["files"] = _save_files(job_id, files)
    if not changed:
        return False
    job.update(changed)
    job["updated"] = _now()
    _write(jobs)
    return True


def delete_job(job_id: str) -> None:
    _write([j for j in list_jobs() if j["id"] != job_id])
    shutil.rmtree(history_dir() / "files" / job_id, ignore_errors=True)


def load_files(job_id: str) -> dict[str, tuple[str, bytes]]:
    """저장해 둔 입력 파일 {종류: (원래 이름, 바이트)}. 없어진 파일은 빠진다."""
    job = get_job(job_id)
    if job is None:
        return {}
    folder = history_dir() / "files" / job_id
    out = {}
    for kind, info in job.get("files", {}).items():
        p = folder / f"{kind}_{info['name']}"
        if p.exists():
            out[kind] = (info["name"], p.read_bytes())
    return out


def display_name(job: dict) -> str:
    if job.get("name"):
        return job["name"]
    floors = "-".join(x for x in (job.get("upper_floor"), job.get("lower_floor")) if x)
    return " ".join(x for x in (job.get("dong"), floors) if x) or job.get("files", {}).get("upper", {}).get(
        "name", "이름 없는 작업")
