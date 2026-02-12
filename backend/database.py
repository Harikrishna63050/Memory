from sqlalchemy import create_engine, Column, String, Text, DateTime, ForeignKey, inspect, text, Index, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime
import logging

# Import pgvector for vector support
try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    Vector = None

from config import DATABASE_URL

logger = logging.getLogger(__name__)

Base = declarative_base()

class Organization(Base):
    """
    Organization table - top level in enterprise hierarchy.
    Production-grade: Enterprise multi-tenant structure.
    """
    __tablename__ = "organizations"
    
    organization_id = Column(String, primary_key=True)
    organization_name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Team(Base):
    """
    Team table - teams belong to organizations.
    Production-grade: Teams have team leads.
    """
    __tablename__ = "teams"
    
    team_id = Column(String, primary_key=True)
    organization_id = Column(String, ForeignKey("organizations.organization_id"), nullable=False, index=True)
    team_name = Column(String, nullable=False)
    team_lead_id = Column(String, nullable=True)  # User ID of team lead
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_org_team', 'organization_id', 'team_id'),
    )

class User(Base):
    """
    User table with enterprise hierarchy association.
    Production-grade: Users belong to organization and team, have roles.
    Enterprise constraint: Only ONE super_admin can exist in the entire system.
    """
    __tablename__ = "users"
    
    user_id = Column(String, primary_key=True)
    organization_id = Column(String, ForeignKey("organizations.organization_id"), nullable=True, index=True)
    team_id = Column(String, ForeignKey("teams.team_id"), nullable=True, index=True)
    role = Column(String, nullable=False, default='member')  # 'super_admin', 'team_lead', 'member'
    password_hash = Column(String, nullable=True)  # For authentication (hashed password)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Composite indexes for enterprise queries
    __table_args__ = (
        Index('idx_org_user', 'organization_id', 'user_id'),
        Index('idx_team_user', 'team_id', 'user_id'),
        Index('idx_user_role', 'user_id', 'role'),
        Index('idx_role_super_admin', 'role'),  # For super admin queries
    )

class Chat(Base):
    """
    Chats table stores question-response pairs in the same row.
    Enterprise-grade: Includes organization_id, team_id for better structure and verification.
    All messages with the same chat_id belong to the same conversation.
    
    Production-grade: Added PDF attachment support at message level.
    - has_pdf: Boolean flag indicating if this message has a PDF attached
    - pdf_document_id: Reference to PDFDocument if has_pdf=True
    """
    __tablename__ = "chats"
    
    message_id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False, index=True)
    organization_id = Column(String, ForeignKey("organizations.organization_id"), nullable=True, index=True)
    team_id = Column(String, ForeignKey("teams.team_id"), nullable=True, index=True)
    chat_id = Column(String, nullable=False, index=True)
    user_message = Column(Text, nullable=False)
    assistant_message = Column(Text, nullable=False)
    
    # PDF attachment fields (production-grade: message-level PDF attachment)
    has_pdf = Column(Boolean, default=False, nullable=False, index=True)
    pdf_document_id = Column(String, ForeignKey("pdf_documents.document_id"), nullable=True, index=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Composite indexes for efficient enterprise querying
    __table_args__ = (
        Index('idx_user_chat', 'user_id', 'chat_id'),
        Index('idx_org_chat', 'organization_id', 'chat_id'),
        Index('idx_team_chat', 'team_id', 'chat_id'),
        Index('idx_chat_created', 'chat_id', 'created_at'),
        Index('idx_chat_pdf', 'chat_id', 'has_pdf'),
    )

class Embedding(Base):
    """
    Embeddings table stores chat summaries with vector embeddings for semantic search.
    Enterprise-grade: Includes organization, team, and sharing level.
    """
    __tablename__ = "embeddings"
    
    summary_id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False, index=True)
    organization_id = Column(String, ForeignKey("organizations.organization_id"), nullable=True, index=True)
    team_id = Column(String, ForeignKey("teams.team_id"), nullable=True, index=True)
    chat_id = Column(String, nullable=False, index=True, unique=True)  # One summary per chat
    summary = Column(Text, nullable=False)
    
    # Vector embedding (1536 dimensions for text-embedding-3-small)
    if Vector:
        embedding_vector = Column(Vector(1536), nullable=True)
    else:
        embedding_vector = Column(Text, nullable=True)
    
    # Enterprise sharing fields
    sharing_level = Column(String, nullable=False, default='private')  # 'private' or 'organization'
    shared_at = Column(DateTime, nullable=True)
    
    # Metadata for flexible querying
    summary_metadata = Column(JSONB, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Composite indexes for efficient enterprise querying
    __table_args__ = (
        Index('idx_user_embeddings', 'user_id', 'chat_id'),
        Index('idx_org_embeddings', 'organization_id', 'sharing_level'),
        Index('idx_team_embeddings', 'team_id', 'organization_id'),
        Index('idx_org_shared', 'organization_id', 'sharing_level'),
    )

class UserProfile(Base):
    """
    User Profile table stores compressed facts about users (replaces GlobalSummary).
    Uses structured data instead of merged summaries for better scalability.
    Schema: user_id, preferences, important_facts, topics_of_interest, created_at, updated_at
    """
    __tablename__ = "user_profiles"
    
    user_id = Column(String, ForeignKey("users.user_id"), primary_key=True)
    
    # Structured data instead of single merged summary
    preferences = Column(JSONB, nullable=True)  # e.g., {"language": "en", "timezone": "PST"}
    important_facts = Column(JSONB, nullable=True)  # e.g., ["Works at Google", "Lives in SF"]
    topics_of_interest = Column(JSONB, nullable=True)  # e.g., ["Python", "Machine Learning"]
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class PDFDocument(Base):
    """
    PDF Documents table stores PDF metadata and extracted text chunks.
    Enterprise-grade: PDFs belong to users in organizations.
    When chat is shared, PDFs in that chat become accessible to organization.
    """
    __tablename__ = "pdf_documents"
    
    document_id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False, index=True)
    organization_id = Column(String, ForeignKey("organizations.organization_id"), nullable=True, index=True)
    filename = Column(String, nullable=False)
    
    # Sharing control: PDFs inherit sharing from chats they're attached to
    # This is determined dynamically based on chat sharing_level
    # No need to store here - calculated from Chat.sharing_level via pdf_document_id
    
    # Store PDF metadata and chunks (NOT the binary PDF file)
    pdf_metadata = Column(JSONB, nullable=True, name='metadata')
    chunks = Column(JSONB, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    __table_args__ = (
        Index('idx_org_pdf', 'organization_id', 'user_id'),
    )

class PDFChunkEmbedding(Base):
    """
    PDF Chunk Embeddings table stores embeddings for PDF chunks.
    Enables semantic search over PDF content.
    Schema: embedding_id, document_id, chunk_index, text, embedding_vector, created_at
    """
    __tablename__ = "pdf_chunk_embeddings"
    
    embedding_id = Column(String, primary_key=True)
    document_id = Column(String, ForeignKey("pdf_documents.document_id"), nullable=False, index=True)
    chunk_index = Column(String, nullable=False)  # Store as string for JSONB compatibility
    text = Column(Text, nullable=False)
    
    # Vector embedding for semantic search
    if Vector:
        embedding_vector = Column(Vector(1536), nullable=True)
    else:
        embedding_vector = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Composite index
    __table_args__ = (
        Index('idx_document_chunk', 'document_id', 'chunk_index'),
    )

# Database setup with production settings
engine = create_engine(
    DATABASE_URL, 
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=10,
    max_overflow=20,
    echo=False  # Set to True for SQL query logging in development
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def check_tables_exist():
    """Check if all required tables exist in the database"""
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    
    required_tables = [
        "organizations",
        "teams",
        "users",
        "chats",
        "embeddings",
        "user_profiles",
        "pdf_documents",
        "pdf_chunk_embeddings"
    ]
    
    missing_tables = [table for table in required_tables if table not in existing_tables]
    
    if missing_tables:
        logger.warning(f"Missing tables: {missing_tables}")
        return False
    
    return True

def init_db():
    """Initialize database - create tables if they don't exist"""
    if not check_tables_exist():
        logger.info("Creating missing tables...")
        Base.metadata.create_all(bind=engine)
        logger.info("Tables created successfully!")
    else:
        logger.debug("All tables exist and verified.")
    
    if not check_tables_exist():
        raise Exception("Failed to create all required tables")

def setup_pgvector_extension():
    """Check and create pgvector extension if it doesn't exist (production-grade)"""
    try:
        # First, check if extension exists
        with engine.connect() as connection:
            result = connection.execute(text("SELECT * FROM pg_extension WHERE extname = 'vector'"))
            if result.fetchone():
                logger.debug("pgvector extension is installed")
                return True
        
        # Extension doesn't exist, try to create it
        logger.info("pgvector extension not found. Attempting to install...")
        try:
            with engine.connect().execution_options(autocommit=True) as connection:
                # Ensure extension is created in public schema
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public"))
                connection.commit()
            logger.info("✅ pgvector extension installed successfully")
            return True
        except Exception as create_error:
            error_msg = str(create_error)
            logger.warning(f"Could not install pgvector extension: {error_msg}")
            
            error_lower = error_msg.lower()
            if "extension" in error_lower and ("not available" in error_lower or "does not exist" in error_lower):
                logger.error("❌ pgvector extension is not installed on PostgreSQL server. Vector search will not work.")
                logger.error("   Please install pgvector: https://github.com/pgvector/pgvector")
            elif "permission" in error_lower or "privilege" in error_lower:
                logger.error("❌ Insufficient privileges to install pgvector extension. Vector search will not work.")
            else:
                logger.error(f"❌ Failed to install pgvector extension: {error_msg}")
            return False
    except Exception as e:
        logger.error(f"❌ Could not verify/setup pgvector extension: {e}")
        return False

def create_vector_search_function():
    """Create vector_search PostgreSQL function for enterprise semantic search (one-time setup)
    Supports role-based search: super_admin, team_lead, member"""
    try:
        # First, ensure pgvector extension is installed and available
        if not setup_pgvector_extension():
            raise Exception("pgvector extension is not available. Cannot create vector_search function.")
        
        with engine.connect() as connection:
            # Verify vector type exists and ensure extension is available
            try:
                type_check = connection.execute(text("""
                    SELECT EXISTS (
                        SELECT 1 FROM pg_type WHERE typname = 'vector'
                    )
                """)).fetchone()
                
                if not type_check or not type_check[0]:
                    # Extension might be in different schema, try to create in public
                    logger.warning("⚠️  Vector type not found, ensuring extension is in public schema...")
                    with engine.connect().execution_options(autocommit=True) as ext_conn:
                        ext_conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public"))
                        ext_conn.commit()
                    # Refresh connection
                    connection.execute(text("SELECT 1"))
                    logger.info("✅ Ensured pgvector extension is available")
            except Exception as e:
                logger.warning(f"⚠️  Could not verify vector type: {e}")
                # Try one more time to create extension
                try:
                    with engine.connect().execution_options(autocommit=True) as ext_conn:
                        ext_conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public"))
                        ext_conn.commit()
                except:
                    pass
            
            # Drop existing functions first
            try:
                connection.execute(text("DROP FUNCTION IF EXISTS vector_search(text, text, text, text, text, text, int)"))
                connection.execute(text("DROP FUNCTION IF EXISTS vector_search(text, text, text, text, int)"))
                connection.execute(text("DROP FUNCTION IF EXISTS vector_search(text, text, text, int)"))
                connection.commit()
            except:
                connection.rollback()
            
            logger.info("Creating vector_search PostgreSQL function (enterprise role-based)...")
            connection.execute(text("""
                CREATE FUNCTION vector_search(
                    query_vec_text text,
                    user_id_param text,
                    user_role text,
                    organization_id_param text DEFAULT NULL,
                    team_id_param text DEFAULT NULL,
                    chat_exclude text DEFAULT NULL,
                    result_limit int DEFAULT 5
                )
                RETURNS TABLE (
                    summary_id character varying,
                    user_id character varying,
                    organization_id character varying,
                    team_id character varying,
                    chat_id character varying,
                    summary text,
                    embedding_vector vector,
                    sharing_level character varying,
                    summary_metadata jsonb,
                    created_at timestamp without time zone,
                    similarity double precision
                )
                LANGUAGE plpgsql
                AS $$
                DECLARE
                    query_vector vector;
                BEGIN
                    query_vector := CAST(query_vec_text AS vector);
                    
                    RETURN QUERY
                    SELECT 
                        e.summary_id,
                        e.user_id,
                        e.organization_id,
                        e.team_id,
                        e.chat_id,
                        e.summary,
                        CAST(REPLACE(REPLACE(e.embedding_vector::text, '{', '['), '}', ']') AS vector) as embedding_vector,
                        e.sharing_level,
                        e.summary_metadata,
                        e.created_at,
                        (1 - (CAST(REPLACE(REPLACE(e.embedding_vector::text, '{', '['), '}', ']') AS vector) <=> query_vector))::double precision as similarity
                    FROM embeddings e
                    WHERE e.embedding_vector IS NOT NULL
                        AND (chat_exclude IS NULL OR e.chat_id != chat_exclude)
                        AND (
                            -- Super Admin: Access ALL embeddings
                            (user_role = 'super_admin')
                            OR
                            -- Team Lead: Own chats + All team chats (private+public) + Organization shared
                            -- CRITICAL: All conditions must check organization_id to prevent cross-organization access
                            (user_role = 'team_lead' AND organization_id_param IS NOT NULL AND team_id_param IS NOT NULL AND (
                                -- Own chats (both private and public) - must be in same organization
                                (e.user_id = user_id_param AND e.organization_id = organization_id_param)
                                OR
                                -- All team members' chats (both private and public) - must be in same organization AND same team
                                (e.team_id = team_id_param AND e.organization_id = organization_id_param)
                                OR
                                -- Organization shared chats from other teams - must be in same organization
                                (e.organization_id = organization_id_param AND e.sharing_level = 'organization' AND e.team_id != team_id_param)
                            ))
                            OR
                            -- Member: ONLY own chats (private+public)
                            -- CRITICAL: Members cannot access organization-shared chats from other users/teams
                            -- Only Team Leads can access organization-shared chats from other teams
                            -- CRITICAL: All conditions must check organization_id to prevent cross-organization access
                            (user_role = 'member' AND organization_id_param IS NOT NULL AND (
                                -- Own chats (both private and public) - must be in same organization
                                (e.user_id = user_id_param AND e.organization_id = organization_id_param)
                            ))
                        )
                    ORDER BY CAST(REPLACE(REPLACE(e.embedding_vector::text, '{', '['), '}', ']') AS vector) <=> query_vector
                    LIMIT result_limit;
                END;
                $$;
            """))
            connection.commit()
            logger.info("✅ vector_search function created successfully (enterprise role-based)")
    except Exception as e:
        logger.error(f"❌ CRITICAL: Could not create vector_search function: {e}")
        raise Exception(f"Failed to create vector_search function: {e}")

def create_vector_index_if_needed():
    """
    Create vector index for faster similarity search (production optimization).
    Only creates index if it doesn't exist and there's data to index.
    """
    try:
        with engine.connect() as connection:
            # Check if index already exists
            index_check = connection.execute(text("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_indexes 
                    WHERE tablename = 'embeddings' 
                    AND indexname = 'idx_embedding_vector'
                )
            """)).fetchone()
            
            if index_check and index_check[0]:
                logger.debug("Vector index already exists")
                return
            
            # Check if we have data to index
            data_check = connection.execute(text("""
                SELECT COUNT(*) FROM embeddings WHERE embedding_vector IS NOT NULL
            """)).fetchone()
            
            if not data_check or data_check[0] == 0:
                logger.debug("No embeddings to index yet, skipping index creation")
                return
            
            embedding_count = data_check[0]
            logger.info(f"Creating vector index for {embedding_count} embeddings...")
            
            # Calculate optimal lists parameter (recommended: rows / 1000)
            lists = max(10, min(1000, embedding_count // 1000))
            
            # Create IVFFlat index for approximate nearest neighbor search (faster)
            # For exact search, use HNSW instead (slower but more accurate)
            connection.execute(text(f"""
                CREATE INDEX idx_embedding_vector ON embeddings 
                USING ivfflat (embedding_vector vector_cosine_ops) 
                WITH (lists = {lists})
            """))
            connection.commit()
            logger.info(f"✅ Vector index created successfully (ivfflat with {lists} lists)")
            
    except Exception as e:
        logger.warning(f"Could not create vector index: {e} (this is optional, search will work without it)")

def create_super_admin_constraint():
    """Create database constraint to ensure only one super_admin exists (production-grade)"""
    try:
        with engine.connect() as connection:
            # Create function to check super admin count
            connection.execute(text("""
                CREATE OR REPLACE FUNCTION check_super_admin_count()
                RETURNS TRIGGER AS $$
                DECLARE
                    super_admin_count INTEGER;
                BEGIN
                    IF NEW.role = 'super_admin' THEN
                        SELECT COUNT(*) INTO super_admin_count
                        FROM users
                        WHERE role = 'super_admin' AND user_id != NEW.user_id;
                        
                        IF super_admin_count > 0 THEN
                            RAISE EXCEPTION 'Only one super_admin can exist in the system. Existing super_admin: %', 
                                (SELECT user_id FROM users WHERE role = 'super_admin' LIMIT 1);
                        END IF;
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
            """))
            
            # Drop existing trigger if exists
            connection.execute(text("DROP TRIGGER IF EXISTS enforce_single_super_admin ON users"))
            
            # Create trigger
            connection.execute(text("""
                CREATE TRIGGER enforce_single_super_admin
                BEFORE INSERT OR UPDATE ON users
                FOR EACH ROW
                EXECUTE FUNCTION check_super_admin_count();
            """))
            
            connection.commit()
            logger.info("✅ Super admin constraint created (only one super_admin allowed)")
    except Exception as e:
        logger.warning(f"⚠️  Could not create super admin constraint: {e}")
        logger.warning("   Constraint will be enforced in application layer")

def verify_db_connection():
    """Verify database connection and tables on startup"""
    try:
        # Test connection
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        
        # Setup pgvector extension (creates it if needed)
        setup_pgvector_extension()
        
        # Create vector_search function (one-time setup)
        create_vector_search_function()
        
        # Create super admin constraint (production-grade)
        create_super_admin_constraint()
        
        # Create vector index if needed (production optimization)
        create_vector_index_if_needed()
        
        # Ensure extension is available in all sessions by setting search_path
        with engine.connect() as connection:
            connection.execute(text("SET search_path TO public"))
            connection.commit()
        
        # Check tables
        if check_tables_exist():
            # Verify embedding_vector column is vector type, migrate if needed
            with engine.connect() as connection:
                result = connection.execute(text("""
                    SELECT data_type 
                    FROM information_schema.columns 
                    WHERE table_name='embeddings' AND column_name='embedding_vector'
                """)).fetchone()
                
                # Check column type - must be USER-DEFINED (vector type) or 'vector'
                # Production-grade: Always ensure column is vector type
                if not result or result[0] not in ('USER-DEFINED', 'vector'):
                    # Column exists but is not vector type - needs migration
                    logger.warning("⚠️  embedding_vector column is not vector type. Migrating to production-grade vector type...")
                    
                    # Production-grade migration: convert text column to vector type
                    try:
                        # First try ALTER TYPE (preserves data)
                        logger.info("   Attempting ALTER TYPE migration...")
                        connection.execute(text("ALTER TABLE embeddings ALTER COLUMN embedding_vector TYPE vector USING embedding_vector::vector"))
                        connection.commit()
                        logger.info("✅ Successfully migrated embedding_vector column to vector type")
                    except Exception as e:
                        connection.rollback()
                        # Fallback: drop and recreate if ALTER TYPE fails
                        logger.warning(f"   ALTER TYPE failed ({str(e)[:100]}), using DROP/ADD approach...")
                        try:
                            connection.execute(text("ALTER TABLE embeddings DROP COLUMN IF EXISTS embedding_vector"))
                            connection.execute(text("ALTER TABLE embeddings ADD COLUMN embedding_vector vector(1536)"))
                            connection.commit()
                            logger.info("✅ Successfully recreated embedding_vector column as vector type")
                        except Exception as e2:
                            connection.rollback()
                            logger.error(f"❌ Failed to migrate embedding_vector column: {e2}")
                            raise Exception(f"CRITICAL: embedding_vector column must be vector type. Migration failed: {e2}")
            
            logger.info("✅ Database connection successful. All tables verified.")
            return True
        else:
            logger.info("Database connected but some tables are missing. Creating them...")
            init_db()
            logger.info("All tables created successfully.")
            return True
    except Exception as e:
        logger.error(f"Database connection error: {str(e)}")
        raise

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
