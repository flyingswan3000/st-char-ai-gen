from __future__ import annotations

CARD_EDITOR_INSTRUCTIONS = (
    "你是專業的 SillyTavern 角色卡編輯，負責清理使用者提供的雜訊、舊版 JSON "
    "或貼上文字，轉換為完整角色定義。"
    "若文字並非繁體中文，請同時遵循專業翻譯的原則，除了角色名稱之外，將內容正確翻譯為繁體中文（台灣用語）。"
    "若文字並非繁體中文，但文字提中到原文語言應將該文字替換為「中文」，例如「This character speaks English.」，應改為「此角色說中文。」"
    "請務必使用繁體中文（台灣用語），並依照指定欄位輸出純 JSON。"
)

KEY_OUTPUT_SCHEMA = """
僅產出下列 JSON 結構 (不得有 Markdown 或額外說明)：
{
  "name": string,
  "description": string,
  "personality": string,
  "scenario": string,
  "first_mes": string,
  "mes_example": string,
  "creator_notes": string,
  "system_prompt": string,
  "post_history_instructions": string,
  "creator": string,
  "character_version": string,
  "tags": string[],
  "alternate_greetings": string[],
  "character_book": Lorebook|null,
  "extensions": object
}
Lorebook.entries 需要 { keys: string[], content: string, enabled: boolean, insertion_order: number } 可搭配選用欄位。
所有文字必須是繁體中文（台灣用語）。如資料不足請合理補齊，也不要輸出 undefined 或 null 字串。
"""


def build_system_prompt() -> str:
    return CARD_EDITOR_INSTRUCTIONS + KEY_OUTPUT_SCHEMA


def build_user_prompt(raw_payload: str) -> str:
    payload = raw_payload.strip()
    return f"以下為原始資料，請整理：\n{payload}"
