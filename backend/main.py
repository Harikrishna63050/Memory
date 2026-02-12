import logging
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Query, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional
from contextlib import asynccontextmanager
import uvicorn

from database import init_db, get_db, verify_db_connection, Chat, Embedding, PDFDocument, PDFChunkEmbedding, User
from models import (
    MessageRequest, MessageResponse, ChatResponse, SummaryResponse, 
    PDFUploadRequest, PDFUploadResponse, ChatShareRequest, ChatShareResponse
)
from services import (
    get_or_create_user, get_or_create_chat, get_last_messages,
    save_message_pair, generate_response, generate_summary
)
from pdf_service import store_pdf_document, PDF_AVAILABLE
from config import LOG_LEVEL, VERBOSE_LOGGING

# Setup logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    verify_db_connection()
    init_db()
    
    # Create super admin and teams if they don't exist
    try:
        from create_super_admin import create_super_admin
        logger.info("Checking for super admin and teams...")
        create_super_admin()
        logger.info("✅ Super admin and teams check completed")
    except Exception as e:
        logger.warning(f"⚠️  Could not create super admin: {e}")
        logger.warning("   Application will continue, but super admin may not exist")
    
    yield
    # Shutdown (if needed)

app = FastAPI(title="Memory Application API", lifespan=lifespan)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],  # React dev servers
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/chat", response_model=MessageResponse)
async def chat(request: MessageRequest, db: Session = Depends(get_db)):
    """Send a message and get AI response (enterprise role-based)"""
    logger.info("=" * 100)
    logger.info("📨 API REQUEST RECEIVED: /api/chat")
    logger.info("=" * 100)
    logger.info(f"   User ID: {request.user_id}")
    logger.info(f"   Organization ID: {request.organization_id}")
    logger.info(f"   Team ID: {request.team_id}")
    logger.info(f"   Chat ID: {request.chat_id or 'NEW CHAT'}")
    logger.info(f"   Message: {request.message}")
    logger.info(f"   PDF Document ID: {request.pdf_document_id or 'None'}")
    logger.info("-" * 100)
    
    try:
        # Get or create user with enterprise hierarchy
        from database import User
        user = get_or_create_user(
            db, 
            request.user_id, 
            organization_id=request.organization_id,
            team_id=request.team_id
        )
        
        # Get or create chat (generate summary for previous chat if creating new one)
        # Always default to 'private' - sharing_level only changes when user explicitly toggles it
        is_new_chat = request.chat_id is None
        # For new chats, always start with 'private' - user can toggle to 'organization' later
        # For existing chats, preserve the existing sharing_level
        from database import Embedding
        sharing_level = 'private'  # Default for new chats
        if not is_new_chat:
            # For existing chats, check if embedding exists and preserve its sharing_level
            existing_embedding = db.query(Embedding).filter(Embedding.chat_id == request.chat_id).first()
            if existing_embedding:
                sharing_level = existing_embedding.sharing_level
        
        chat_id, was_created = get_or_create_chat(
            db, 
            request.user_id, 
            request.chat_id, 
            generate_previous_summary=is_new_chat,
            sharing_level=sharing_level
        )
        
        # Production-grade: Get PDF to attach to this message
        pdf_document_id = request.pdf_document_id
        if not pdf_document_id:
            from services import get_orphaned_pdf_for_user
            pdf_document_id = get_orphaned_pdf_for_user(db, request.user_id)
        
        # Save user message FIRST with PDF attachment
        from services import save_user_message, update_assistant_message
        user_message_obj = save_user_message(
            db, request.user_id, chat_id, request.message,
            pdf_document_id=pdf_document_id
        )
        
        # Get last 5 message pairs from current chat (sliding window)
        context_messages = get_last_messages(db, chat_id, limit=5)
        
        # Generate AI response using enterprise memory architecture
        # Role-based search is handled automatically based on user's role
        ai_response = generate_response(
            request.message, 
            context_messages,
            db=db,
            user_id=request.user_id,
            organization_id=user.organization_id,
            team_id=user.team_id,
            current_chat_id=chat_id,
            is_new_chat=was_created
        )
        
        # Update the message with assistant response
        message_pair = update_assistant_message(db, user_message_obj.message_id, ai_response)
        
        # PDF is now linked to message via Chat.pdf_document_id - no additional linking needed
        
        # Note: Summary and embeddings are generated only when a new chat is opened
        # (handled in get_or_create_chat function)
        
        # Get PDF filename if attached
        pdf_filename = None
        if message_pair.has_pdf and message_pair.pdf_document_id:
            pdf_doc = db.query(PDFDocument).filter(
                PDFDocument.document_id == message_pair.pdf_document_id
            ).first()
            if pdf_doc:
                pdf_filename = pdf_doc.filename
        
        # Production-grade logging: API response
        logger.info("=" * 100)
        logger.info("📤 API RESPONSE SENT: /api/chat")
        logger.info("=" * 100)
        logger.info(f"   Chat ID: {chat_id}")
        logger.info(f"   Message ID: {message_pair.message_id}")
        logger.info(f"   Response Length: {len(ai_response):,} chars")
        logger.info(f"   PDF Attached: {message_pair.has_pdf}")
        if pdf_filename:
            logger.info(f"   PDF Filename: {pdf_filename}")
        logger.info("=" * 100)
        logger.info("")  # Empty line for readability
        
        return MessageResponse(
            message_id=message_pair.message_id,
            chat_id=chat_id,
            role="assistant",
            content=ai_response,
            created_at=message_pair.created_at,
            has_pdf=message_pair.has_pdf,
            pdf_document_id=message_pair.pdf_document_id,
            pdf_filename=pdf_filename
        )
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}", exc_info=True)
        # Re-raise to let FastAPI handle with CORS headers
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/chat/{chat_id}/messages", response_model=List[MessageResponse])
async def get_messages(chat_id: str, db: Session = Depends(get_db)):
    """Get all messages for a chat (returns as separate user/assistant messages)"""
    message_pairs = db.query(Chat).filter(Chat.chat_id == chat_id)\
        .order_by(Chat.created_at).all()
    
    result = []
    for msg_pair in message_pairs:
        # Get PDF filename if attached
        pdf_filename = None
        if msg_pair.has_pdf and msg_pair.pdf_document_id:
            pdf_doc = db.query(PDFDocument).filter(
                PDFDocument.document_id == msg_pair.pdf_document_id
            ).first()
            if pdf_doc:
                pdf_filename = pdf_doc.filename
        
        # Add user message (PDF attached to user message, not assistant)
        result.append(MessageResponse(
            message_id=msg_pair.message_id + "_user",
            chat_id=msg_pair.chat_id,
            role="user",
            content=msg_pair.user_message,
            created_at=msg_pair.created_at,
            has_pdf=msg_pair.has_pdf,
            pdf_document_id=msg_pair.pdf_document_id,
            pdf_filename=pdf_filename
        ))
        # Add assistant message
        result.append(MessageResponse(
            message_id=msg_pair.message_id + "_assistant",
            chat_id=msg_pair.chat_id,
            role="assistant",
            content=msg_pair.assistant_message,
            created_at=msg_pair.created_at,
            has_pdf=False,  # PDF is attached to user message, not assistant
            pdf_document_id=None,
            pdf_filename=None
        ))
    
    return result

@app.get("/api/user/{user_id}/chats", response_model=List[ChatResponse])
async def get_user_chats(user_id: str, db: Session = Depends(get_db)):
    """Get all chats for a user"""
    # Get distinct chat_ids for this user
    distinct_chats = db.query(Chat.chat_id).filter(Chat.user_id == user_id)\
        .distinct().all()
    
    result = []
    for (chat_id,) in distinct_chats:
        message_pairs = db.query(Chat).filter(Chat.chat_id == chat_id)\
            .order_by(Chat.created_at).all()
        
        if message_pairs:
            # Convert pairs to message list
            messages_list = []
            for msg_pair in message_pairs:
                messages_list.append(MessageResponse(
                    message_id=msg_pair.message_id + "_user",
                    chat_id=msg_pair.chat_id,
                    role="user",
                    content=msg_pair.user_message,
                    created_at=msg_pair.created_at
                ))
                messages_list.append(MessageResponse(
                    message_id=msg_pair.message_id + "_assistant",
                    chat_id=msg_pair.chat_id,
                    role="assistant",
                    content=msg_pair.assistant_message,
                    created_at=msg_pair.created_at
                ))
            
            result.append(ChatResponse(
                chat_id=chat_id,
                user_id=user_id,
                created_at=message_pairs[0].created_at,
                messages=messages_list
            ))
    
    # Sort by most recent first
    result.sort(key=lambda x: x.created_at, reverse=True)
    return result

@app.get("/api/user/{user_id}/chats/preview", response_model=List[dict])
async def get_user_chats_preview(user_id: str, db: Session = Depends(get_db)):
    """Get all chats for a user with preview (first message) and sharing level"""
    try:
        from database import Embedding
        
        # Check if user exists (read-only endpoint - don't create)
        # User will be created when they send first message with organization_id
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            # User doesn't exist yet - return empty list (they'll be created on first message)
            return []
        
        # Get distinct chat_ids for this user
        distinct_chats = db.query(Chat.chat_id).filter(Chat.user_id == user_id)\
            .distinct().all()
        
        result = []
        for (chat_id,) in distinct_chats:
            # Get first message pair as preview
            first_message_pair = db.query(Chat).filter(Chat.chat_id == chat_id)\
                .order_by(Chat.created_at).first()
            
            # Get last message pair for updated_at
            last_message_pair = db.query(Chat).filter(Chat.chat_id == chat_id)\
                .order_by(desc(Chat.created_at)).first()
            
            # Get message pair count
            message_count = db.query(Chat).filter(Chat.chat_id == chat_id).count()
            
            # Get sharing level from embedding
            embedding = db.query(Embedding).filter(Embedding.chat_id == chat_id).first()
            sharing_level = embedding.sharing_level if embedding else 'private'
            
            if first_message_pair:
                preview = first_message_pair.user_message[:100] + "..." if len(first_message_pair.user_message) > 100 else first_message_pair.user_message
                result.append({
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "created_at": first_message_pair.created_at.isoformat(),
                    "updated_at": last_message_pair.created_at.isoformat() if last_message_pair else first_message_pair.created_at.isoformat(),
                    "preview": preview,
                    "message_count": message_count,
                    "sharing_level": sharing_level  # 'private' or 'organization'
                })
        
        # Sort by most recent first
        result.sort(key=lambda x: x["updated_at"], reverse=True)
        return result
    except Exception as e:
        logger.error(f"Error in get_user_chats_preview: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/organizations/{organization_id}/users")
async def get_organization_users(organization_id: str, db: Session = Depends(get_db)):
    """Get all users in an organization (for auto-complete)"""
    from database import User
    users = db.query(User).filter(User.organization_id == organization_id)\
        .order_by(User.user_id).all()
    
    return [
        {
            "user_id": user.user_id,
            "role": user.role,
            "team_id": user.team_id,
            "created_at": user.created_at.isoformat()
        }
        for user in users
    ]

@app.get("/api/organizations/{organization_id}/teams")
async def get_organization_teams(organization_id: str, db: Session = Depends(get_db)):
    """Get all teams in an organization (for auto-complete)"""
    from database import Team
    teams = db.query(Team).filter(Team.organization_id == organization_id)\
        .order_by(Team.team_name).all()
    
    return [
        {
            "team_id": team.team_id,
            "team_name": team.team_name,
            "team_lead_id": team.team_lead_id,
            "created_at": team.created_at.isoformat()
        }
        for team in teams
    ]

@app.get("/api/organizations")
async def get_all_organizations(db: Session = Depends(get_db)):
    """Get all organizations (for auto-complete)"""
    from database import Organization
    orgs = db.query(Organization).order_by(Organization.organization_name).all()
    
    return [
        {
            "organization_id": org.organization_id,
            "organization_name": org.organization_name,
            "created_at": org.created_at.isoformat()
        }
        for org in orgs
    ]

@app.get("/api/chat/{chat_id}/summaries", response_model=List[SummaryResponse])
async def get_chat_summaries(chat_id: str, db: Session = Depends(get_db)):
    """Get summary for a chat (should be only one)"""
    embeddings = db.query(Embedding).filter(Embedding.chat_id == chat_id)\
        .order_by(Embedding.created_at.desc()).all()
    
    return [
        SummaryResponse(
            summary_id=emb.summary_id,
            chat_id=emb.chat_id,
            summary_text=emb.summary,
            created_at=emb.created_at
        )
        for emb in embeddings
    ]

@app.get("/api/chat/{chat_id}/pdfs")
async def get_chat_pdfs(chat_id: str, user_id: str, db: Session = Depends(get_db)):
    """
    Get all PDFs attached to messages in a chat.
    Enterprise-grade: Respects sharing level and role-based access.
    - Super Admin: Access ALL PDFs
    - Team Lead/Member: Access if chat is shared with organization or own chat
    """
    from database import User, Embedding
    
    # Get user info for role-based access
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if user can access this chat
    # Super admin can access all chats
    if user.role != 'super_admin':
        # Check if chat belongs to user or is shared with organization
        chat_embedding = db.query(Embedding).filter(Embedding.chat_id == chat_id).first()
        if not chat_embedding:
            raise HTTPException(status_code=404, detail="Chat not found")
        
        # Check access: own chat OR organization shared
        can_access = False
        if chat_embedding.user_id == user_id:
            can_access = True
        elif (chat_embedding.organization_id == user.organization_id and 
              chat_embedding.sharing_level == 'organization'):
            can_access = True
        elif user.role == 'team_lead' and chat_embedding.team_id == user.team_id:
            can_access = True
        
        if not can_access:
            raise HTTPException(status_code=403, detail="Access denied: Chat is private or not shared with your organization")
    
    # Find messages with PDF attachments in this chat
    # Super admin: no user filter, others: filter by chat ownership or sharing
    if user.role == 'super_admin':
        messages_with_pdfs = db.query(Chat).filter(
            Chat.chat_id == chat_id,
            Chat.has_pdf == True,
            Chat.pdf_document_id.isnot(None)
        ).all()
    else:
        # For non-super-admin: get from chat messages (already verified access above)
        messages_with_pdfs = db.query(Chat).filter(
            Chat.chat_id == chat_id,
            Chat.has_pdf == True,
            Chat.pdf_document_id.isnot(None)
        ).all()
    
    if not messages_with_pdfs:
        return []
    
    # Get unique PDF document IDs
    pdf_document_ids = list(set([msg.pdf_document_id for msg in messages_with_pdfs if msg.pdf_document_id]))
    
    # Get PDF documents - Super admin can access all, others only if chat is shared
    if user.role == 'super_admin':
        pdfs = db.query(PDFDocument).filter(
            PDFDocument.document_id.in_(pdf_document_ids)
        ).order_by(PDFDocument.created_at.desc()).all()
    else:
        # For non-super-admin: PDFs are accessible if chat is shared (already verified above)
        pdfs = db.query(PDFDocument).filter(
            PDFDocument.document_id.in_(pdf_document_ids)
        ).order_by(PDFDocument.created_at.desc()).all()
    
    return [
        {
            "document_id": pdf.document_id,
            "filename": pdf.filename,
            "num_chunks": len(pdf.chunks) if pdf.chunks else 0,
            "created_at": pdf.created_at.isoformat(),
            "metadata": pdf.pdf_metadata or {}
        }
        for pdf in pdfs
    ]

@app.post("/api/pdf/upload", response_model=PDFUploadResponse)
async def upload_pdf(
    file: UploadFile = File(...),
    user_id: str = Form(...),
    organization_id: Optional[str] = Form(None),
    chat_id: Optional[str] = Form(None),  # Kept for backwards compatibility, but not used
    db: Session = Depends(get_db)
):
    """
    Enterprise PDF upload endpoint.
    Processes PDF: Parse → Chunk → Embed → Store in database.
    """
    try:
        # Validate PDF availability
        if not PDF_AVAILABLE:
            raise HTTPException(
                status_code=500,
                detail="PDF processing not available. Install pypdf: pip install pypdf"
            )
        
        # Validate file type
        if not file.filename or not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="File must be a PDF (.pdf)")
        
        # Validate file size (max 10MB for production)
        file_content = await file.read()
        max_size = 10 * 1024 * 1024  # 10MB
        if len(file_content) > max_size:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum size: 10MB (received: {len(file_content) / 1024 / 1024:.2f}MB)"
            )
        
        logger.info(f"📄 PDF Upload Request: {file.filename} | User: {user_id} | Org: {organization_id}")
        
        # Get or create user with enterprise hierarchy
        user = get_or_create_user(db, user_id, organization_id=organization_id)
        
        # Store PDF document with embeddings
        result = store_pdf_document(
            db=db,
            user_id=user_id,
            file_content=file_content,
            filename=file.filename,
            chunk_size=1000,
            chunk_overlap=200
        )
        
        logger.info(f"✅ PDF upload successful: {file.filename} → {result['document_id']}")
        
        return PDFUploadResponse(
            success=True,
            message=f"PDF uploaded and processed successfully. {result['embeddings_created']} chunks indexed.",
            document_id=result["document_id"],
            filename=file.filename,
            num_chunks=result["num_chunks"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error uploading PDF: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing PDF: {str(e)}")

@app.post("/api/chats/{chat_id}/share", response_model=ChatShareResponse)
async def share_chat(
    chat_id: str, 
    request: ChatShareRequest,
    user_id: str = Query(..., description="User ID (from auth token in production)"),
    db: Session = Depends(get_db)
):
    """
    Share or unshare a chat with organization (enterprise feature).
    When chat is shared, PDFs attached to that chat also become accessible to organization.
    """
    try:
        from database import Embedding, User, Chat, PDFDocument
        from datetime import datetime
        import uuid
        
        # Verify user exists
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get or create embedding for this chat (for new chats, embedding might not exist yet)
        embedding = db.query(Embedding).filter(Embedding.chat_id == chat_id).first()
        
        # Verify chat exists (check Chat table)
        chat_exists = db.query(Chat).filter(Chat.chat_id == chat_id, Chat.user_id == user_id).first()
        if not chat_exists:
            raise HTTPException(status_code=404, detail="Chat not found")
        
        # If embedding doesn't exist, create it (for new chats)
        if not embedding:
            embedding = Embedding(
                summary_id=str(uuid.uuid4()),
                user_id=user_id,
                organization_id=user.organization_id,
                team_id=user.team_id,
                chat_id=chat_id,
                summary="",  # Will be filled when chat completes
                sharing_level='private',  # Always default to private
                shared_at=None
            )
            db.add(embedding)
            db.flush()  # Flush to get the embedding object
        
        # Verify user owns this chat or is super admin
        if embedding.user_id != user_id and user.role != 'super_admin':
            raise HTTPException(status_code=403, detail="Only chat owner or super admin can change sharing")
        
        # Validate sharing level
        if request.sharing_level not in ['private', 'organization']:
            raise HTTPException(status_code=400, detail="sharing_level must be 'private' or 'organization'")
        
        # Update sharing level
        old_sharing_level = embedding.sharing_level
        embedding.sharing_level = request.sharing_level
        if request.sharing_level == 'organization':
            embedding.shared_at = datetime.now(datetime.UTC) if hasattr(datetime, 'UTC') else datetime.utcnow()
        else:
            embedding.shared_at = None
        
        # PRODUCTION FEATURE: When chat is shared, PDFs in that chat also become accessible
        # Find all PDFs attached to messages in this chat
        messages_with_pdfs = db.query(Chat).filter(
            Chat.chat_id == chat_id,
            Chat.has_pdf == True,
            Chat.pdf_document_id.isnot(None)
        ).all()
        
        pdf_document_ids = list(set([msg.pdf_document_id for msg in messages_with_pdfs if msg.pdf_document_id]))
        
        if pdf_document_ids:
            logger.info(f"📄 Chat {chat_id} has {len(pdf_document_ids)} PDF(s) attached")
            logger.info(f"   Sharing level changed: {old_sharing_level} → {request.sharing_level}")
            logger.info(f"   PDFs in this chat are now {'accessible' if request.sharing_level == 'organization' else 'private'}")
            logger.info(f"   PDF document IDs: {', '.join(pdf_document_ids)}")
        
        db.commit()
        
        return ChatShareResponse(
            success=True,
            chat_id=chat_id,
            sharing_level=request.sharing_level,
            shared_at=embedding.shared_at.isoformat() if embedding.shared_at else None
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error sharing chat: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error sharing chat: {str(e)}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
