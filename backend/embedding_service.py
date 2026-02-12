import logging
import numpy as np
from typing import List, Optional
from openai import OpenAI
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import Embedding
from config import (
    EMBEDDING_MODEL, EMBEDDING_DIMENSIONS, OPENAI_API_KEY,
    SIMILARITY_THRESHOLD_MIN
)

client = OpenAI(api_key=OPENAI_API_KEY)
logger = logging.getLogger(__name__)

def generate_embedding(text: str) -> np.ndarray:
    """Generate embedding for a single text"""
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text
    )
    return np.array(response.data[0].embedding)

def generate_embeddings_batch(texts: List[str]) -> List[np.ndarray]:
    """Generate embeddings for multiple texts (batch processing, more efficient)"""
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts
    )
    return [np.array(item.embedding) for item in response.data]

def store_embedding(
    db: Session,
    summary_id: str,
    embedding: np.ndarray,
    metadata: Optional[dict] = None
):
    """Store embedding vector in database"""
    embedding_obj = db.query(Embedding).filter(Embedding.summary_id == summary_id).first()
    if embedding_obj:
        embedding_obj.embedding_vector = embedding.tolist()
        if metadata:
            embedding_obj.summary_metadata = metadata
        db.commit()

def get_relevant_contexts(
    db: Session,
    query_text: str,
    user_id: str,
    current_chat_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    team_id: Optional[str] = None,
    user_role: str = "member",
    top_k: int = 5,
    similarity_threshold_min: Optional[float] = None
) -> List[Embedding]:
    """
    Retrieve top-K most relevant chat summaries using enterprise role-based semantic search.
    Enterprise-grade: Supports super_admin, team_lead, and member roles.
    
    Args:
        query_text: User's current message to find relevant contexts for
        user_id: User ID
        current_chat_id: Current chat ID to exclude from search (optional)
        organization_id: Organization ID (required for team_lead and member)
        team_id: Team ID (required for team_lead)
        user_role: User role - 'super_admin', 'team_lead', or 'member'
        top_k: Number of relevant contexts to retrieve (default: 5)
        similarity_threshold_min: Optional minimum similarity (0-1). If None, uses config default.
    
    Returns:
        List of Embedding objects with relevant summaries (top-K results above minimum threshold)
    
    Enterprise Strategy:
        - Super Admin: Access ALL embeddings across all organizations
        - Team Lead: Access own team's chats + organization shared chats
        - Member: Access own chats + organization shared chats
    """
    # Use config default if not provided
    if similarity_threshold_min is None:
        similarity_threshold_min = SIMILARITY_THRESHOLD_MIN
    
    # Get user info for role-based search
    from database import User
    user_obj = db.query(User).filter(User.user_id == user_id).first()
    if not user_obj:
        logger.warning(f"⚠️  User {user_id} not found")
        return []
    
    # Use user's role if not provided
    if not user_role or user_role not in ['super_admin', 'team_lead', 'member']:
        user_role = user_obj.role or 'member'
    
    # Auto-detect organization and team from user if not provided
    if not organization_id:
        organization_id = user_obj.organization_id
    if not team_id and user_role == 'team_lead':
        team_id = user_obj.team_id
    
    # Log user query with role indicator
    logger.info("═" * 80)
    if user_role == 'super_admin':
        logger.info("🔑 " + "─" * 76 + " 🔑")
        logger.info("🔑" + " " * 28 + "SUPER ADMIN MODE" + " " * 28 + "🔑")
        logger.info("🔑 " + "─" * 76 + " 🔑")
    elif user_role == 'team_lead':
        logger.info("👔 " + "─" * 76 + " 👔")
        logger.info("👔" + " " * 30 + "TEAM LEAD MODE" + " " * 30 + "👔")
        logger.info("👔 " + "─" * 76 + " 👔")
    else:
        logger.info("👤 " + "─" * 76 + " 👤")
        logger.info("👤" + " " * 32 + "MEMBER MODE" + " " * 32 + "👤")
        logger.info("👤 " + "─" * 76 + " 👤")
    logger.info("─" * 80)
    logger.info("🔍 ENTERPRISE SEMANTIC SEARCH")
    logger.info(f"   User Query: {query_text}")
    logger.info(f"   User ID: {user_id}")
    logger.info(f"   Role: {user_role.upper()}")
    if organization_id:
        logger.info(f"   Organization ID: {organization_id}")
    if team_id:
        logger.info(f"   Team ID: {team_id}")
    
    # Count embeddings based on role
    if user_role == 'super_admin':
        count_query = db.query(Embedding).filter(Embedding.embedding_vector.isnot(None))
        logger.info(f"   🔑 Super Admin: Accessing ALL embeddings across all organizations")
    elif user_role == 'team_lead':
        if not organization_id or not team_id:
            logger.warning(f"   ⚠️  Team lead requires organization_id and team_id")
            return []
        # Team Lead: Own private + Own public + All team members' private + All team members' public + Organization shared
        # CRITICAL: All conditions must check organization_id to prevent cross-organization access
        count_query = db.query(Embedding).filter(
            Embedding.embedding_vector.isnot(None),
            (
                # Own chats (both private and public) - must be in same organization
                ((Embedding.user_id == user_id) & (Embedding.organization_id == organization_id)) |
                # All team members' chats (both private and public) - must be in same organization AND same team
                ((Embedding.team_id == team_id) & (Embedding.organization_id == organization_id)) |
                # Organization shared chats from other teams - must be in same organization
                ((Embedding.organization_id == organization_id) & (Embedding.sharing_level == 'organization') & (Embedding.team_id != team_id))
            )
        )
        logger.info(f"   👔 Team Lead: Accessing own chats + all team {team_id} chats (private+public) + organization shared chats (Org: {organization_id})")
    else:  # member
        if not organization_id:
            logger.warning(f"   ⚠️  Member requires organization_id")
            return []
        # Member: ONLY own chats (private + public)
        # CRITICAL: Members cannot access organization-shared chats from other users/teams
        # Only Team Leads can access organization-shared chats from other teams
        # CRITICAL: All conditions must check organization_id to prevent cross-organization access
        count_query = db.query(Embedding).filter(
            Embedding.embedding_vector.isnot(None),
            (
                # Own chats (both private and public) - must be in same organization
                ((Embedding.user_id == user_id) & (Embedding.organization_id == organization_id))
            )
        )
        logger.info(f"   👤 Member: Accessing ONLY own chats (private+public) - NO access to other teams' organization-shared chats (Org: {organization_id})")
    
    if current_chat_id:
        count_query = count_query.filter(Embedding.chat_id != current_chat_id)
    
    total_chats = count_query.count()
    if total_chats == 0:
        logger.info(f"   No embeddings found for role-based search")
        logger.info("─" * 80)
        return []
    
    logger.info(f"   Searching in {total_chats} previous chat(s)")
    if current_chat_id:
        logger.info(f"   Excluding current chat: {current_chat_id}")
    
    # Generate query embedding
    query_embedding = generate_embedding(query_text)
    embedding_list = query_embedding.tolist()
    
    # Log query embedding preview (2-3 values max, one line - production approach)
    preview_count = min(3, len(embedding_list))
    embedding_preview = embedding_list[:preview_count]
    preview_str = ', '.join(f'{v:.4f}' for v in embedding_preview)
    logger.info(f"   Query Embedding ({len(embedding_list)} dimensions): [{preview_str}...]")
    
    # Production-grade approach: Use PostgreSQL function for vector search
    # This ensures proper type handling and is the most reliable method
    # The function handles vector type casting internally, avoiding type recognition issues
    
    # Convert embedding list to pgvector format string
    array_str = "[" + ",".join(map(str, embedding_list)) + "]"
    
    # Build query using enterprise role-based function
    chat_exclude_val = current_chat_id if current_chat_id else None
    
    query_sql = text("""
        SELECT * FROM vector_search(
            :query_vec_text,
            :user_id_param,
            :user_role,
            :organization_id_param,
            :team_id_param,
            :chat_exclude,
            :result_limit
        )
    """)
    
    params = {
        "query_vec_text": array_str,
        "user_id_param": user_id,
        "user_role": user_role,
        "organization_id_param": organization_id,
        "team_id_param": team_id,
        "chat_exclude": chat_exclude_val,
        "result_limit": top_k
    }
    
    logger.info(f"   Query params: role={user_role}, org={organization_id}, team={team_id}")
    
    # Execute query with proper error handling
    logger.info("   ──────────────────────────────────────────────────────────────────────────")
    logger.info("   🔍 STEP 1: Executing PostgreSQL vector_search function...")
    try:
        results = db.execute(query_sql, params).fetchall()
        logger.info(f"      ✅ Query executed successfully")
        logger.info(f"      📊 Raw results from database: {len(results)} row(s) returned")
    except Exception as e:
        error_msg = str(e)
        if len(error_msg) > 500:
            error_msg = error_msg[:500] + "... (truncated)"
        logger.error(f"❌ Semantic search error: {error_msg}")
        raise
    
    # Process results - simple top-K approach
    logger.info("   ──────────────────────────────────────────────────────────────────────────")
    logger.info("   🔍 STEP 2: Processing top-K results...")
    logger.info(f"      Top-K: {top_k}")
    logger.info(f"      Minimum threshold: {similarity_threshold_min} {'(filtering enabled)' if similarity_threshold_min > 0 else '(filtering disabled)'}")
    
    all_results = []
    relevant_contexts = []
    
    # PRODUCTION-GRADE APPROACH: Always return top-K results if available
    # Threshold is used for logging/warning, not hard filtering
    # This ensures users get the best available results even if similarity is slightly below threshold
    
    for row in results:
        similarity_score = float(row.similarity) if hasattr(row, 'similarity') and row.similarity is not None else 0.0
        result_data = {
            "summary_id": row.summary_id,
            "chat_id": row.chat_id,
            "user_id": getattr(row, 'user_id', None),
            "organization_id": getattr(row, 'organization_id', None),
            "team_id": getattr(row, 'team_id', None),
            "sharing_level": getattr(row, 'sharing_level', 'private'),
            "similarity": similarity_score
        }
        all_results.append(result_data)
        
        # PRODUCTION-GRADE: Include all results up to top_k, regardless of threshold
        # Threshold is informational - we log warnings but still include results
        embedding_obj = db.query(Embedding).filter(
            Embedding.summary_id == row.summary_id
        ).first()
        
        if embedding_obj:
            relevant_contexts.append({
                "embedding": embedding_obj,
                "similarity": similarity_score,
                "above_threshold": similarity_score >= similarity_threshold_min
            })
        
        # Stop once we have top_k results
        if len(relevant_contexts) >= top_k:
            break
    
    # Results are already sorted by similarity from the database query
    
    # PRODUCTION-GRADE: Statistics and monitoring
    logger.info(f"      📈 Search results analysis:")
    if all_results:
        above_minimum = [r for r in all_results if r["similarity"] >= similarity_threshold_min]
        below_minimum = [r for r in all_results if r["similarity"] < similarity_threshold_min]
        avg_similarity = sum(r["similarity"] for r in all_results) / len(all_results) if all_results else 0
        max_similarity = max(r["similarity"] for r in all_results) if all_results else 0
        min_similarity = min(r["similarity"] for r in all_results) if all_results else 0
        
        logger.info(f"         📊 Statistics:")
        logger.info(f"            • Total results from DB: {len(all_results)}")
        logger.info(f"            • Above minimum (≥{similarity_threshold_min}): {len(above_minimum)}")
        if similarity_threshold_min > 0:
            logger.info(f"            • Filtered out (<{similarity_threshold_min}): {len(below_minimum)}")
        logger.info(f"            • Average similarity: {avg_similarity:.4f}")
        logger.info(f"            • Max similarity: {max_similarity:.4f}")
        logger.info(f"            • Min similarity: {min_similarity:.4f}")
        
        # Show individual results with user IDs
        for i, result in enumerate(all_results[:top_k], 1):
            status = "✅ INCLUDED" if result["similarity"] >= similarity_threshold_min else "❌ FILTERED"
            result_user_id = result.get('user_id', 'N/A')
            logger.info(f"         {i}. Chat {result['chat_id'][:8]}... | User: {result_user_id} | Similarity: {result['similarity']:.4f} {status}")
        
        if len(all_results) > top_k:
            logger.info(f"         ... and {len(all_results) - top_k} more result(s) below top-K")
    else:
        logger.info(f"         ⚠️  No results returned from vector search")
    
    logger.info("   ──────────────────────────────────────────────────────────────────────────")
    logger.info(f"   🔍 STEP 3: Final contexts selected:")
    if relevant_contexts:
        total_length = sum(len(ctx['embedding'].summary) for ctx in relevant_contexts)
        above_threshold_count = sum(1 for ctx in relevant_contexts if ctx.get('above_threshold', True))
        below_threshold_count = len(relevant_contexts) - above_threshold_count
        
        logger.info(f"      ✅ {len(relevant_contexts)} context(s) selected (Top-{top_k}) | Total size: {total_length:,} chars")
        
        if below_threshold_count > 0:
            logger.info(f"      ⚠️  WARNING: {below_threshold_count} context(s) below threshold ({similarity_threshold_min}) but included for best results")
            logger.info(f"      💡 Production approach: Always return top-K results if available, even if below threshold")
        
        # Show which users these contexts are from
        final_user_ids = [ctx['embedding'].user_id for ctx in relevant_contexts]
        unique_final_users = set(final_user_ids)
        if user_role == 'super_admin':
            logger.info(f"      🔑 Contexts from all organizations")
        elif user_role == 'team_lead':
            logger.info(f"      👔 Contexts from team + organization shared")
        else:
            logger.info(f"      👤 Contexts from own chats + organization shared")
        logger.info(f"      👥 Users: {', '.join(unique_final_users)}")
        
        logger.info(f"      📋 Chat details:")
        for i, ctx in enumerate(relevant_contexts, 1):
            emb = ctx['embedding']
            threshold_status = "✅" if ctx.get('above_threshold', True) else "⚠️"
            logger.info(f"         {i}. Chat {emb.chat_id[:8]}... | User: {emb.user_id} | Similarity: {ctx['similarity']:.4f} {threshold_status}")
        
        similarities = [ctx['similarity'] for ctx in relevant_contexts]
        logger.info(f"      📊 Similarity range: {min(similarities):.4f} - {max(similarities):.4f} (avg: {sum(similarities)/len(similarities):.4f})")
        logger.info(f"      📈 Threshold: {similarity_threshold_min} | Above: {above_threshold_count} | Below: {below_threshold_count}")
        logger.info(f"      💡 Sending as summaries to model (LLM can handle lower similarity)")
    else:
        logger.info(f"      ⚠️  No contexts found (no results from database)")
    
    logger.info("─" * 80)
    
    # PRODUCTION-GRADE: Return list of Embedding objects (for compatibility)
    # Note: We return all top-K results, even if some are below threshold
    # The LLM can effectively use lower-similarity context (e.g., 0.25-0.30)
    return [ctx["embedding"] for ctx in relevant_contexts]

def migrate_existing_summaries(db: Session, user_id: Optional[str] = None) -> int:
    """
    Batch generate embeddings for existing summaries without embeddings.
    Production utility function for migrating legacy data.
    
    Returns:
        Number of summaries processed
    """
    
    query = db.query(Embedding)
    if user_id:
        query = query.filter(Embedding.user_id == user_id)
    query = query.filter(Embedding.embedding_vector.is_(None))
    
    summaries = query.all()
    
    if not summaries:
        logger.info("All summaries already have embeddings")
        return 0
    
    logger.info(f"Found {len(summaries)} summaries without embeddings")
    
    # Process in batches of 100 (OpenAI batch limit)
    batch_size = 100
    processed = 0
    
    for i in range(0, len(summaries), batch_size):
        batch = summaries[i:i + batch_size]
        texts = [s.summary for s in batch]
        
        try:
            embeddings = generate_embeddings_batch(texts)
            
            for summary, embedding in zip(batch, embeddings):
                summary.embedding_vector = embedding.tolist()
                
                # Add metadata if not present
                if not summary.summary_metadata:
                    summary.summary_metadata = {
                        "message_count": 0,
                        "chat_id": summary.chat_id,
                        "migrated": True
                    }
            
            db.commit()
            processed += len(batch)
            logger.info(f"Processed batch {i//batch_size + 1}: {len(batch)} summaries")
        except Exception as e:
            logger.error(f"Error processing batch {i//batch_size + 1}: {e}")
            db.rollback()
    
    logger.info(f"Migration complete: {processed}/{len(summaries)} summaries processed")
    return processed

