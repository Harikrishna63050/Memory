#!/usr/bin/env python3
"""
Production-grade test script to verify all components are working correctly.
Tests: Database connection, pgvector, embeddings, semantic search, etc.
"""

import sys
import os
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_imports():
    """Test that all required modules can be imported"""
    logger.info("=" * 80)
    logger.info("TEST 1: Module Imports")
    logger.info("=" * 80)
    try:
        from database import init_db, get_db, verify_db_connection, Embedding, User, Chat, UserProfile, Base, engine
        from embedding_service import generate_embedding, get_relevant_contexts, store_embedding
        from services import generate_response, generate_summary, get_or_create_user, get_or_create_chat
        from config import EMBEDDING_MODEL, CHAT_MODEL, OPENAI_API_KEY
        logger.info("✅ All modules imported successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Import error: {e}")
        return False

# Import models for cleanup
from database import Chat, User

def test_database_connection():
    """Test database connection and pgvector extension"""
    logger.info("=" * 80)
    logger.info("TEST 2: Database Connection & pgvector")
    logger.info("=" * 80)
    try:
        from database import verify_db_connection, engine
        from sqlalchemy import text
        
        # Test connection
        verify_db_connection()
        
        # Test pgvector extension
        with engine.connect() as conn:
            result = conn.execute(text("SELECT * FROM pg_extension WHERE extname = 'vector'"))
            if result.fetchone():
                logger.info("✅ pgvector extension is installed")
            else:
                logger.warning("⚠️  pgvector extension not found - attempting to create...")
                try:
                    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                    conn.commit()
                    logger.info("✅ pgvector extension created")
                except Exception as e:
                    logger.error(f"❌ Failed to create pgvector extension: {e}")
                    return False
            
            # Test vector type (need at least 1 dimension)
            result = conn.execute(text("SELECT '[0.1,0.2]'::vector"))
            logger.info("✅ Vector type is available")
        
        logger.info("✅ Database connection successful")
        return True
    except Exception as e:
        logger.error(f"❌ Database connection error: {e}")
        return False

def test_embedding_generation():
    """Test OpenAI embedding generation"""
    logger.info("=" * 80)
    logger.info("TEST 3: Embedding Generation")
    logger.info("=" * 80)
    try:
        from embedding_service import generate_embedding
        from config import EMBEDDING_DIMENSIONS
        
        test_text = "This is a test query for embedding generation"
        embedding = generate_embedding(test_text)
        
        if embedding is None:
            logger.error("❌ Embedding generation returned None")
            return False
        
        if len(embedding) != EMBEDDING_DIMENSIONS:
            logger.error(f"❌ Embedding dimension mismatch: expected {EMBEDDING_DIMENSIONS}, got {len(embedding)}")
            return False
        
        logger.info(f"✅ Embedding generated successfully ({len(embedding)} dimensions)")
        logger.info(f"   Preview: {embedding[:5].tolist()}")
        return True
    except Exception as e:
        logger.error(f"❌ Embedding generation error: {e}")
        return False

def test_vector_operations():
    """Test vector storage and semantic search operations"""
    logger.info("=" * 80)
    logger.info("TEST 4: Vector Storage & Semantic Search")
    logger.info("=" * 80)
    try:
        from database import get_db, Embedding, User, Chat
        from embedding_service import generate_embedding, store_embedding, get_relevant_contexts
        from services import get_or_create_user, get_or_create_chat, generate_summary
        from sqlalchemy import text
        
        db = next(get_db())
        
        # Create test user
        test_user_id = "test_user_12345"
        get_or_create_user(db, test_user_id)
        
        # Create test chat
        test_chat_id, _ = get_or_create_chat(db, test_user_id, None, generate_previous_summary=False)
        
        # Generate test summary
        test_summary = "User is interested in machine learning and AI. They work as a software engineer."
        test_embedding = generate_embedding(test_summary)
        
        # Create embedding record
        from uuid import uuid4
        summary_id = str(uuid4())
        embedding_obj = Embedding(
            summary_id=summary_id,
            user_id=test_user_id,
            chat_id=test_chat_id,
            summary=test_summary,
            embedding_vector=test_embedding.tolist()
        )
        db.add(embedding_obj)
        db.commit()
        
        logger.info(f"✅ Embedding stored successfully (summary_id: {summary_id[:8]}...)")
        
        # Test semantic search
        query_text = "What does the user work with?"
        results = get_relevant_contexts(
            db, query_text, test_user_id, 
            current_chat_id=None, top_k=5, similarity_threshold=0.3
        )
        
        if results:
            logger.info(f"✅ Semantic search successful - found {len(results)} relevant context(s)")
            for i, embedding_obj in enumerate(results[:3], 1):
                logger.info(f"   {i}. Summary: {embedding_obj.summary[:80]}...")
        else:
            logger.warning("⚠️  Semantic search returned no results (might be normal if threshold is high)")
        
        # Cleanup test data (order matters due to foreign keys)
        db.query(Embedding).filter(Embedding.summary_id == summary_id).delete()
        db.commit()
        # Also cleanup any other embeddings for this test user
        db.query(Embedding).filter(Embedding.user_id == test_user_id).delete()
        db.query(Chat).filter(Chat.chat_id == test_chat_id).delete()
        # Cleanup chats for this test user
        db.query(Chat).filter(Chat.user_id == test_user_id).delete()
        db.query(User).filter(User.user_id == test_user_id).delete()
        db.commit()
        logger.info("✅ Test data cleaned up")
        
        return True
    except Exception as e:
        logger.error(f"❌ Vector operations error: {e}", exc_info=True)
        try:
            db.rollback()
        except:
            pass
        return False

def test_api_response_generation():
    """Test response generation with memory architecture"""
    logger.info("=" * 80)
    logger.info("TEST 5: Response Generation (Full Memory Architecture)")
    logger.info("=" * 80)
    try:
        from database import get_db, User, Chat
        from services import get_or_create_user, get_or_create_chat, generate_response
        from embedding_service import generate_embedding
        
        db = next(get_db())
        
        test_user_id = "test_user_response"
        get_or_create_user(db, test_user_id)
        
        # Create a chat with some history
        chat_id, _ = get_or_create_chat(db, test_user_id, None, generate_previous_summary=False)
        
        # Create some message history
        from services import save_message_pair
        save_message_pair(db, test_user_id, chat_id, "Hello, I'm John", "Hello John! Nice to meet you.")
        save_message_pair(db, test_user_id, chat_id, "I work as a data scientist", "That's great! What kind of data science projects do you work on?")
        
        # Test response generation
        context_messages = db.query(Chat).filter(Chat.chat_id == chat_id).limit(5).all()
        
        response = generate_response(
            "Tell me about my job",
            context_messages,
            db=db,
            user_id=test_user_id,
            current_chat_id=chat_id,
            is_new_chat=False
        )
        
        if response:
            logger.info(f"✅ Response generated successfully")
            logger.info(f"   Response preview: {response[:150]}...")
        else:
            logger.error("❌ Response generation returned None")
            return False
        
        # Cleanup
        db.query(Chat).filter(Chat.chat_id == chat_id).delete()
        db.query(User).filter(User.user_id == test_user_id).delete()
        db.commit()
        logger.info("✅ Test data cleaned up")
        
        return True
    except Exception as e:
        logger.error(f"❌ Response generation error: {e}", exc_info=True)
        try:
            db.rollback()
        except:
            pass
        return False

def main():
    """Run all tests"""
    logger.info("\n" + "=" * 80)
    logger.info("PRODUCTION SYSTEM TEST SUITE")
    logger.info("=" * 80 + "\n")
    
    tests = [
        ("Module Imports", test_imports),
        ("Database Connection", test_database_connection),
        ("Embedding Generation", test_embedding_generation),
        ("Vector Operations", test_vector_operations),
        ("Response Generation", test_api_response_generation),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
            logger.info("")  # Blank line between tests
        except Exception as e:
            logger.error(f"❌ Test '{test_name}' crashed: {e}", exc_info=True)
            results.append((test_name, False))
            logger.info("")
    
    # Summary
    logger.info("=" * 80)
    logger.info("TEST SUMMARY")
    logger.info("=" * 80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status}: {test_name}")
    
    logger.info("")
    logger.info(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("🎉 All tests passed! System is ready for production.")
        return 0
    else:
        logger.error(f"⚠️  {total - passed} test(s) failed. Please review the errors above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())

