from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union


class JobStatus(str):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ts() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


@dataclass
class JobRecord:
    id: str
    provider: str
    status: str
    created_at: str
    updated_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    error: Optional[str]
    stream_filename: str
    input_filename: str
    raw_filename: Optional[str]
    result_filename: Optional[str]
    token_usage: Optional[Dict[str, Union[int, float]]]
    base_image_filename: Optional[str] = None
    png_filename: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "provider": self.provider,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "stream_filename": self.stream_filename,
            "input_filename": self.input_filename,
            "raw_filename": self.raw_filename,
            "result_filename": self.result_filename,
            "token_usage": self.token_usage,
            "base_image_filename": self.base_image_filename,
            "png_filename": self.png_filename,
        }


class JobManager:
    def __init__(self, root: Optional[Path] = None, keep_max: int = 10):
        base_dir = Path(__file__).resolve().parent.parent
        self.root = root or (base_dir / "tmp" / "jobs")
        self.keep_max = max(keep_max, 1)
        self.root.mkdir(parents=True, exist_ok=True)

    # ---------- File helpers ----------
    def _job_dir(self, job_id: str) -> Path:
        return self.root / job_id

    def _meta_path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "meta.json"

    def _read_meta(self, job_id: str) -> JobRecord:
        meta_path = self._meta_path(job_id)
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return JobRecord(**data)

    def _write_meta(self, job: JobRecord) -> None:
        job.updated_at = _ts()
        meta_path = self._meta_path(job.id)
        meta_path.write_text(json.dumps(job.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- Public helpers ----------
    def create_job(self, provider: str, payload: str, base_image: Optional[bytes] = None) -> JobRecord:
        job_id = uuid.uuid4().hex
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        stream_filename = "stream.log"
        input_filename = "input.txt"
        (job_dir / input_filename).write_text(payload, encoding="utf-8")
        (job_dir / stream_filename).write_text("", encoding="utf-8")
        base_image_filename = None
        if base_image:
            base_image_filename = "base_image.png"
            (job_dir / base_image_filename).write_bytes(base_image)
        now = _ts()
        job = JobRecord(
            id=job_id,
            provider=provider,
            status=JobStatus.PENDING,
            created_at=now,
            updated_at=now,
            started_at=None,
            completed_at=None,
            error=None,
            stream_filename=stream_filename,
            input_filename=input_filename,
            raw_filename=None,
            result_filename=None,
            token_usage=None,
            base_image_filename=base_image_filename,
            png_filename=None,
        )
        self._write_meta(job)
        self._housekeep()
        return job

    def mark_running(self, job_id: str) -> JobRecord:
        job = self._read_meta(job_id)
        if job.status == JobStatus.RUNNING:
            return job
        job.status = JobStatus.RUNNING
        job.started_at = job.started_at or _ts()
        self._write_meta(job)
        return job

    def get_meta(self, job_id: str) -> JobRecord:
        return self._read_meta(job_id)

    def append_stream(self, job_id: str, text: str) -> None:
        if not text:
            return
        job = self._read_meta(job_id)
        stream_path = self._job_dir(job_id) / job.stream_filename
        with stream_path.open("a", encoding="utf-8") as handle:
            handle.write(text)

    def complete_job(
        self,
        job_id: str,
        raw_output: str,
        export_payload: Dict[str, object],
        token_usage: Optional[Dict[str, Union[int, float]]],
        png_bytes: Optional[bytes] = None,
    ) -> JobRecord:
        job = self._read_meta(job_id)
        job.status = JobStatus.COMPLETED
        job.completed_at = _ts()
        job.error = None
        job.token_usage = token_usage
        raw_filename = "raw.txt"
        result_filename = "result.json"
        job.raw_filename = raw_filename
        job.result_filename = result_filename
        if png_bytes:
            png_filename = "card.png"
            (self._job_dir(job_id) / png_filename).write_bytes(png_bytes)
            job.png_filename = png_filename
        job_dir = self._job_dir(job_id)
        (job_dir / raw_filename).write_text(raw_output, encoding="utf-8")
        (job_dir / result_filename).write_text(
            json.dumps(export_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._write_meta(job)
        return job

    def fail_job(self, job_id: str, error: str) -> JobRecord:
        job = self._read_meta(job_id)
        job.status = JobStatus.FAILED
        job.completed_at = _ts()
        job.error = error
        self._write_meta(job)
        return job

    def read_input(self, job_id: str) -> str:
        job = self._read_meta(job_id)
        return (self._job_dir(job_id) / job.input_filename).read_text(encoding="utf-8")

    def read_stream(self, job_id: str) -> Tuple[str, int]:
        job = self._read_meta(job_id)
        stream_path = self._job_dir(job_id) / job.stream_filename
        if not stream_path.exists():
            return "", 0
        data = stream_path.read_text(encoding="utf-8")
        return data, stream_path.stat().st_size

    def read_stream_chunk(self, job_id: str, offset: int) -> Tuple[str, int]:
        job = self._read_meta(job_id)
        stream_path = self._job_dir(job_id) / job.stream_filename
        if not stream_path.exists():
            return "", offset
        with stream_path.open("rb") as handle:
            handle.seek(offset)
            chunk = handle.read()
            new_offset = handle.tell()
        if not chunk:
            return "", offset
        return chunk.decode("utf-8", errors="ignore"), new_offset

    def read_result(self, job_id: str) -> Optional[Dict[str, object]]:
        job = self._read_meta(job_id)
        if not job.result_filename:
            return None
        result_path = self._job_dir(job_id) / job.result_filename
        if not result_path.exists():
            return None
        return json.loads(result_path.read_text(encoding="utf-8"))

    def result_file_path(self, job_id: str) -> Optional[Path]:
        job = self._read_meta(job_id)
        if not job.result_filename:
            return None
        path = self._job_dir(job_id) / job.result_filename
        if not path.exists():
            return None
        return path

    def png_file_path(self, job_id: str) -> Optional[Path]:
        job = self._read_meta(job_id)
        if not job.png_filename:
            return None
        path = self._job_dir(job_id) / job.png_filename
        if not path.exists():
            return None
        return path

    def read_base_image(self, job_id: str) -> Optional[bytes]:
        job = self._read_meta(job_id)
        if not job.base_image_filename:
            return None
        path = self._job_dir(job_id) / job.base_image_filename
        if not path.exists():
            return None
        return path.read_bytes()

    def read_raw(self, job_id: str) -> Optional[str]:
        job = self._read_meta(job_id)
        if not job.raw_filename:
            return None
        raw_path = self._job_dir(job_id) / job.raw_filename
        if not raw_path.exists():
            return None
        return raw_path.read_text(encoding="utf-8")

    def get_job_detail(self, job_id: str) -> Dict[str, object]:
        job = self._read_meta(job_id)
        stream_text, stream_offset = self.read_stream(job_id)
        input_text = self.read_input(job_id)
        result = self.read_result(job_id)
        raw = self.read_raw(job_id)
        png_exists = self.png_file_path(job_id) is not None
        return {
            "meta": job.to_dict(),
            "input_text": input_text,
            "stream_text": stream_text,
            "stream_offset": stream_offset,
            "result": result,
            "raw_output": raw,
            "png_available": png_exists,
        }

    def list_jobs(self) -> Dict[str, List[Dict[str, object]]]:
        metas: List[JobRecord] = []
        for item in sorted(self.root.iterdir() if self.root.exists() else [], key=lambda p: p.name):
            meta_path = item / "meta.json"
            if not meta_path.exists():
                continue
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                metas.append(JobRecord(**data))
            except Exception:  # noqa: BLE001
                continue
        metas.sort(key=lambda m: m.created_at, reverse=True)
        in_progress = [m.to_dict() for m in metas if m.status in {JobStatus.PENDING, JobStatus.RUNNING}]
        completed = [m.to_dict() for m in metas if m.status in {JobStatus.COMPLETED, JobStatus.FAILED}]
        return {"in_progress": in_progress, "completed": completed}

    def _housekeep(self) -> None:
        job_dirs = []
        for path in self.root.iterdir():
            meta_path = path / "meta.json"
            if not meta_path.exists():
                continue
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            job_dirs.append((data.get("created_at", ""), data.get("status"), path))

        if len(job_dirs) <= self.keep_max:
            return

        job_dirs.sort(key=lambda item: item[0])  # oldest first
        removable = [entry for entry in job_dirs if entry[1] in {JobStatus.COMPLETED, JobStatus.FAILED}]

        total = len(job_dirs)
        idx = 0
        while total > self.keep_max and idx < len(removable):
            _, _, target = removable[idx]
            shutil.rmtree(target, ignore_errors=True)
            total -= 1
            idx += 1
