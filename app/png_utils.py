from __future__ import annotations

import base64
import json
import logging
import zlib
from typing import Dict, Optional, Tuple, Union, overload

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHARACTER_CHUNK_KEYWORDS = (b"ccv3", b"chara")
logger = logging.getLogger(__name__)


def is_png_data(data: bytes) -> bool:
    return len(data) >= len(PNG_SIGNATURE) and data.startswith(PNG_SIGNATURE)


@overload
def extract_ccv3_json(data: bytes) -> Optional[str]:
    ...


@overload
def extract_ccv3_json(data: bytes, *, include_reason: bool) -> Tuple[Optional[str], Optional[str]]:
    ...


def extract_ccv3_json(
    data: bytes,
    *,
    include_reason: bool = False,
) -> Union[Optional[str], Tuple[Optional[str], Optional[str]]]:
    extracted, reason = _extract_ccv3_payload(data)
    if reason:
        logger.warning("解析 PNG 內的 ccv3 chunk 失敗：%s", reason)
    if include_reason:
        return extracted, reason
    return extracted


def _build_chunk(chunk_type: bytes, chunk_data: bytes) -> bytes:
    length = len(chunk_data).to_bytes(4, "big")
    crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
    return length + chunk_type + chunk_data + crc.to_bytes(4, "big")


def embed_ccv3_json(base_image: bytes, card_payload: Dict[str, object]) -> bytes:
    if not is_png_data(base_image):
        raise ValueError("提供的圖片不是有效的 PNG/APNG")

    json_bytes = json.dumps(card_payload, ensure_ascii=False).encode("utf-8")
    encoded = base64.b64encode(json_bytes)
    new_chunk = _build_chunk(b"tEXt", b"ccv3" + b"\x00" + encoded)

    output = bytearray()
    output.extend(base_image[: len(PNG_SIGNATURE)])
    pos = len(PNG_SIGNATURE)
    total = len(base_image)
    inserted = False

    while pos + 8 <= total:
        length = int.from_bytes(base_image[pos : pos + 4], "big")
        chunk_type = base_image[pos + 4 : pos + 8]
        chunk_start = pos
        chunk_end = pos + 8 + length + 4
        chunk_bytes = base_image[chunk_start:chunk_end]
        pos = chunk_end

        if chunk_type == b"tEXt":
            chunk_data = base_image[chunk_start + 8 : chunk_start + 8 + length]
            keyword = chunk_data.split(b"\x00", 1)[0]
            if keyword == b"ccv3":
                continue  # 移除舊資料

        if chunk_type == b"IEND" and not inserted:
            output.extend(new_chunk)
            inserted = True

        output.extend(chunk_bytes)

    if not inserted:
        output.extend(new_chunk)
    return bytes(output)


def _extract_ccv3_payload(data: bytes) -> Tuple[Optional[str], Optional[str]]:
    if not is_png_data(data):
        return None, "提供的檔案不是有效的 PNG/APNG"

    pos = len(PNG_SIGNATURE)
    total = len(data)
    while pos + 8 <= total:
        length = int.from_bytes(data[pos : pos + 4], "big")
        chunk_type = data[pos + 4 : pos + 8]
        pos += 8
        chunk_data = data[pos : pos + length]
        pos += length
        pos += 4  # skip CRC

        if chunk_type == b"tEXt":
            parts = chunk_data.split(b"\x00", 1)
            if len(parts) != 2:
                continue
            keyword, raw_text = parts
            if keyword.lower() not in CHARACTER_CHUNK_KEYWORDS:
                continue
            try:
                decoded = base64.b64decode(raw_text)
                return decoded.decode("utf-8"), None
            except Exception as exc:  # noqa: BLE001
                keyword_str = keyword.decode("latin1", errors="ignore") or "ccv3/chara"
                return None, f"無法解碼 PNG 內的 {keyword_str} chunk：{exc}"

        if chunk_type == b"IEND":
            break
    return None, "此 PNG 沒有 ccv3/chara chunk，請確認是否為 SillyTavern 匯出的角色卡"
