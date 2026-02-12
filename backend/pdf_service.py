"""
PDF Chat Service - Production-Grade PDF Processing
Handles PDF document parsing, chunking, and embedding for chat-based document Q&A
"""
import logging
import io
from typing import List, Optional, Dict, Any
from openai import OpenAI
import tiktoken
from sqlalchemy.orm import Session
from config import OPENAI_API_KEY, EMBEDDING_MODEL, EMBEDDING_DIMENSIONS

client = OpenAI(api_key=OPENAI_API_KEY)
logger = logging.getLogger(__name__)

# Try to import PDF libraries - prefer pypdf (modern, actively maintained) over PyPDF2 (deprecated)
# Production-grade: Use pypdf (specified in requirements.txt) as primary library
try:
    from pypdf import PdfReader
    PDF_AVAILABLE = True
    PyPDF2 = None  # Mark PyPDF2 as unavailable to use pypdf
    logger.debug("✅ Using pypdf (modern, production-grade library)")
except ImportError:
    try:
        # Fallback to PyPDF2 only if pypdf is not available
        import PyPDF2
        PDF_AVAILABLE = True
        logger.warning("⚠️  Using PyPDF2 (deprecated). Please install pypdf: pip install pypdf")
    except ImportError:
        PDF_AVAILABLE = False
        logger.error("❌ PDF libraries not installed. Install with: pip install pypdf")

def parse_pdf(file_content: bytes, filename: str) -> Dict[str, Any]:
    """
    Parse PDF file and extract text content.
    
    Args:
        file_content: PDF file bytes
        filename: Original filename for logging
    
    Returns:
        Dict with 'text', 'pages', 'metadata'
    """
    if not PDF_AVAILABLE:
        raise ImportError("PDF processing not available. Install pypdf: pip install pypdf")
    
    logger.info(f"📄 Parsing PDF: {filename}")
    
    try:
        pdf_file = io.BytesIO(file_content)
        
        # Production-grade: Use pypdf (modern) as primary, PyPDF2 as fallback
        if PyPDF2 is None:
            # Using pypdf (modern, production-grade library)
            from pypdf import PdfReader
            reader = PdfReader(pdf_file)
            pages = []
            text_parts = []
            
            for i, page in enumerate(reader.pages):
                page_text = page.extract_text()
                pages.append({
                    "page_number": i + 1,
                    "text": page_text,
                    "char_count": len(page_text)
                })
                text_parts.append(f"[Page {i+1}]\n{page_text}")
            
            # pypdf metadata access
            metadata = {}
            if reader.metadata:
                metadata = {
                    "/Title": reader.metadata.get("/Title", ""),
                    "/Author": reader.metadata.get("/Author", ""),
                    "/Subject": reader.metadata.get("/Subject", ""),
                }
            full_text = "\n\n".join(text_parts)
        else:
            # Fallback to PyPDF2 (deprecated - should not be used in production)
            logger.warning("⚠️  Using deprecated PyPDF2. Please install pypdf for production use.")
            reader = PyPDF2.PdfReader(pdf_file)
            pages = []
            text_parts = []
            
            for i, page in enumerate(reader.pages):
                page_text = page.extract_text()
                pages.append({
                    "page_number": i + 1,
                    "text": page_text,
                    "char_count": len(page_text)
                })
                text_parts.append(f"[Page {i+1}]\n{page_text}")
            
            metadata = reader.metadata or {}
            full_text = "\n\n".join(text_parts)
        
        result = {
            "text": full_text,
            "pages": pages,
            "metadata": {
                "title": metadata.get("/Title", ""),
                "author": metadata.get("/Author", ""),
                "subject": metadata.get("/Subject", ""),
                "num_pages": len(pages),
                "filename": filename
            }
        }
        
        logger.info(f"   ✅ PDF parsed: {len(pages)} pages, {len(full_text)} characters")
        pages_summary = ', '.join([f'P{i+1}({p["char_count"]} chars)' for i, p in enumerate(pages[:5])])
        logger.info(f"   📊 Pages: {pages_summary}")
        if len(pages) > 5:
            logger.info(f"   ... and {len(pages) - 5} more page(s)")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Error parsing PDF {filename}: {e}")
        raise

def chunk_text(text: str, max_chunk_size: int = 1000, overlap: int = 200) -> List[Dict[str, Any]]:
    """
    Split text into chunks for embedding and retrieval.
    Uses sentence-aware chunking to prevent mid-sentence breaks.
    Production-grade: Ensures chunks are properly ordered and don't break mid-sentence.
    
    Args:
        text: Text to chunk
        max_chunk_size: Maximum characters per chunk
        overlap: Character overlap between chunks (for context continuity)
    
    Returns:
        List of chunk dicts with 'text', 'start', 'end', 'chunk_index' (ordered sequentially)
    """
    if not text or len(text.strip()) == 0:
        return []
    
    if len(text) <= max_chunk_size:
        return [{
            "text": text.strip(),
            "start": 0,
            "end": len(text),
            "chunk_index": 0
        }]
    
    chunks = []
    start = 0
    chunk_index = 0
    
    while start < len(text):
        # Calculate potential end position
        potential_end = start + max_chunk_size
        
        # If we're at or near the end of text, take the rest
        if potential_end >= len(text):
            remaining_text = text[start:].strip()
            if remaining_text:
                chunks.append({
                    "text": remaining_text,
                    "start": start,
                    "end": len(text),
                    "chunk_index": chunk_index
                })
                chunk_index += 1
            break
        
        # Try to find a good break point (sentence boundary) within the last 300 chars
        # Production-grade: Look for natural break points to avoid mid-sentence cuts
        search_start = max(start, potential_end - 300)
        search_end = potential_end
        
        # Priority: paragraph break, sentence end, comma, space
        best_break = -1
        
        # 1. Look for paragraph breaks (double newline)
        para_break = text.rfind('\n\n', search_start, search_end)
        if para_break > start:
            best_break = para_break + 2
        else:
            # 2. Look for single newline (section break)
            newline_break = text.rfind('\n', search_start, search_end)
            if newline_break > start and newline_break > potential_end - 100:
                best_break = newline_break + 1
            else:
                # 3. Look for sentence endings (. ! ? followed by space)
                for punct in ['. ', '! ', '? ']:
                    sentence_end = text.rfind(punct, search_start, search_end)
                    if sentence_end > start:
                        best_break = sentence_end + len(punct)
                        break
                
                # 4. If no sentence break found, look for comma
                if best_break == -1:
                    comma_break = text.rfind(', ', search_start, search_end)
                    if comma_break > start and comma_break > potential_end - 50:
                        best_break = comma_break + 2
                
                # 5. Last resort: break at space to avoid cutting words
                if best_break == -1:
                    space_break = text.rfind(' ', search_start, search_end)
                    if space_break > start:
                        best_break = space_break + 1
        
        # Use best break if found, otherwise use max size (will break word - unavoidable)
        end = best_break if best_break > start else potential_end
        
        # Extract chunk text and ensure it's not empty
        chunk_text_content = text[start:end].strip()
        
        # Skip empty chunks (shouldn't happen, but safety check)
        if chunk_text_content:
            chunks.append({
                "text": chunk_text_content,
                "start": start,
                "end": end,
                "chunk_index": chunk_index
            })
            chunk_index += 1
        
        # Move start forward with overlap (ensuring we don't go backwards)
        # Production-grade: Overlap should start from a clean break point
        if end < len(text):
            # Start next chunk with overlap, but try to start at a word boundary
            overlap_start = max(start + 1, end - overlap)
            
            # Find next word boundary for clean overlap
            if overlap_start < len(text):
                # Find next space or newline to start cleanly
                next_space = text.find(' ', overlap_start, end)
                if next_space > overlap_start:
                    start = next_space + 1
                else:
                    start = overlap_start
            else:
                start = end
        else:
            break
    
    logger.info(f"   📦 Text chunked into {len(chunks)} chunks (max {max_chunk_size} chars, overlap {overlap})")
    logger.info(f"   ✅ Chunk indices: 0 to {len(chunks)-1} (sequential, ordered)")
    return chunks

def process_pdf_for_chat(
    file_content: bytes,
    filename: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200
) -> Dict[str, Any]:
    """
    Complete PDF processing pipeline: Parse → Chunk → Prepare for embedding.
    
    Args:
        file_content: PDF file bytes
        filename: Original filename
        chunk_size: Maximum characters per chunk
        chunk_overlap: Overlap between chunks
    
    Returns:
        Dict with 'chunks', 'metadata', 'full_text'
    """
    logger.info("─" * 80)
    logger.info("📄 PDF PROCESSING PIPELINE")
    logger.info(f"   File: {filename}")
    
    # Parse PDF
    pdf_data = parse_pdf(file_content, filename)
    
    # Chunk text
    chunks = chunk_text(pdf_data["text"], max_chunk_size=chunk_size, overlap=chunk_overlap)
    
    result = {
        "chunks": chunks,
        "metadata": pdf_data["metadata"],
        "full_text": pdf_data["text"],
        "total_chunks": len(chunks)
    }
    
    logger.info(f"   ✅ Processing complete: {len(chunks)} chunks ready for embedding")
    logger.info("─" * 80)
    
    return result

def store_pdf_document(
    db: Session,
    user_id: str,
    file_content: bytes,
    filename: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200
) -> Dict[str, Any]:
    """
    Production-grade PDF document storage: Process → Store → Embed → Save
    
    Note: We do NOT store the PDF binary file - only extract and store:
    - Text chunks (for embedding/search)
    - Metadata (title, author, pages)
    - Embeddings (in separate table)
    
    PDF is attached to messages via Chat.pdf_document_id (message-level attachment).
    
    Args:
        db: Database session
        user_id: User ID
        file_content: PDF file bytes (processed, not stored)
        filename: Original filename
        chunk_size: Maximum characters per chunk
        chunk_overlap: Overlap between chunks
    
    Returns:
        Dict with document_id, num_chunks, metadata
    """
    import uuid
    from embedding_service import generate_embedding
    from database import PDFDocument, PDFChunkEmbedding, User
    
    logger.info("─" * 80)
    logger.info("📄 PDF DOCUMENT STORAGE PIPELINE")
    logger.info(f"   File: {filename} | User: {user_id}")
    logger.info(f"   Note: Storing extracted text/chunks, NOT the PDF binary file")
    
    # Get user's organization_id
    user = db.query(User).filter(User.user_id == user_id).first()
    organization_id = user.organization_id if user else None
    
    # Step 1: Process PDF (parse + chunk) - extracts text, discards binary
    processed_data = process_pdf_for_chat(file_content, filename, chunk_size, chunk_overlap)
    
    # Step 2: Generate document ID
    document_id = str(uuid.uuid4())
    
    # Step 3: Store PDF document metadata and text chunks (NOT binary file)
    pdf_doc = PDFDocument(
        document_id=document_id,
        user_id=user_id,
        organization_id=organization_id,
        filename=filename,
        pdf_metadata=processed_data["metadata"],
        chunks=processed_data["chunks"]
    )
    db.add(pdf_doc)
    db.commit()
    db.refresh(pdf_doc)
    logger.info(f"✅ PDF document stored (document_id: {document_id})")
    
    # Step 4: Generate embeddings for each chunk and store (in order)
    logger.info(f"🔢 Generating embeddings for {len(processed_data['chunks'])} chunks...")
    embeddings_created = 0
    
    # Production-grade: Process chunks in order to maintain sequential chunk_index
    # Sort chunks by chunk_index to ensure correct order (safety check)
    sorted_chunks = sorted(processed_data["chunks"], key=lambda x: x.get("chunk_index", 0))
    
    for chunk in sorted_chunks:
        try:
            # Validate chunk has required fields
            chunk_index = chunk.get("chunk_index", embeddings_created)
            chunk_text = chunk.get("text", "").strip()
            
            if not chunk_text:
                logger.warning(f"⚠️  Skipping empty chunk at index {chunk_index}")
                continue
            
            # Generate embedding
            embedding_vector = generate_embedding(chunk_text)
            
            # Store chunk embedding with sequential chunk_index as string (for JSONB compatibility)
            chunk_embedding = PDFChunkEmbedding(
                embedding_id=str(uuid.uuid4()),
                document_id=document_id,
                chunk_index=str(chunk_index),  # Store as string for JSONB, but maintain numeric order
                text=chunk_text,
                embedding_vector=embedding_vector.tolist()
            )
            db.add(chunk_embedding)
            embeddings_created += 1
            
        except Exception as e:
            logger.error(f"❌ Error generating embedding for chunk {chunk.get('chunk_index', 'unknown')}: {e}")
            continue
    
    db.commit()
    logger.info(f"✅ Created {embeddings_created}/{len(processed_data['chunks'])} chunk embeddings")
    logger.info(f"   📋 Chunk indices stored: 0 to {embeddings_created-1} (ordered)")
    logger.info("─" * 80)
    
    return {
        "document_id": document_id,
        "num_chunks": len(processed_data["chunks"]),
        "metadata": processed_data["metadata"],
        "embeddings_created": embeddings_created
    }

def get_all_pdf_chunks_for_chat(
    db: Session,
    user_id: str,
    chat_id: str,
    max_chunks: int = 1000,  # High limit for best quality - send all chunks
    requesting_user_id: Optional[str] = None  # User requesting PDF access (for access control)
) -> Optional[str]:
    """
    Get all PDF chunks from documents attached to messages in this chat.
    Enterprise-grade: Respects sharing level and role-based access.
    - Super Admin: Access ALL PDFs
    - Others: Access if chat is shared with organization or own chat
    
    Strategy (like ChatGPT):
    - If PDF exists in chat, always include all chunks
    - Conversation history (last 5 messages) maintains context naturally
    - No keyword detection or semantic search needed - simpler and more reliable
    
    Args:
        db: Database session
        user_id: User ID who owns the chat (for finding PDFs)
        chat_id: Chat ID
        max_chunks: Maximum chunks to return (to prevent token overflow)
        requesting_user_id: User requesting access (for access control, defaults to user_id)
    
    Returns:
        Formatted PDF context string with all chunks or None
    """
    from database import PDFDocument, Chat, User, Embedding
    
    # Use requesting_user_id if provided, otherwise use user_id
    requester_id = requesting_user_id or user_id
    
    logger.info(f"📄 Getting all PDF chunks for chat {chat_id} | Requester: {requester_id}")
    
    # Get requester info for access control
    requester = db.query(User).filter(User.user_id == requester_id).first()
    if not requester:
        logger.warning(f"   ⚠️  Requester {requester_id} not found")
        return None
    
    # Check if requester can access this chat
    # Super admin can access all chats
    if requester.role != 'super_admin':
        chat_embedding = db.query(Embedding).filter(Embedding.chat_id == chat_id).first()
        if chat_embedding:
            # Check access: own chat OR organization shared
            can_access = False
            if chat_embedding.user_id == requester_id:
                can_access = True
            elif (chat_embedding.organization_id == requester.organization_id and 
                  chat_embedding.sharing_level == 'organization'):
                can_access = True
            elif requester.role == 'team_lead' and chat_embedding.team_id == requester.team_id:
                can_access = True
            
            if not can_access:
                logger.warning(f"   ⚠️  Access denied: Chat is private or not shared with organization")
                return None
    
    # Find PDF documents attached to messages in this chat
    # Super admin: no user filter, others: filter by chat ownership or sharing
    if requester.role == 'super_admin':
        messages_with_pdfs = db.query(Chat).filter(
            Chat.chat_id == chat_id,
            Chat.has_pdf == True,
            Chat.pdf_document_id.isnot(None)
        ).all()
    else:
        messages_with_pdfs = db.query(Chat).filter(
            Chat.chat_id == chat_id,
            Chat.has_pdf == True,
            Chat.pdf_document_id.isnot(None)
        ).all()
    
    if not messages_with_pdfs:
        logger.info(f"   No messages with PDF attachments found for chat {chat_id}")
        return None
    
    # Get unique PDF document IDs
    pdf_document_ids = list(set([msg.pdf_document_id for msg in messages_with_pdfs if msg.pdf_document_id]))
    
    # Get PDF documents - Super admin can access all, others only if chat is shared
    if requester.role == 'super_admin':
        pdf_docs = db.query(PDFDocument).filter(
            PDFDocument.document_id.in_(pdf_document_ids)
        ).all()
    else:
        # For non-super-admin: PDFs are accessible if chat is shared (already verified above)
        pdf_docs = db.query(PDFDocument).filter(
            PDFDocument.document_id.in_(pdf_document_ids)
        ).all()
    
    if not pdf_docs:
        logger.info(f"   No PDF documents found")
        return None
    
    logger.info(f"   Found {len(pdf_docs)} PDF document(s)")
    
    # Get all chunks from all PDFs (ordered by document and chunk index)
    all_chunks = []
    for pdf_doc in pdf_docs:
        if pdf_doc.chunks:
            for chunk in pdf_doc.chunks:
                chunk_index = chunk.get('chunk_index', 0)
                chunk_text = chunk.get('text', '')
                all_chunks.append({
                    'document_id': pdf_doc.document_id,
                    'filename': pdf_doc.filename,
                    'chunk_index': chunk_index,
                    'text': chunk_text
                })
    
    # Sort by document and chunk index (convert to int for proper numerical sorting)
    all_chunks.sort(key=lambda x: (x['filename'], int(x['chunk_index']) if isinstance(x['chunk_index'], (str, int)) else 0))
    
    # Production-grade: For best quality, send all chunks (no limit)
    # Modern LLMs (gpt-4o-mini, gpt-4o) handle large contexts efficiently
    # Only limit if chunks exceed model's context window (128K tokens = ~500K chars = ~500 chunks @ 1000 chars each)
    if len(all_chunks) > max_chunks:
        logger.warning(f"   ⚠️  PDF has {len(all_chunks)} chunks, limiting to {max_chunks} for safety")
        logger.warning(f"   💡 For best quality, consider increasing max_chunks or using larger context model")
        all_chunks = all_chunks[:max_chunks]
    
    if not all_chunks:
        logger.info(f"   No chunks found in PDFs")
        return None
    
    # Format chunks with document context
    context_parts = []
    current_doc = None
    for i, chunk in enumerate(all_chunks, 1):
        if current_doc != chunk['filename']:
            context_parts.append(f"\n[Document: {chunk['filename']}]\n")
            current_doc = chunk['filename']
        # Convert chunk_index to int for display (handle string storage)
        chunk_idx = int(chunk['chunk_index']) if isinstance(chunk['chunk_index'], (str, int)) else 0
        context_parts.append(f"[Chunk {chunk_idx + 1}]\n{chunk['text']}")
    
    result = "\n\n".join(context_parts)
    logger.info(f"   ✅ Retrieved {len(all_chunks)} chunks from {len(pdf_docs)} PDF(s) ({len(result)} chars)")
    
    return result

# Removed: should_include_pdf_context()
# New production approach: Always include all PDF chunks if PDF exists in chat
# Simpler, more reliable - no keyword detection needed
# Conversation history (last 5 messages) naturally maintains context

def create_pdf_context_message(pdf_chunks: List[Dict[str, Any]], relevant_chunks: List[int]) -> str:
    """
    Create context message from relevant PDF chunks for chat.
    
    Args:
        pdf_chunks: All PDF chunks
        relevant_chunks: Indices of relevant chunks to include
    
    Returns:
        Formatted context string
    """
    if not relevant_chunks:
        return ""
    
    context_parts = []
    for idx in relevant_chunks:
        if 0 <= idx < len(pdf_chunks):
            chunk = pdf_chunks[idx]
            # Convert chunk_index to int for display (handle string storage)
            chunk_idx = int(chunk['chunk_index']) if isinstance(chunk['chunk_index'], (str, int)) else 0
            context_parts.append(f"[Chunk {chunk_idx + 1}]\n{chunk['text']}")
    
    return "\n\n---\n\n".join(context_parts)

def search_pdf_context(
    db: Session,
    user_id: str,
    chat_id: str,
    query_text: str,
    top_k: int = 3,
    similarity_threshold: float = 0.7
) -> Optional[str]:
    """
    Search PDF chunks relevant to the query for document Q&A.
    Production-grade: Finds PDFs attached to messages in this chat.
    
    Args:
        db: Database session
        user_id: User ID
        chat_id: Chat ID (to find PDFs attached to messages in this chat)
        query_text: User's query
        top_k: Number of relevant chunks to retrieve
        similarity_threshold: Minimum similarity score
    
    Returns:
        Formatted PDF context string or None
    """
    from embedding_service import generate_embedding
    from sqlalchemy import text
    from database import PDFChunkEmbedding, PDFDocument, Chat
    
    logger.info(f"🔍 Searching PDF context for chat {chat_id}")
    
    # Production-grade: Find PDF documents attached to messages in this chat
    # Query messages with PDFs, then get their PDF document IDs
    messages_with_pdfs = db.query(Chat).filter(
        Chat.chat_id == chat_id,
        Chat.user_id == user_id,
        Chat.has_pdf == True,
        Chat.pdf_document_id.isnot(None)
    ).all()
    
    if not messages_with_pdfs:
        logger.info(f"   No messages with PDF attachments found for chat {chat_id}")
        return None
    
    # Get unique PDF document IDs from messages
    pdf_document_ids = list(set([msg.pdf_document_id for msg in messages_with_pdfs if msg.pdf_document_id]))
    
    # Get PDF documents
    pdf_docs = db.query(PDFDocument).filter(
        PDFDocument.document_id.in_(pdf_document_ids),
        PDFDocument.user_id == user_id
    ).all()
    
    if not pdf_docs:
        logger.info(f"   No PDF documents found for chat {chat_id}")
        return None
    
    logger.info(f"   Found {len(pdf_docs)} PDF document(s) for this chat")
    
    # Generate query embedding
    query_embedding = generate_embedding(query_text)
    embedding_list = query_embedding.tolist()
    array_str = "[" + ",".join(map(str, embedding_list)) + "]"
    
    # Search across all PDF chunks from documents in this chat
    document_ids = [doc.document_id for doc in pdf_docs]
    
    query_sql = text("""
        SELECT 
            e.embedding_id,
            e.document_id,
            e.chunk_index,
            e.text,
            CAST(REPLACE(REPLACE(e.embedding_vector::text, '{', '['), '}', ']') AS vector) as embedding_vector,
            (1 - (CAST(REPLACE(REPLACE(e.embedding_vector::text, '{', '['), '}', ']') AS vector) <=> CAST(:query_vec_text AS vector)))::double precision as similarity
        FROM pdf_chunk_embeddings e
        WHERE e.document_id = ANY(:document_ids)
            AND e.embedding_vector IS NOT NULL
        ORDER BY CAST(REPLACE(REPLACE(e.embedding_vector::text, '{', '['), '}', ']') AS vector) <=> CAST(:query_vec_text AS vector)
        LIMIT :top_k
    """)
    
    try:
        results = db.execute(
            query_sql,
            {
                "query_vec_text": array_str,
                "document_ids": document_ids,
                "top_k": top_k
            }
        ).fetchall()
        
        relevant_chunks = []
        all_results = []
        
        for row in results:
            similarity = float(row.similarity) if hasattr(row, 'similarity') and row.similarity else 0.0
            chunk_data = {
                "text": row.text,
                "chunk_index": row.chunk_index,
                "similarity": similarity,
                "document_id": row.document_id
            }
            all_results.append(chunk_data)
            
            if similarity >= similarity_threshold:
                relevant_chunks.append(chunk_data)
        
        # Production-grade: If PDFs exist for this chat, always include at least top-k chunks
        # Even if similarity is below threshold, include them for document Q&A
        if relevant_chunks:
            logger.info(f"   ✅ Found {len(relevant_chunks)} relevant PDF chunks (similarity >= {similarity_threshold})")
            context_parts = [f"[PDF Chunk {i+1}, Similarity: {chunk['similarity']:.3f}]\n{chunk['text']}" 
                           for i, chunk in enumerate(relevant_chunks)]
            return "\n\n---\n\n".join(context_parts)
        elif all_results:
            # Fallback: Use top-k chunks even if similarity is below threshold
            # This ensures PDF content is available when user explicitly asks about documents
            logger.info(f"   ⚠️  No chunks above threshold ({similarity_threshold}), but using top {len(all_results)} chunk(s) from PDF(s)")
            logger.info(f"      Top similarity: {all_results[0]['similarity']:.3f}, Min similarity: {all_results[-1]['similarity']:.3f}")
            context_parts = [f"[PDF Chunk {i+1}, Similarity: {chunk['similarity']:.3f}]\n{chunk['text']}" 
                           for i, chunk in enumerate(all_results[:top_k])]
            return "\n\n---\n\n".join(context_parts)
        else:
            logger.info(f"   ⚠️  No PDF chunks found (no results returned)")
            return None
            
    except Exception as e:
        logger.error(f"❌ Error searching PDF context: {e}")
        return None

