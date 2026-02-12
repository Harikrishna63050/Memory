import uuid
import logging
import time
from typing import List, Optional, Tuple, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import desc
from database import User, Chat, Embedding
from openai import OpenAI
from embedding_service import generate_embedding
from user_profile_service import update_user_profile, get_user_profile_context, format_user_profile
from config import (
    CHAT_MODEL, SUMMARY_MODEL, OPENAI_API_KEY, TOP_K_CONTEXTS, 
    SIMILARITY_THRESHOLD_MIN, RECENT_MESSAGES_LIMIT
)

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# Setup logging
logger = logging.getLogger(__name__)

def get_or_create_user(
    db: Session, 
    user_id: str, 
    organization_id: Optional[str] = None,
    team_id: Optional[str] = None,
    role: str = 'member'
) -> User:
    """
    Get or create a user with enterprise hierarchy association.
    Enterprise-grade: Users belong to organization and team, have roles.
    Production constraint: Only ONE super_admin can exist in the entire system.
    """
    from database import Organization, Team
    
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        # PRODUCTION CONSTRAINT: Only one super_admin allowed
        if role == 'super_admin':
            existing_super_admin = db.query(User).filter(User.role == 'super_admin').first()
            if existing_super_admin:
                logger.warning(f"⚠️  Super admin already exists: {existing_super_admin.user_id}")
                logger.warning(f"   Cannot create another super admin. Setting {user_id} to member role.")
                role = 'member'  # Override to member if super admin already exists
        
        # Auto-create organization if provided and doesn't exist
        if organization_id:
            org = db.query(Organization).filter(Organization.organization_id == organization_id).first()
            if not org:
                logger.info(f"Organization {organization_id} not found, creating...")
                org = Organization(organization_id=organization_id, organization_name=organization_id)
                db.add(org)
                db.commit()
        
        # Auto-create team if provided and doesn't exist
        if team_id and organization_id:
            team = db.query(Team).filter(Team.team_id == team_id).first()
            if not team:
                logger.info(f"Team {team_id} not found, creating...")
                team = Team(team_id=team_id, organization_id=organization_id, team_name=team_id)
                db.add(team)
                db.commit()
        
        user = User(
            user_id=user_id, 
            organization_id=organization_id,
            team_id=team_id,
            role=role
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info(f"✅ Created user {user_id} | Org: {organization_id} | Team: {team_id} | Role: {user.role}")
    else:
        # Update role if needed (but enforce super admin constraint)
        if role == 'super_admin' and user.role != 'super_admin':
            existing_super_admin = db.query(User).filter(User.role == 'super_admin').first()
            if existing_super_admin and existing_super_admin.user_id != user_id:
                logger.warning(f"⚠️  Super admin already exists: {existing_super_admin.user_id}")
                logger.warning(f"   Cannot change {user_id} to super admin. Keeping current role: {user.role}")
            else:
                user.role = role
                db.commit()
                logger.info(f"✅ Updated user {user_id} role to {role}")
    
    return user

def get_orphaned_pdf_for_user(db: Session, user_id: str) -> Optional[str]:
    """
    Get the most recent orphaned PDF (not attached to any message) for a user.
    Production-grade: Returns PDF document_id to attach to next message.
    
    An orphaned PDF is one that:
    - Belongs to the user
    - Is not referenced by any Chat record (no message has pdf_document_id pointing to it)
    
    Returns: PDF document_id if found, None otherwise
    """
    from database import PDFDocument, Chat
    
    # Find PDFs that don't have any Chat records pointing to them
    # Using LEFT JOIN: PDFs with no matching Chat.pdf_document_id
    orphaned_pdf = db.query(PDFDocument).outerjoin(
        Chat, Chat.pdf_document_id == PDFDocument.document_id
    ).filter(
        PDFDocument.user_id == user_id,
        Chat.pdf_document_id.is_(None)  # No Chat message references this PDF
    ).order_by(PDFDocument.created_at.desc()).first()
    
    if orphaned_pdf:
        logger.info(f"📎 Found orphaned PDF {orphaned_pdf.document_id} to attach to next message")
        return orphaned_pdf.document_id
    
    return None

# Removed: attach_orphaned_pdf_to_chat()
# PDFs are now attached at message level via Chat.pdf_document_id
# No need to set chat_id on PDFDocument anymore

def get_or_create_chat(db: Session, user_id: str, chat_id: Optional[str] = None, generate_previous_summary: bool = True, sharing_level: str = 'private') -> Tuple[str, bool]:
    """
    Get or create a chat_id.
    Creates embedding immediately with sharing_level for new chats.
    Returns: (chat_id, is_new_chat)
    """
    # Use alias to avoid UnboundLocalError when Embedding is used later in function
    # This ensures Python doesn't treat Embedding as a local variable
    from database import Embedding as EmbeddingModel
    
    if chat_id:
        # Check if chat exists by checking if any messages exist
        existing_chat = db.query(Chat).filter(
            Chat.chat_id == chat_id, 
            Chat.user_id == user_id
        ).first()
        if existing_chat:
            return chat_id, False
    
    # Before creating new chat, generate summary for the most recent previous chat
    if generate_previous_summary:
        # Get the most recent chat_id for this user
        previous_chat = db.query(Chat).filter(Chat.user_id == user_id)\
            .order_by(desc(Chat.created_at)).first()
        
        if previous_chat and previous_chat.chat_id:
            previous_chat_id = previous_chat.chat_id
            # Check if summary already exists for this chat (with actual summary text and embedding vector)
            existing_summary = db.query(EmbeddingModel).filter(EmbeddingModel.chat_id == previous_chat_id).first()
            # Only generate if summary doesn't exist OR if it exists but has no summary text or embedding vector
            if not existing_summary or not existing_summary.summary or existing_summary.embedding_vector is None:
                # Generate summary for previous chat
                logger.info(f"📝 Generating summary for previous chat {previous_chat_id[:8]}... before creating new chat")
                generate_summary(db, previous_chat_id, user_id)
    
    # Create new chat_id
    new_chat_id = chat_id or str(uuid.uuid4())
    
    # Create embedding immediately with sharing_level (before messages are added)
    # This allows sharing to be set from the start
    user = db.query(User).filter(User.user_id == user_id).first()
    if user:
        existing_embedding = db.query(EmbeddingModel).filter(EmbeddingModel.chat_id == new_chat_id).first()
        if not existing_embedding:
            # Create placeholder embedding with sharing_level
            placeholder_embedding = EmbeddingModel(
                summary_id=str(uuid.uuid4()),
                user_id=user_id,
                organization_id=user.organization_id,
                team_id=user.team_id,
                chat_id=new_chat_id,
                summary="",  # Will be filled when chat completes
                sharing_level=sharing_level,
                shared_at=datetime.utcnow() if sharing_level == 'organization' else None
            )
            db.add(placeholder_embedding)
            db.commit()
            logger.info(f"✅ Created embedding with sharing_level='{sharing_level}' for new chat {new_chat_id}")
    
    # Note: PDFs are now attached at message level, not chat level
    # Orphaned PDFs will be attached when first message is sent
    
    return new_chat_id, True

def get_last_messages(db: Session, chat_id: str, limit: int = 10) -> List[Chat]:
    """Get last N message pairs for a chat"""
    return db.query(Chat).filter(Chat.chat_id == chat_id)\
        .order_by(desc(Chat.created_at)).limit(limit).all()

def save_user_message(db: Session, user_id: str, chat_id: str, user_message: str, pdf_document_id: Optional[str] = None) -> Chat:
    """
    Save user message first (before generating response).
    Production-grade: PDF is attached immediately so it's available for context.
    Enterprise-grade: Includes organization_id and team_id for better structure.
    
    Returns: Chat message object with message_id
    """
    # Get user's organization and team info
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise ValueError(f"User {user_id} not found")
    
    message_id = str(uuid.uuid4())
    has_pdf = pdf_document_id is not None
    
    message = Chat(
        message_id=message_id,
        user_id=user_id,
        organization_id=user.organization_id,
        team_id=user.team_id,
        chat_id=chat_id,
        user_message=user_message,
        assistant_message="",  # Placeholder - will be updated after response generation
        has_pdf=has_pdf,
        pdf_document_id=pdf_document_id
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    
    if has_pdf:
        logger.info(f"✅ User message {message_id} saved with PDF {pdf_document_id}")
    
    return message

def update_assistant_message(db: Session, message_id: str, assistant_message: str) -> Chat:
    """
    Update the assistant message for an existing user message.
    """
    message = db.query(Chat).filter(Chat.message_id == message_id).first()
    if message:
        message.assistant_message = assistant_message
        db.commit()
        db.refresh(message)
    return message

def save_message_pair(db: Session, user_id: str, chat_id: str, user_message: str, assistant_message: str, pdf_document_id: Optional[str] = None) -> Chat:
    """
    Save a question-response pair in the chats table.
    Enterprise-grade: Includes organization_id and team_id for better structure.
    
    Note: For production, prefer using save_user_message() + update_assistant_message()
    to ensure PDF context is available during response generation.
    
    Args:
        pdf_document_id: Optional PDF document ID to attach to this message
    """
    # Get user's organization and team info
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise ValueError(f"User {user_id} not found")
    
    message_id = str(uuid.uuid4())
    has_pdf = pdf_document_id is not None
    
    message = Chat(
        message_id=message_id,
        user_id=user_id,
        organization_id=user.organization_id,
        team_id=user.team_id,
        chat_id=chat_id,
        user_message=user_message,
        assistant_message=assistant_message,
        has_pdf=has_pdf,
        pdf_document_id=pdf_document_id
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    
    if has_pdf:
        logger.info(f"📎 Message {message_id} attached to PDF document {pdf_document_id}")
    
    return message

# Removed: get_global_summary_context and update_global_summary
# These are replaced by semantic search and user profile system

def generate_response(
    user_message: str, 
    context_messages: List[Chat], 
    db: Optional[Session] = None,
    user_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    team_id: Optional[str] = None,
    current_chat_id: Optional[str] = None,
    is_new_chat: bool = False
) -> str:
    """
    Generate AI response using production-grade memory architecture:
    1. User Profile (compressed facts)
    2. Relevant Historical Contexts (semantic search - top K)
    3. Recent Messages (sliding window - last N pairs from current chat)
    4. Current user message
    
    Returns: AI response string
    """
    from embedding_service import get_relevant_contexts
    
    # ============================================================================
    # PRODUCTION-GRADE LOGGING: CONVERSATION FLOW
    # ============================================================================
    logger.info("=" * 100)
    logger.info(f"🔄 CONVERSATION REQUEST")
    logger.info("=" * 100)
    logger.info(f"   User ID: {user_id}")
    logger.info(f"   Chat ID: {current_chat_id}")
    logger.info(f"   Organization: {organization_id}")
    logger.info(f"   Team: {team_id}")
    logger.info(f"   New Chat: {is_new_chat}")
    logger.info(f"   User Message: {user_message}")
    logger.info(f"   Recent Messages Available: {len(context_messages)} pairs")
    logger.info("-" * 100)
    
    messages = []
    
    # 1. User Profile (compressed facts)
    logger.info("   ──────────────────────────────────────────────────────────────────────────")
    logger.info("   📋 CONTEXT ASSEMBLY STEP 1: User Profile")
    logger.info(f"      ℹ️  User Profile = Compressed facts extracted from ALL past chat summaries")
    logger.info(f"      ℹ️  Updated after each chat completion with new facts via LLM extraction")
    if db and user_id:
        user_profile = get_user_profile_context(db, user_id)
        if user_profile:
            profile_text = format_user_profile(user_profile)
            if profile_text:
                messages.append({
                    "role": "system",
                    "content": f"You are a helpful assistant. Here are important facts about the user:\n{profile_text}"
                })
                logger.info(f"      ✅ Added user profile context ({len(profile_text)} chars)")
                logger.info(f"      📝 Full Profile content:")
                for line in profile_text.split('\n'):
                    if line.strip():
                        logger.info(f"         • {line.strip()}")
                logger.info(f"      💡 This profile contains ALL extracted facts from past conversations")
                logger.info(f"      💡 Even if embeddings don't match, this provides long-term memory")
            else:
                logger.info(f"      ⚠️  User profile exists but is empty")
        else:
            logger.info(f"      ⚠️  No user profile found for user {user_id}")
    else:
        logger.info(f"      ⚠️  Skipped (db or user_id not provided)")
    
    # 2. PDF Document Context (add EARLY for better context understanding)
    # Enterprise-grade: Add PDF context BEFORE historical contexts, respects sharing level
    logger.info("   ──────────────────────────────────────────────────────────────────────────")
    logger.info("   📋 CONTEXT ASSEMBLY STEP 2: PDF Document Context")
    pdf_context = None
    
    if db and user_id and current_chat_id:
        try:
            from pdf_service import get_all_pdf_chunks_for_chat
            
            # Enterprise-grade: Get ALL PDF chunks if PDF exists in chat and user has access
            # Respects sharing level: PDFs accessible if chat is shared with organization
            pdf_context = get_all_pdf_chunks_for_chat(
                db, user_id, current_chat_id, 
                max_chunks=1000,  # Send all chunks for best quality
                requesting_user_id=user_id  # Pass user_id for access control
            )
            
            if pdf_context:
                # Enhanced prompt to prioritize PDF when user asks about "it" or "the document"
                pdf_system_message = f"""CRITICAL: A document has been uploaded to this chat. The document content is provided below.

                ABSOLUTE PRIORITY RULES:
                1. When the user says "summarize it", "summarize this", "summarize the document", "summarize", or any similar phrase, they are referring to THIS DOCUMENT below, NOT the conversation history.
                2. The document content takes ABSOLUTE PRIORITY over any conversation history when answering questions.
                3. If the user asks to summarize something, you MUST summarize THIS DOCUMENT.
                4. Use the document information to answer all questions accurately.
                5. When ambiguous phrases like "it" or "this" are used, always interpret them as referring to THIS DOCUMENT.

                DOCUMENT CONTENT:
                {pdf_context}

                CRITICAL REMINDER: When the user asks to "summarize it" or similar, they mean THIS DOCUMENT, not the conversation history. Always prioritize the document."""
                                
                messages.append({
                    "role": "system",
                    "content": pdf_system_message
                })
                logger.info(f"      ✅ Added PDF context EARLY - all chunks included ({len(pdf_context)} chars)")
                logger.info(f"      💡 PDF context is now available throughout the conversation")
                logger.info(f"      📄 Enhanced prompt: PDF takes priority when user asks to summarize")
            else:
                logger.info(f"      ⚠️  No PDF documents found for this chat")
        except Exception as e:
            logger.warning(f"      ⚠️  Error retrieving PDF context: {e}")
    else:
        logger.info(f"      ⚠️  Skipped (db, user_id, or chat_id not provided)")
    
    # 3. Relevant Historical Contexts (semantic search - enterprise role-based)
    logger.info("   ──────────────────────────────────────────────────────────────────────────")
    logger.info("   📋 CONTEXT ASSEMBLY STEP 3: Historical Contexts from Embeddings")
    
    if db and user_id:
        # Get user info for role-based search
        user_obj = db.query(User).filter(User.user_id == user_id).first()
        if not user_obj:
            logger.warning(f"   ⚠️  User {user_id} not found")
            relevant_contexts = []
        else:
            user_role = user_obj.role or 'member'
            organization_id = user_obj.organization_id
            team_id = user_obj.team_id
            
            logger.info(f"   Role: {user_role.upper()} | Org: {organization_id} | Team: {team_id}")
            
            relevant_contexts = get_relevant_contexts(
                db, user_message, user_id, 
                current_chat_id=current_chat_id,
                organization_id=organization_id,
                team_id=team_id,
                user_role=user_role,
                top_k=TOP_K_CONTEXTS,
                similarity_threshold_min=SIMILARITY_THRESHOLD_MIN
            )
    else:
        relevant_contexts = []
    
    if relevant_contexts:
        # Production Strategy: Always use summaries (token-efficient, cost-effective)
        # Build context text with clearer formatting
        # Also include PDF chunks from historical chats if they have PDFs
        context_parts = []
        pdf_chunks_from_historical = []  # Collect PDF chunks from historical chats
        
        # Log embeddings search results
        logger.info(f"      📊 Embeddings Search Results: {len(relevant_contexts)} context(s) found")
        for idx, ctx in enumerate(relevant_contexts[:TOP_K_CONTEXTS], 1):
            # Build chat context with summary (ensure summary exists)
            summary_text = ctx.summary if ctx.summary else "No summary available"
            chat_context = f"--- Chat {idx} (ID: {ctx.chat_id[:8]}, User: {ctx.user_id}) ---\n{summary_text}"
            
            # Log each embedding found
            logger.info(f"      [{idx}] Chat ID: {ctx.chat_id[:8]}... | User: {ctx.user_id}")
            if ctx.summary:
                logger.info(f"          Summary Preview: {ctx.summary[:150]}{'...' if len(ctx.summary) > 150 else ''}")
            else:
                logger.warning(f"          ⚠️  No summary available for this chat")
            
            # Check if this historical chat has PDFs and include chunks
            # Enterprise-grade: Respects sharing level - PDFs accessible if chat is shared
            try:
                from pdf_service import get_all_pdf_chunks_for_chat
                # Pass requesting_user_id for access control (checks if user can access PDFs in this chat)
                historical_pdf_context = get_all_pdf_chunks_for_chat(
                    db, ctx.user_id, ctx.chat_id, 
                    max_chunks=1000,
                    requesting_user_id=user_id  # Current user requesting access
                )
                if historical_pdf_context:
                    # Add PDF content prominently - this is the key information source
                    chat_context += f"\n\n{'='*80}\n📄 PDF DOCUMENT CONTENT (PRIMARY INFORMATION SOURCE):\n{'='*80}\n{historical_pdf_context}\n{'='*80}"
                    pdf_chunks_from_historical.append(f"Chat {ctx.chat_id[:8]} ({ctx.user_id}): {len(historical_pdf_context)} chars")
                    logger.info(f"          📄 PDF found in this chat ({len(historical_pdf_context)} chars) - INCLUDED in context")
            except Exception as e:
                logger.debug(f"      ⚠️  Could not fetch PDF chunks for historical chat {ctx.chat_id[:8]}: {e}")
            
            # Always add chat context (with or without PDF)
            context_parts.append(chat_context)
        
        context_text = "\n\n".join(context_parts)
        total_context_chars = len(context_text)
        
        # Log context size accurately
        if total_context_chars == 0:
            logger.warning(f"      ⚠️  WARNING: Context text is empty! This should not happen.")
        else:
            logger.info(f"      📊 Context text size: {total_context_chars:,} chars (includes summaries + PDF chunks)")
        
        if pdf_chunks_from_historical:
            logger.info(f"      📄 Also included PDF chunks from {len(pdf_chunks_from_historical)} historical chat(s): {', '.join(pdf_chunks_from_historical)}")
            logger.info(f"      💡 PDF content is included in the context above - LLM will use it to answer questions")
        
        # Stronger prompt for using historical context
        search_scope_note = ""
        if user_obj and user_obj.role == 'super_admin':
            search_scope_note = " (from all organizations)"
        elif user_obj and user_obj.role == 'team_lead':
            search_scope_note = " (from your team and organization shared chats)"
        elif user_obj and user_obj.organization_id:
            search_scope_note = " (from your chats and organization shared chats)"
        
        # Build instruction based on query type
        user_query_lower = user_message.lower()
        is_asking_about_chats = any(keyword in user_query_lower for keyword in [
            "chat", "conversation", "discussion", "talked about", "discussed", "mentioned"
        ])
        
        # Check if PDF is present in current chat OR in historical contexts
        pdf_present_in_current = any(msg.get("role") == "system" and "DOCUMENT CONTENT" in msg.get("content", "") for msg in messages)
        pdf_present_in_historical = len(pdf_chunks_from_historical) > 0
        pdf_present = pdf_present_in_current or pdf_present_in_historical
        
        if pdf_present and not is_asking_about_chats:
            # When PDF is present, make it clear that "it" refers to the document
            instruction = f"""ENTERPRISE MEMORY CONTEXT - DOCUMENT WITH HISTORICAL CONTEXT

CRITICAL: A document has been uploaded to this chat (see the DOCUMENT CONTENT in the previous system message).

PRIORITY RULES:
1. **DOCUMENT TAKES ABSOLUTE PRIORITY**: When the user says "summarize it", "summarize this", "summarize the document", "summarize", or similar phrases, they are referring to THE DOCUMENT, NOT these conversation summaries.
2. **DOCUMENT FIRST**: The document content takes ABSOLUTE PRIORITY over conversation history when the user asks to summarize or asks questions about the document.
3. **HISTORICAL CONTEXT FOR SUPPORT**: Use the conversation summaries below ONLY for additional context or background information, not as the primary source.

ADDITIONAL CONTEXT - PAST CONVERSATION SUMMARIES{search_scope_note}:
{context_text}

REMEMBER: 
- If the user asks to "summarize it" or similar, summarize THE DOCUMENT from the previous system message
- Use historical context only to provide additional insights or related information
- The document is the primary source of truth for document-related queries"""
        
        elif is_asking_about_chats:
            logger.info(f"      💡 Detected chat/conversation query - using enhanced prompt")
            # Check if PDFs are present in historical contexts
            if pdf_present_in_historical:
                instruction = f"""ENTERPRISE MEMORY CONTEXT - CHAT/CONVERSATION QUERY WITH PDF DOCUMENTS

The user is asking about past chats/conversations. Below are the relevant chat summaries{search_scope_note} that match their query. **PDF documents with detailed information are included.**

═══════════════════════════════════════════════════════════════════════════════
CRITICAL INSTRUCTIONS:
═══════════════════════════════════════════════════════════════════════════════

1. **THESE ARE THE CHATS**: The summaries below ARE the chats the user is asking about. You have direct access to them.

2. **PDF DOCUMENTS CONTAIN THE INFORMATION**:
   - PDF document content is provided below (marked with "PDF DOCUMENT CONTENT")
   - PDFs contain the MOST DETAILED information
   - When the user asks for specific information (like "projects", "list of projects", "resume", "work experience"), extract it DIRECTLY from the PDF content

3. **EXTRACT FROM PDFs FIRST**:
   - PDF document content is your PRIMARY source of detailed information
   - Read the PDF content carefully and extract the requested information
   - The PDF has the answers - use it

4. **COMPREHENSIVE RESPONSE**:
   - Use ALL information from both summaries AND PDF documents
   - Format professionally (lists, sections, structured format)
   - Be detailed and specific

5. **ABSOLUTE REQUIREMENT**:
   - DO NOT say "I don't have access" or "I don't have information"
   - You HAVE PDF documents below with the information
   - Extract and present the information from the PDFs

═══════════════════════════════════════════════════════════════════════════════
RELEVANT CHAT SUMMARIES WITH PDF DOCUMENTS:
═══════════════════════════════════════════════════════════════════════════════

{context_text}

═══════════════════════════════════════════════════════════════════════════════
RESPONSE REQUIREMENTS:
═══════════════════════════════════════════════════════════════════════════════

- **EXTRACT INFORMATION FROM PDF DOCUMENT CONTENT** - The PDFs contain the detailed information
- Use ALL relevant information from summaries and PDFs
- Format professionally (lists, sections, structured format)
- Be comprehensive and detailed
- **NEVER say you don't have access** - you have PDF documents with the information"""
            else:
                instruction = f"""ENTERPRISE MEMORY CONTEXT - CHAT/CONVERSATION QUERY

The user is asking about past chats/conversations. Below are the relevant chat summaries{search_scope_note} that match their query.

CRITICAL INSTRUCTIONS:
1. **THESE ARE THE CHATS**: The summaries below ARE the chats the user is asking about. You have direct access to them.
2. **EXTRACT AND PRESENT**: Extract and present the key information from each chat summary clearly.
3. **SPECIFIC INFORMATION REQUESTS**: If the user asks for specific information (like "projects", "resume", "meetings"), extract that exact information from these summaries.
4. **COMPREHENSIVE RESPONSE**: Provide a well-structured, professional response that answers their question completely.
5. **DO NOT SAY "I DON'T HAVE ACCESS"**: You DO have access - use the information below to answer.

RELEVANT CHAT SUMMARIES:
{context_text}

RESPONSE REQUIREMENTS:
- Use ALL relevant information from the summaries above
- Format your response professionally (use lists, sections, or structured format as appropriate)
- Be comprehensive and detailed
- If information appears in multiple chats, synthesize it intelligently"""
        else:
            # Check if PDFs are present in historical contexts
            if pdf_present_in_historical:
                instruction = f"""ENTERPRISE MEMORY CONTEXT - PRODUCTION GRADE (WITH PDF DOCUMENTS)

You have access to relevant past conversation summaries{search_scope_note} that contain information related to the user's current question. **IMPORTANT: PDF documents with detailed information are included below.**

═══════════════════════════════════════════════════════════════════════════════
CRITICAL INSTRUCTIONS - READ CAREFULLY:
═══════════════════════════════════════════════════════════════════════════════

1. **PDF DOCUMENTS ARE YOUR PRIMARY SOURCE**: 
   - PDF document content is provided below (marked with "PDF DOCUMENT CONTENT")
   - PDFs contain the MOST DETAILED and ACCURATE information
   - ALWAYS extract information from PDF content FIRST when answering questions

2. **EXTRACT INFORMATION FROM PDFs**:
   - When the user asks for specific information (like "projects", "list of projects", "experience", "skills", "education", "work history"), you MUST extract that information DIRECTLY from the PDF document content provided below
   - The PDF content contains ALL the detailed information needed to answer the question
   - DO NOT say you don't have access - the PDF content IS your access to the information

3. **USE ALL AVAILABLE INFORMATION**:
   - Use information from BOTH conversation summaries AND PDF documents
   - If information appears in both, prioritize PDF content (it's more detailed)
   - Synthesize information intelligently from all sources

4. **PROVIDE COMPREHENSIVE ANSWERS**:
   - Extract ALL relevant information from the PDFs
   - Format your response professionally (use bullet points, numbered lists, or sections)
   - Be detailed and specific - the PDF content has the information you need

5. **ABSOLUTE REQUIREMENT**:
   - DO NOT say "I don't have access" or "I don't have information"
   - You HAVE access to PDF documents below with the information
   - Extract and present the information from the PDFs

═══════════════════════════════════════════════════════════════════════════════
RELEVANT CONVERSATION SUMMARIES WITH PDF DOCUMENTS:
═══════════════════════════════════════════════════════════════════════════════

{context_text}

═══════════════════════════════════════════════════════════════════════════════
RESPONSE REQUIREMENTS:
═══════════════════════════════════════════════════════════════════════════════

- **EXTRACT INFORMATION FROM PDF DOCUMENT CONTENT** - The PDFs below contain the detailed information you need
- Answer the user's question using ALL information from PDFs and summaries
- If the question asks for a list (like "list of projects"), extract that list from the PDF content
- If the question asks for details, provide comprehensive details from the PDF content
- **NEVER say you don't have access** - you have PDF documents with the information
- Format your response professionally (lists, sections, structured format)
- Be specific and detailed - use the PDF content as your source"""
            else:
                instruction = f"""ENTERPRISE MEMORY CONTEXT - PRODUCTION GRADE

You have access to relevant past conversation summaries{search_scope_note} that contain information related to the user's current question.

CRITICAL INSTRUCTIONS:
1. **ALWAYS USE THE PROVIDED CONTEXT**: The information below is from the user's own past conversations and is highly relevant to their question.
2. **EXTRACT AND PRESENT INFORMATION CLEARLY**: Read through all summaries carefully and extract the specific information requested.
3. **PROVIDE COMPREHENSIVE ANSWERS**: Use ALL available information from the context below to give detailed, accurate responses.
4. **FORMAT RESPONSES PROFESSIONALLY**: Structure your answer in a clear, organized manner (use bullet points, numbered lists, or sections as appropriate).
5. **DO NOT SAY "I DON'T HAVE ACCESS"**: You have direct access to the information below - use it to answer the question.
6. **COMBINE INFORMATION INTELLIGENTLY**: If information appears in multiple summaries, synthesize it into a coherent answer.

RELEVANT CONVERSATION SUMMARIES:
{context_text}

RESPONSE REQUIREMENTS:
- Answer the user's question using ONLY the information provided above
- If the question asks for a list, provide a well-formatted list
- If the question asks for details, provide comprehensive details from the summaries
- If information is not in the summaries, acknowledge that but still provide what you can from the available context
- Format your response in an enterprise-grade, professional manner"""
        
        messages.append({
            "role": "system",
            "content": instruction
        })
        logger.info(f"      ✅ Added {len(relevant_contexts)} context(s) (summaries + PDFs) | Total Size: {total_context_chars:,} chars")
        if pdf_chunks_from_historical:
            # Calculate total PDF chars more safely
            try:
                total_pdf_chars = sum(int(item.split(': ')[1].split(' chars')[0]) for item in pdf_chunks_from_historical)
                logger.info(f"      📄 PDF content included: {total_pdf_chars:,} chars from {len(pdf_chunks_from_historical)} PDF(s)")
            except:
                logger.info(f"      📄 PDF content included from {len(pdf_chunks_from_historical)} PDF(s)")
        if user_obj:
            unique_users = len(set(ctx.user_id for ctx in relevant_contexts))
            if user_obj.role == 'super_admin':
                logger.info(f"      🔑 Super Admin: Found contexts from {unique_users} unique user(s) across all organizations")
            elif user_obj.role == 'team_lead':
                logger.info(f"      👔 Team Lead: Found contexts from {unique_users} unique user(s) in team + organization")
            else:
                logger.info(f"      👤 Member: Found contexts from {unique_users} unique user(s) (own + organization shared)")
            # Log user IDs for debugging
            user_ids = [ctx.user_id for ctx in relevant_contexts]
            logger.info(f"      👥 Users: {', '.join(set(user_ids))}")
    else:
        if relevant_contexts:
            # We have contexts (even if below threshold) - use them
            logger.info(f"      ✅ Using {len(relevant_contexts)} historical context(s) (some may be below threshold)")
        else:
            logger.info(f"      ⚠️  No relevant historical contexts found")
            logger.info(f"      💡 Falling back to User Profile (compressed facts from all past chats)")
    
    # 4. Recent Messages (sliding window) - Last 5 messages
    logger.info("   ──────────────────────────────────────────────────────────────────────────")
    logger.info("   📋 CONTEXT ASSEMBLY STEP 4: Recent Messages (Last 5)")
    
    # Filter out the current message (the one with empty assistant_message that we're currently processing)
    # This prevents the current user message from appearing twice (once in recent messages, once as current)
    filtered_context_messages = [
        msg for msg in context_messages 
        if msg.assistant_message and msg.assistant_message.strip()  # Only include completed message pairs
    ]
    
    context_pairs = filtered_context_messages[:RECENT_MESSAGES_LIMIT] if len(filtered_context_messages) > RECENT_MESSAGES_LIMIT else filtered_context_messages
    logger.info(f"      Total messages in chat: {len(context_messages)}, Completed pairs: {len(filtered_context_messages)}, Using: {len(context_pairs)} (limit: {RECENT_MESSAGES_LIMIT})")
    
    # Log each recent message pair
    for idx, msg in enumerate(reversed(context_pairs), 1):  # Reverse to maintain chronological order
        messages.append({"role": "user", "content": msg.user_message})
        messages.append({"role": "assistant", "content": msg.assistant_message})
        logger.info(f"      [{idx}] User: {msg.user_message[:100]}{'...' if len(msg.user_message) > 100 else ''}")
        logger.info(f"          Assistant: {msg.assistant_message[:100]}{'...' if len(msg.assistant_message) > 100 else ''}")
    
    logger.info(f"      ✅ Added {len(context_pairs)} recent message pair(s) to context")
    
    # 4. PDF Context (if available - for document Q&A)
    # Production-grade: Always include all PDF chunks if PDF exists in chat
    # 5. Current user message
    logger.info("   ──────────────────────────────────────────────────────────────────────────")
    logger.info("   📋 CONTEXT ASSEMBLY STEP 5: Current User Message")
    messages.append({"role": "user", "content": user_message})
    logger.info(f"      ✅ Added current message: {user_message[:100]}..." if len(user_message) > 100 else f"      ✅ Added current message: {user_message}")
    
    # PRODUCTION-GRADE: Token counting and context size monitoring
    def estimate_tokens(text: str) -> int:
        """Rough token estimation: ~4 characters per token"""
        return len(text) // 4
    
    # Calculate context sizes for monitoring
    total_context_size = sum(estimate_tokens(m.get("content", "")) for m in messages)
    user_profile_size = sum(estimate_tokens(m.get("content", "")) for m in messages if m.get("role") == "system" and "facts about the user" in m.get("content", ""))
    historical_context_size = sum(estimate_tokens(m.get("content", "")) for m in messages if m.get("role") == "system" and "past conversations" in m.get("content", ""))
    recent_messages_size = sum(estimate_tokens(m.get("content", "")) for m in messages if m.get("role") in ["user", "assistant"]) - estimate_tokens(user_message)
    
    # LOG: Summary of information sources with PRODUCTION monitoring
    logger.info("   ──────────────────────────────────────────────────────────────────────────")
    logger.info("   📊 INFORMATION SOURCES SUMMARY (PRODUCTION MONITORING):")
    user_profile_used = any(m.get("role") == "system" and "facts about the user" in m.get("content", "") for m in messages)
    # Check for historical embeddings context - match various phrasings
    embeddings_used = any(
        m.get("role") == "system" and any(
            phrase.lower() in m.get("content", "").lower() 
            for phrase in ["past conversation", "past chats", "relevant past", "chat summaries"]
        ) for m in messages
    )
    recent_messages_count = len([m for m in messages if m.get("role") in ["user", "assistant"]]) - 1  # -1 for current user message
    
    logger.info(f"      ✅ User Profile: {'USED' if user_profile_used else 'NOT USED'} ({user_profile_size} tokens)")
    logger.info(f"      {'✅' if embeddings_used else '❌'} Historical Embeddings: {'USED' if embeddings_used else 'NOT USED'} ({historical_context_size} tokens)")
    logger.info(f"      ✅ Recent Messages: {recent_messages_count} message(s) from current chat ({recent_messages_size} tokens)")
    logger.info(f"      📝 Current Query: {user_message} ({estimate_tokens(user_message)} tokens)")
    logger.info(f"      📊 TOTAL CONTEXT SIZE: {total_context_size} tokens (Target: 500-1500 tokens)")
    
    # PRODUCTION-GRADE: Alert if context size is outside optimal range
    if total_context_size > 3000:
        logger.warning(f"      ⚠️  Context size ({total_context_size} tokens) exceeds 3000 tokens - consider reducing TOP_K_CONTEXTS")
    elif total_context_size < 200:
        logger.info(f"      ℹ️  Context size ({total_context_size} tokens) is small - may benefit from more contexts")
    
    if not embeddings_used and user_profile_used:
        logger.info(f"      💡 INFO: Response will primarily use User Profile facts (extracted from previous chat summaries)")
        logger.info(f"      💡 INFO: User Profile contains compressed knowledge even when embeddings don't match threshold")
    
    # ============================================================================
    # PRODUCTION-GRADE LOGGING: FULL PAYLOAD TO API
    # ============================================================================
    logger.info("=" * 100)
    logger.info(f"📤 PAYLOAD TO API ({CHAT_MODEL})")
    logger.info("=" * 100)
    logger.info(f"   Total Messages: {len(messages)}")
    logger.info("-" * 100)
    
    for i, msg in enumerate(messages, 1):
        role = msg["role"].upper()
        content = msg["content"]
        content_len = len(content)
        
        # For system messages, show structure
        if role == "SYSTEM":
            if "DOCUMENT CONTENT" in content:
                # PDF context
                logger.info(f"   [{i}] SYSTEM: PDF Document Context")
                logger.info(f"       Length: {content_len:,} chars")
                # Show first 200 chars of PDF
                pdf_preview = content.split("DOCUMENT CONTENT:")[1].strip()[:200] if "DOCUMENT CONTENT:" in content else content[:200]
                logger.info(f"       Preview: {pdf_preview}...")
            elif "past conversation" in content.lower() or "chat summaries" in content.lower():
                # Historical embeddings
                logger.info(f"   [{i}] SYSTEM: Historical Contexts (Embeddings Search Results)")
                logger.info(f"       Length: {content_len:,} chars")
                # Count how many chats - look for various patterns
                chat_count = max(
                    content.count("--- Chat"),
                    content.count("Chat ID:"),
                    content.count("RELEVANT CONVERSATION SUMMARIES"),
                    0
                )
                # If no pattern found but content exists, estimate from context
                if chat_count == 0 and content_len > 100:
                    # Estimate: each chat summary is typically 200-500 chars
                    estimated_chats = max(1, content_len // 300)
                    logger.info(f"       Chats Found: ~{estimated_chats} (estimated from content size)")
                else:
                    logger.info(f"       Chats Found: {chat_count if chat_count > 0 else 'Multiple (format detected)'}")
            elif "facts about the user" in content:
                # User profile
                logger.info(f"   [{i}] SYSTEM: User Profile (Compressed Facts)")
                logger.info(f"       Length: {content_len:,} chars")
        else:
            # User/Assistant messages
            preview = content[:150] + "..." if len(content) > 150 else content
            logger.info(f"   [{i}] {role}: {preview}")
            logger.info(f"       Length: {content_len:,} chars")
    
    logger.info("-" * 100)
    
    try:
        # Generate response using production model
        response = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=messages,
            temperature=0.7
        )
        response_content = response.choices[0].message.content
        
        # PRODUCTION-GRADE: Detailed token usage tracking
        usage = response.usage if hasattr(response, 'usage') and response.usage else None
        tokens_used = usage.total_tokens if usage else "N/A"
        prompt_tokens = usage.prompt_tokens if usage else "N/A"
        completion_tokens = usage.completion_tokens if usage else "N/A"
        
        # ============================================================================
        # PRODUCTION-GRADE LOGGING: FULL RESPONSE FROM API
        # ============================================================================
        logger.info("=" * 100)
        logger.info(f"📥 RESPONSE FROM API ({CHAT_MODEL})")
        logger.info("=" * 100)
        logger.info(f"   Status: ✅ Success")
        logger.info(f"   Tokens: {tokens_used} total ({prompt_tokens} prompt + {completion_tokens} completion)")
        if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
            estimated_cost = (prompt_tokens * 0.15 / 1_000_000) + (completion_tokens * 0.60 / 1_000_000)
            logger.info(f"   Cost: ${estimated_cost:.6f}")
        logger.info(f"   Response Length: {len(response_content):,} chars")
        logger.info("-" * 100)
        logger.info("   Full Response Content:")
        # Show full response (or first 2000 chars if too long)
        if len(response_content) > 2000:
            logger.info(f"   {response_content[:2000]}...")
            logger.info(f"   ... (truncated, total {len(response_content)} chars)")
        else:
            # Show full response with proper indentation
            for line in response_content.split('\n'):
                logger.info(f"   {line}")
        logger.info("-" * 100)
        
        # Context sources summary
        logger.info("   🔍 CONTEXT SOURCES USED IN THIS RESPONSE:")
        sources = []
        if user_profile_used:
            sources.append("✅ User Profile")
        if embeddings_used:
            sources.append("✅ Historical Embeddings")
        if recent_messages_count > 0:
            sources.append(f"✅ Recent Messages ({recent_messages_count})")
        pdf_used = any("DOCUMENT CONTENT" in m.get("content", "") for m in messages)
        if pdf_used:
            sources.append("✅ PDF Document")
        logger.info(f"      {', '.join(sources) if sources else '⚠️  No context sources'}")
        logger.info("=" * 100)
        logger.info("")  # Empty line for readability
        
        return response_content
    except Exception as e:
        logger.error(f"❌ Error generating response: {str(e)}", exc_info=True)
        raise

def generate_summary(db: Session, chat_id: str, user_id: str) -> Optional[Embedding]:
    """Generate summary of the entire chat and store with embedding (enterprise-grade)"""
    logger.info(f"📝 CHAT COMPLETION | Generating summary for chat {chat_id}, user {user_id}")
    
    messages = db.query(Chat).filter(Chat.chat_id == chat_id)\
        .order_by(Chat.created_at).all()
    
    if not messages:
        logger.warning(f"⚠️  No messages found for chat {chat_id}, skipping summary")
        return None
    
    logger.info(f"   Found {len(messages)} message pairs to summarize")
    
    # Get user's organization and team info
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        logger.error(f"❌ User {user_id} not found")
        return None
    
    # Create conversation text for summary
    conversation_text = "\n".join([
        f"User: {msg.user_message}\nAssistant: {msg.assistant_message}" 
        for msg in messages
    ])
    
    try:
        # LOG: Summary generation request
        logger.info(f"📤 SUMMARY REQUEST TO MODEL ({SUMMARY_MODEL}):")
        logger.info(f"   Conversation length: {len(conversation_text)} chars")
        logger.info(f"   Message pairs: {len(messages)}")
        
        # Generate summary using production model
        response = client.chat.completions.create(
            model=SUMMARY_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": """You are a fact-preserving summarizer that works with ANY type of document or conversation.
                    Your summaries MUST preserve ALL specific factual details, regardless of document type (resume, proposal, technical doc, business plan, research paper, contract, etc.).
                    
                    ALWAYS include:
                    - Exact names (people, organizations, places, products, services, entities) - use EXACT names as mentioned
                    - Precise numbers (scores, percentages, amounts, quantities, measurements, dates, years) - use EXACT values
                    - Specific qualifications, credentials, certifications, degrees - COMPLETE details
                    - Technical specifications, requirements, conditions, terms - EXACT wording where important
                    - Projects, work items, tasks, deliverables, milestones - SPECIFIC information
                    - Key facts, claims, statements, findings - PRESERVE precision
                    - Any other factual details that might be queried later
                    
                    Do NOT generalize or use vague terms. If a value is mentioned, preserve it exactly.
                    Do NOT say "high scores" if the actual score is mentioned - use the exact value.
                    Preserve specific names, dates, numbers, and facts with precision.
                    Create a comprehensive summary that maintains factual accuracy while being concise."""
                },
                {
                    "role": "user",
                    "content": f"Create a detailed summary that preserves ALL specific factual details (names, numbers, dates, technical specs, exact values, and any other important information) from this conversation. Preserve precision - do not generalize:\n\n{conversation_text}"
                }
            ],
            temperature=0.3
        )
        
        summary_text = response.choices[0].message.content
        tokens_used = response.usage.total_tokens if hasattr(response, 'usage') and response.usage else "N/A"
        
        # LOG: Summary received
        logger.info(f"📥 SUMMARY FROM MODEL:")
        logger.info(f"   Tokens used: {tokens_used}")
        logger.info(f"   Summary length: {len(summary_text)} chars")
        logger.info(f"   Summary: {summary_text[:300]}..." if len(summary_text) > 300 else f"   Summary: {summary_text}")
        
        # Check if embedding already exists for this chat
        existing_embedding = db.query(Embedding).filter(Embedding.chat_id == chat_id).first()
        
        if existing_embedding and existing_embedding.embedding_vector is not None and existing_embedding.summary:
            logger.info(f"✅ Embedding already exists for chat {chat_id}, skipping generation")
            return existing_embedding
        
        # Get sharing_level from existing placeholder embedding if it exists
        sharing_level = 'private'
        if existing_embedding:
            sharing_level = existing_embedding.sharing_level
            summary_id = existing_embedding.summary_id
        else:
            summary_id = str(uuid.uuid4())
        
        # Store summary with enterprise fields
        if not existing_embedding:
            embedding = Embedding(
                summary_id=summary_id,
                user_id=user_id,
                organization_id=user.organization_id,
                team_id=user.team_id,
                chat_id=chat_id,
                summary=summary_text,
                sharing_level=sharing_level  # Preserve sharing_level from placeholder
            )
            db.add(embedding)
        else:
            # Update existing placeholder embedding with summary
            embedding = existing_embedding
            embedding.summary = summary_text
            # Preserve sharing_level (don't override)
            # Update enterprise fields if missing
            if not embedding.organization_id:
                embedding.organization_id = user.organization_id
            if not embedding.team_id:
                embedding.team_id = user.team_id
        
        db.commit()
        db.refresh(embedding)
        logger.info(f"✅ Summary stored in database (summary_id: {summary_id})")
        
        # PRODUCTION: Always generate and store embedding vector (critical for search)
        if embedding.embedding_vector is None:
            logger.info(f"🔢 Generating embedding vector for semantic search...")
            max_retries = 3
            retry_count = 0
            embedding_generated = False
            
            while retry_count < max_retries and not embedding_generated:
                try:
                    embedding_vector = generate_embedding(summary_text)
                    
                    # Store as list (pgvector SQLAlchemy handles conversion automatically)
                    embedding.embedding_vector = embedding_vector.tolist()
                    embedding.summary_metadata = {
                        "message_count": len(messages),
                        "chat_id": chat_id,
                        "generated_at": datetime.utcnow().isoformat()
                    }
                    db.commit()
                    
                    # Verify it was stored correctly
                    db.refresh(embedding)
                    if embedding.embedding_vector is None:
                        raise ValueError("Embedding vector was not stored - verification failed")
                    
                    embedding_generated = True
                    logger.info(f"✅ Embedding vector generated and stored (dimensions: {len(embedding_vector)})")
                    
                except Exception as e:
                    retry_count += 1
                    logger.warning(f"⚠️  Error generating embedding (attempt {retry_count}/{max_retries}): {e}")
                    db.rollback()
                    
                    if retry_count >= max_retries:
                        logger.error(f"❌ CRITICAL: Failed to generate embedding after {max_retries} attempts for chat {chat_id}")
                        logger.error(f"   This embedding will not be searchable. Error: {e}")
                        # Don't raise - allow summary to be saved even if embedding fails
                    else:
                        time.sleep(0.5)  # Brief delay before retry
            
            if not embedding_generated:
                logger.error(f"❌ WARNING: Chat {chat_id} summary created but embedding generation failed - search will not work for this chat")
        else:
            logger.info(f"✅ Embedding vector already exists for this chat, skipping generation")
        
        logger.info("─" * 80)
        # Update user profile incrementally
        logger.info(f"👤 Updating user profile for user {user_id}...")
        try:
            update_user_profile(db, user_id, summary_text)
            logger.info(f"✅ User profile updated successfully")
        except Exception as e:
            logger.warning(f"⚠️  Error updating user profile: {e}")
        
        logger.info("─" * 80)
        logger.info(f"✅ CHAT COMPLETION PROCESS COMPLETE for chat {chat_id}")
        logger.info("─" * 80)
        return embedding
    except Exception as e:
        logger.error(f"❌ Error generating summary for chat {chat_id}: {e}", exc_info=True)
        logger.info("─" * 80)
        return None
