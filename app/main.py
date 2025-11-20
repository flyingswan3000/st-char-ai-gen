from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .llm_client import LLMClient, LLMProvider
from .utils import build_card_from_response, format_card_for_export

settings = get_settings()
llm_client = LLMClient(settings)

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
