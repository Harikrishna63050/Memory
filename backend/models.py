from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class MessageRequest(BaseModel):
    user_id: str
    organization_id: Optional[str] = None  # Auto-detected from user if not provided
    team_id: Optional[str] = None  # Auto-detected from user if not provided
    chat_id: Optional[str] = None
    message: str
    pdf_document_id: Optional[str] = None  # PDF to attach to this message
    sharing_level: Optional[str] = 'private'  # 'private' or 'organization' - set immediately on chat creation

class MessageResponse(BaseModel):
    message_id: str
    chat_id: str
    role: str
    content: str
    created_at: datetime
    has_pdf: Optional[bool] = False
    pdf_document_id: Optional[str] = None  # PDF document ID if has_pdf=True
    pdf_filename: Optional[str] = None  # PDF filename if has_pdf=True

class ChatResponse(BaseModel):
    chat_id: str
    user_id: str
    created_at: datetime
    messages: List[MessageResponse] = []

class SummaryResponse(BaseModel):
    summary_id: str
    chat_id: str
    summary_text: str
    created_at: datetime

class PDFUploadRequest(BaseModel):
    user_id: str
    organization_id: Optional[str] = None  # Auto-detected from user if not provided
    chat_id: Optional[str] = None

class PDFUploadResponse(BaseModel):
    success: bool
    message: str
    document_id: Optional[str] = None
    filename: Optional[str] = None
    num_chunks: Optional[int] = None

class ChatShareRequest(BaseModel):
    sharing_level: str  # 'private' or 'organization'

class ChatShareResponse(BaseModel):
    success: bool
    chat_id: str
    sharing_level: str
    shared_at: Optional[str] = None

