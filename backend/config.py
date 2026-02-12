"""
Production configuration for the application
"""
import os
from dotenv import load_dotenv

load_dotenv()

# OpenAI Models - Production Grade
EMBEDDING_MODEL = "text-embedding-3-small"  # Best cost/performance ratio, 1536 dimensions
EMBEDDING_DIMENSIONS = 1536
CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")  # gpt-4o-mini: best balance, gpt-4-turbo for highest quality
SUMMARY_MODEL = os.getenv("OPENAI_SUMMARY_MODEL", "gpt-4o-mini")  # gpt-4o-mini for efficiency

# Semantic Search Configuration - Production Grade (Top-K Approach)
TOP_K_CONTEXTS = int(os.getenv("TOP_K_CONTEXTS", "5"))  # Top K most relevant contexts to retrieve and send to model
SIMILARITY_THRESHOLD_MIN = float(os.getenv("SIMILARITY_THRESHOLD_MIN", "0.30"))  # Warning threshold (0-1). Results below this are logged as warnings but still included. Set to 0 to disable warnings. Production approach: Always return top-K results if available.
RECENT_MESSAGES_LIMIT = int(os.getenv("RECENT_MESSAGES_LIMIT", "5"))  # Last N message pairs

# Enterprise Role-Based Search
# Search is automatic based on user role (no configuration needed):
# - super_admin: Access ALL chats across all organizations
# - team_lead: Access own team + organization shared chats  
# - member: Access own chats + organization shared chats


# Database Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/memory")

# API Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Logging Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")  # DEBUG, INFO, WARNING, ERROR
VERBOSE_LOGGING = os.getenv("VERBOSE_LOGGING", "true").lower() == "true"  # Enable detailed logging (default: true for debugging)

