from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class LorebookEntry(BaseModel):
    keys: List[str]
    content: str
    extensions: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    insertion_order: int = 0
    constant: Optional[bool] = None
    case_sensitive: Optional[bool] = None
    name: Optional[str] = None
    priority: Optional[int] = None
    id: Optional[Union[int, str]] = None
    comment: Optional[str] = None
    selective: Optional[bool] = None
    secondary_keys: Optional[List[str]] = None
    position: Optional[str] = None
    use_regex: Optional[bool] = None


class Lorebook(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    scan_depth: Optional[int] = None
    token_budget: Optional[int] = None
    recursive_scanning: Optional[bool] = None
    extensions: Dict[str, Any] = Field(default_factory=dict)
    entries: List[LorebookEntry] = Field(default_factory=list)


class CharacterCore(BaseModel):
    name: str
    description: str
    personality: str
    scenario: str
    first_mes: str
    mes_example: str
    creator_notes: str
    system_prompt: str
    post_history_instructions: str
    alternate_greetings: List[str] = Field(default_factory=list)
    character_book: Optional[Lorebook] = None
    tags: List[str] = Field(default_factory=list)
    creator: str
    character_version: str
    extensions: Dict[str, Any] = Field(default_factory=dict)
