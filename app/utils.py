import json
import re
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from .models import CharacterCore

CODE_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)
DEFAULT_SPEC = "chara_card_v3"
DEFAULT_SPEC_VERSION = "3.0"


def extract_json_from_text(raw: str) -> str:
    """
    嘗試從 LLM 回傳的文字中抓出第一段 JSON。
    """
    text = raw.strip()
    fence_match = CODE_FENCE_PATTERN.search(text)
    if fence_match:
        return fence_match.group(1).strip()

    brace_match = JSON_OBJECT_PATTERN.search(text)
    if brace_match:
        return brace_match.group(0).strip()

    return text


def build_card_from_response(raw_content: str) -> CharacterCore:
    json_payload = extract_json_from_text(raw_content)
    try:
        parsed: Any = json.loads(json_payload)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM 回傳內容不是有效的 JSON") from exc

    try:
        return CharacterCore.model_validate(parsed)
    except ValidationError as exc:
        raise ValueError(f"關鍵欄位格式不正確: {exc}") from exc


def _clean_dict(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if v is not None}


def format_card_for_export(core: CharacterCore) -> dict:
    """依照 SillyTavern 實際匯入的 JSON 範本輸出。"""
    ts = datetime.utcnow()
    ms = int(ts.microsecond / 1000)
    timestamp = f"{ts:%Y-%m-%d @%Hh %Mm %Ss} {ms:03d}ms"
    character_book = (
        core.character_book.model_dump() if core.character_book is not None else None
    )
    data = _clean_dict(
        {
            "name": core.name,
            "description": core.description,
            "personality": core.personality,
            "scenario": core.scenario,
            "first_mes": core.first_mes,
            "mes_example": core.mes_example,
            "creator_notes": core.creator_notes,
            "system_prompt": core.system_prompt,
            "post_history_instructions": core.post_history_instructions,
            "alternate_greetings": core.alternate_greetings,
            "character_book": character_book,
            "tags": core.tags,
            "creator": core.creator,
            "character_version": core.character_version,
            "extensions": core.extensions,
        }
    )

    export_payload = {
        "name": core.name,
        "description": core.description,
        "personality": core.personality,
        "first_mes": core.first_mes,
        "avatar": "none",
        "mes_example": core.mes_example,
        "scenario": core.scenario,
        "create_date": timestamp,
        "talkativeness": "0.5",
        "fav": False,
        "creatorcomment": "",
        "spec": DEFAULT_SPEC,
        "spec_version": DEFAULT_SPEC_VERSION,
        "data": data,
        "tags": core.tags,
    }

    return export_payload
