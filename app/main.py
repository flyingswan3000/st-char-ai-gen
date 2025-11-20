import asyncio
import json
import logging
from pathlib import Path
from typing import AsyncGenerator, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .job_manager import JobManager, JobStatus
from .llm_client import LLMClient, LLMProvider
from .png_utils import embed_ccv3_json, extract_ccv3_json, is_png_data
from .utils import build_card_from_response, format_card_for_export

settings = get_settings()
llm_client = LLMClient(settings)
job_manager = JobManager(keep_max=10)
logger = logging.getLogger(__name__)
DEFAULT_CARD_IMAGE = Path(__file__).resolve().parent / "assets" / "default_card.png"

app = FastAPI(title="SillyTavern JSON 產生器", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR)), name="assets")


@app.get("/")
async def read_index():
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        return JSONResponse({"message": "前端尚未建立"}, status_code=404)
    return FileResponse(index_path)


@app.get("/job.html")
async def read_job_page():
    job_page = FRONTEND_DIR / "job.html"
    if not job_page.exists():
        return JSONResponse({"message": "任務頁面尚未建立"}, status_code=404)
    return FileResponse(job_page)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/api/generate")
async def generate_card(
    provider: str = Form("openai"),
    input_text: str = Form(""),
    file: Optional[UploadFile] = File(None),
):
    payload = input_text.strip()
    if file is not None:
        file_bytes = await file.read()
        try:
            file_text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            file_text = file_bytes.decode("utf-8", errors="ignore")
        if payload:
            payload = f"{payload}\n\n{file_text}"
        else:
            payload = file_text

    if not payload:
        raise HTTPException(status_code=400, detail="請提供文字或上傳檔案")

    chosen_provider = LLMProvider.from_label(provider)

    try:
        raw_output, usage = await llm_client.generate_card(chosen_provider, payload)
        key_data = build_card_from_response(raw_output)
        export_payload = format_card_for_export(key_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "provider": chosen_provider.value,
        "card": export_payload,
        "raw": raw_output,
        "token_usage": usage,
    }


async def _process_job(job_id: str) -> None:
    try:
        meta = job_manager.mark_running(job_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("無法更新 Job 狀態：%s", exc)
        return

    try:
        payload = job_manager.read_input(job_id)
        provider = LLMProvider.from_label(meta.provider)

        def handle_stream(text: str) -> None:
            job_manager.append_stream(job_id, text)

        raw_output, usage = await llm_client.generate_card(
            provider, payload, on_stream=handle_stream
        )
        key_data = build_card_from_response(raw_output)
        export_payload = format_card_for_export(key_data)
        base_image = job_manager.read_base_image(job_id)
        if base_image is None and DEFAULT_CARD_IMAGE.exists():
            base_image = DEFAULT_CARD_IMAGE.read_bytes()
        png_bytes = None
        if base_image is not None:
            try:
                png_bytes = embed_ccv3_json(base_image, export_payload)
            except ValueError as exc:
                logger.warning("嵌入 PNG 失敗 job=%s error=%s", job_id, exc)
        job_manager.complete_job(job_id, raw_output, export_payload, usage, png_bytes=png_bytes)
    except ValueError as exc:
        job_manager.fail_job(job_id, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("背景任務失敗：%s", exc)
        job_manager.fail_job(job_id, f"伺服器錯誤：{exc}")


@app.post("/api/jobs")
async def create_job(
    provider: str = Form("openai"),
    input_text: str = Form(""),
    file: Optional[UploadFile] = File(None),
):
    payload = input_text.strip()
    base_image_bytes: Optional[bytes] = None
    if file is not None:
        file_bytes = await file.read()
        if is_png_data(file_bytes):
            base_image_bytes = file_bytes
            extracted = extract_ccv3_json(file_bytes)
            if extracted:
                payload = f"{payload}\n\n{extracted}" if payload else extracted
        else:
            try:
                file_text = file_bytes.decode("utf-8")
            except UnicodeDecodeError:
                file_text = file_bytes.decode("utf-8", errors="ignore")
            payload = f"{payload}\n\n{file_text}" if payload else file_text

    if not payload:
        raise HTTPException(status_code=400, detail="請提供文字或上傳檔案")

    chosen_provider = LLMProvider.from_label(provider)
    job = job_manager.create_job(chosen_provider.value, payload, base_image=base_image_bytes)
    asyncio.create_task(_process_job(job.id))
    return {
        "job_id": job.id,
        "provider": chosen_provider.value,
        "redirect_url": f"/job.html?id={job.id}",
    }


@app.get("/api/jobs")
async def list_jobs():
    return job_manager.list_jobs()


@app.get("/api/jobs/{job_id}")
async def job_detail(job_id: str):
    try:
        detail = job_manager.get_job_detail(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="找不到指定任務") from exc
    return detail


@app.get("/api/jobs/{job_id}/download")
async def download_job(job_id: str):
    try:
        meta = job_manager.get_meta(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="找不到指定任務") from exc

    if meta.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="此任務尚未完成")

    result_path = job_manager.result_file_path(job_id)
    if result_path is None:
        raise HTTPException(status_code=404, detail="結果不存在")

    filename = f"{job_id}.json"
    return FileResponse(result_path, media_type="application/json", filename=filename)


@app.get("/api/jobs/{job_id}/download.png")
async def download_job_png(job_id: str):
    try:
        meta = job_manager.get_meta(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="找不到指定任務") from exc

    if meta.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="此任務尚未完成")

    png_path = job_manager.png_file_path(job_id)
    if png_path is None:
        raise HTTPException(status_code=404, detail="PNG 檔案不存在")

    filename = f"{job_id}.png"
    return FileResponse(png_path, media_type="image/png", filename=filename)


@app.get("/api/jobs/{job_id}/stream")
async def stream_job(job_id: str, offset: int = 0) -> StreamingResponse:
    try:
        job_manager.get_meta(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="找不到指定任務") from exc

    async def event_generator(start_offset: int) -> AsyncGenerator[str, None]:
        current_offset = max(start_offset, 0)
        while True:
            try:
                chunk, next_offset = job_manager.read_stream_chunk(job_id, current_offset)
            except FileNotFoundError:
                error_payload = json.dumps(
                    {"type": "status", "status": JobStatus.FAILED, "error": "任務已被移除"},
                    ensure_ascii=False,
                )
                yield f"id: {current_offset}\ndata: {error_payload}\n\n"
                break
            if chunk:
                current_offset = next_offset
                payload = json.dumps({"type": "chunk", "content": chunk}, ensure_ascii=False)
                yield f"id: {current_offset}\ndata: {payload}\n\n"
            try:
                meta = job_manager.get_meta(job_id)
            except FileNotFoundError:
                error_payload = json.dumps(
                    {"type": "status", "status": JobStatus.FAILED, "error": "任務已被移除"},
                    ensure_ascii=False,
                )
                yield f"id: {current_offset}\ndata: {error_payload}\n\n"
                break
            if meta.status in {JobStatus.COMPLETED, JobStatus.FAILED}:
                payload = json.dumps(
                    {
                        "type": "status",
                        "status": meta.status,
                        "error": meta.error,
                        "token_usage": meta.token_usage,
                    },
                    ensure_ascii=False,
                )
                yield f"id: {current_offset}\ndata: {payload}\n\n"
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(offset), media_type="text/event-stream")
