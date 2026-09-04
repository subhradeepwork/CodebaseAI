from __future__ import annotations

from pydantic import BaseModel, Field


class RepositoryCreate(BaseModel):
    path: str


class ConversationCreate(BaseModel):
    repository_id: int
    title: str | None = None


class ConversationUpdate(BaseModel):
    title: str | None = None
    archived: bool | None = None


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)


class IndexRequest(BaseModel):
    force: bool = False
    embeddings: bool = True


class SourceRef(BaseModel):
    path: str
    start_line: int
    end_line: int
    score: float = 0.0
    kind: str = "retrieval"
    stale: bool = False


class ChatResponse(BaseModel):
    user_message_id: int
    assistant_message_id: int
    content: str
    sources: list[SourceRef]
