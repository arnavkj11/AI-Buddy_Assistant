from pydantic import BaseModel
from typing import List, Optional

class ChatMessageReq(BaseModel):
    message: str

class Source(BaseModel):
    doc_title: str
    page_or_section: str
    chunk_id: str

class ChatMessageResp(BaseModel):
    answer: str
    sources: Optional[List[Source]] = []
    session_id: str

class ChatSessionCreateResp(BaseModel):
    session_id: str
    created_at: str
