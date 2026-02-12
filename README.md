# Memory Application

A chat application with memory capabilities that stores conversations, generates summaries, and creates embeddings for semantic search.

## Features

- **Simple User Interface**: Select a User ID and start chatting immediately (no login required)
- **Chat Persistence**: All conversations are stored in the database
- **Context Awareness**: Uses last 5 messages for conversation context
- **Automatic Summaries**: Generates summaries of conversations (every 10 messages)
- **Memory Embeddings**: Creates embeddings for summaries to enable semantic search

## Project Structure

```
Memory/
├── backend/
│   ├── database.py      # Database models and setup
│   ├── models.py        # Pydantic models for API
│   ├── services.py      # Business logic (chat, summaries, embeddings)
│   ├── main.py          # FastAPI application
│   ├── requirements.txt # Python dependencies
│   └── .env.example     # Environment variables template
├── frontend/
│   ├── src/
│   │   ├── App.js       # Main React component
│   │   ├── App.css      # Styles
│   │   ├── index.js     # React entry point
│   │   └── index.css    # Global styles
│   ├── public/
│   │   └── index.html   # HTML template
│   └── package.json     # Node.js dependencies
└── README.md
```

## Database Schema

The database uses a simplified 3-table structure optimized for production:

### 1. **users** table
Stores user information:
- `user_id` (Primary Key)
- `created_at` (Timestamp)

### 2. **chats** table
Stores all messages in a single table. All messages with the same `chat_id` belong to the same conversation:
- `message_id` (Primary Key)
- `user_id` (Foreign Key to users, indexed)
- `chat_id` (Indexed - groups messages into conversations)
- `role` ('user' or 'assistant')
- `content` (Message text)
- `created_at` (Timestamp, indexed)

**Note**: Each message is stored in a separate row to maintain proper ordering and allow for:
- Multiple user messages before an assistant response
- Better query performance with proper indexing
- Easy message retrieval and pagination

### 3. **embeddings** table
Stores chat summaries with their embeddings:
- `summary_id` (Primary Key)
- `user_id` (Foreign Key to users, indexed)
- `chat_id` (Unique, one summary per chat)
- `summary` (Text summary of the conversation)
- `embeddings` (JSON string of embedding vector)
- `created_at` (Timestamp)

## Setup Instructions

### Prerequisites

- PostgreSQL installed and running
- Python 3.8+
- Node.js 14+

### Database Setup

1. Create PostgreSQL database:
```bash
createdb memory
# Or using psql:
psql -U postgres
CREATE DATABASE memory;
```

### Backend Setup

1. Navigate to the backend directory:
```bash
cd backend
```

2. Create a virtual environment (recommended):
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
```bash
cp env.example .env
# Edit .env and add your DATABASE_URL and OPENAI_API_KEY
# Default DATABASE_URL: postgresql://postgres:password@localhost:5432/memory
```

5. Run the backend server:
```bash
python main.py
# Or: uvicorn main:app --reload
```

The backend will run on `http://localhost:8000` and automatically:
- Connect to PostgreSQL database
- Verify all required tables exist
- Create missing tables if needed

### Frontend Setup

1. Navigate to the frontend directory:
```bash
cd frontend
```

2. Install dependencies:
```bash
npm install
```

3. Create a `.env` file (optional, if backend is not on default port):
```bash
REACT_APP_API_URL=http://localhost:8000
```

4. Start the development server:
```bash
npm start
```

The frontend will run on `http://localhost:3000`

## Usage

1. Open the application in your browser (usually `http://localhost:3000`)
2. Enter a User ID in the input field (e.g., "user123")
3. Type a message and click "Send" or press Enter
4. The AI will respond using the last 5 messages as context
5. Continue chatting - summaries will be generated automatically every 10 messages

## API Endpoints

- `POST /api/chat` - Send a message and get AI response
  - Body: `{ "user_id": "string", "chat_id": "string (optional)", "message": "string" }`
  
- `GET /api/chat/{chat_id}/messages` - Get all messages for a chat

- `GET /api/user/{user_id}/chats` - Get all chats for a user

- `GET /api/chat/{chat_id}/summaries` - Get all summaries for a chat

## Configuration

- Summary generation threshold: Modify `message_count_threshold` in `services.py` (default: 10 messages)
- Context window size: Modify `limit` in `get_last_messages()` call (default: 5 messages)
- OpenAI models: Modify model names in `services.py` (currently using `gpt-3.5-turbo` and `text-embedding-3-small`)

## Requirements

- Python 3.8+
- Node.js 14+
- PostgreSQL 12+
- OpenAI API key

## Database Configuration

The application uses PostgreSQL and automatically:
- Checks table existence on startup
- Creates missing tables if needed
- Verifies database connection before accepting requests

Set `DATABASE_URL` in your `.env` file:
```
DATABASE_URL=postgresql://postgres:password@localhost:5432/memory
```

