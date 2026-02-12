# Chat Sharing & Access Control Guide

## Overview
This document explains how chat sharing and access control works for each role in the enterprise memory system: **Super Admin**, **Team Lead**, and **Member**.

---

## Role-Based Access Control

### 🔑 Super Admin

**Access Level:** Full access to ALL chats across ALL organizations

#### What Super Admin Can Access:
- ✅ **ALL private chats** from all users in all organizations
- ✅ **ALL public (organization-shared) chats** from all organizations
- ✅ **ALL PDFs** attached to any chat, regardless of sharing level
- ✅ **ALL chat history** and embeddings across the entire system

#### Search Capabilities:
- Can search through **ALL embeddings** in the database
- No restrictions based on organization, team, or user
- Can access any chat by chat_id without permission checks

#### Implementation:
```python
# Super Admin search query
count_query = db.query(Embedding).filter(
    Embedding.embedding_vector.isnot(None)
)
# No filters - accesses everything
```

#### Example Scenario:
```
Super Admin (Abcd) can:
- Access Praveen's private chat about "Project X"
- Access Raja's organization-shared chat about "Team Meeting"
- Access Vivek's private chat about "Client Discussion"
- Access ALL chats from Organization "Yanthraa"
- Access ALL chats from any other organization
```

---

### 👔 Team Lead

**Access Level:** Own chats + All team members' chats + Organization shared chats

#### What Team Lead Can Access:

1. **Own Chats (Private + Public)**
   - All chats created by the team lead themselves
   - Both private and organization-shared chats

2. **All Team Members' Chats (Private + Public)**
   - All chats from any member in their team
   - Both private and organization-shared chats
   - **Key Point:** Team leads have access to team members' private chats

3. **Organization Shared Chats from Other Teams**
   - Chats shared with organization from other teams in the same organization
   - Only organization-shared chats (not private chats from other teams)

#### Search Capabilities:
- Can search through:
  - Own chats (private + public)
  - All team members' chats (private + public)
  - Organization shared chats from other teams

#### Implementation:
```python
# Team Lead search query
count_query = db.query(Embedding).filter(
    Embedding.embedding_vector.isnot(None),
    (
        # Own chats (both private and public)
        (Embedding.user_id == user_id) |
        # All team members' chats (both private and public)
        (Embedding.team_id == team_id) |
        # Organization shared chats from other teams
        ((Embedding.organization_id == organization_id) & 
         (Embedding.sharing_level == 'organization') & 
         (Embedding.team_id != team_id))
    )
)
```

#### Example Scenario:
```
Team Lead: Praveen (Team: BART, Organization: Yanthraa)

Can Access:
✅ Praveen's own private chat about "Personal Notes"
✅ Praveen's own organization-shared chat about "Project Ideas"
✅ Team member John's private chat about "Client Feedback"
✅ Team member Sarah's organization-shared chat about "Meeting Notes"
✅ Team member Mike's private chat about "Technical Details"
✅ Organization-shared chat from Team "Holocron" (Raja's team)
✅ Organization-shared chat from Team "FAT" (Vivek's team)

Cannot Access:
❌ Private chat from Team "Holocron" (not shared with organization)
❌ Private chat from Team "FAT" (not shared with organization)
❌ Chats from other organizations
```

---

### 👤 Member

**Access Level:** ONLY own chats (private + public)

#### What Member Can Access:

1. **Own Chats (Private + Public)**
   - All chats created by the member themselves
   - Both private and organization-shared chats (only their own)

#### What Member CANNOT Access:

- ❌ Organization shared chats from other users/teams
- ❌ Private chats from other users
- ❌ Any chats from other teams (even if shared with organization)
- ❌ Chats from other organizations

**Note:** Only Team Leads can access organization-shared chats from other teams. Members are restricted to their own chats only.

#### Search Capabilities:
- Can search through:
  - Own chats (private + public) ONLY

#### Implementation:
```python
# Member search query
count_query = db.query(Embedding).filter(
    Embedding.embedding_vector.isnot(None),
    (
        # Own chats (both private and public) - must be in same organization
        ((Embedding.user_id == user_id) & (Embedding.organization_id == organization_id))
    )
)
```

#### Example Scenario:
```
Member: John (Team: BART, Organization: Yanthraa)

Can Access:
✅ John's own private chat about "Personal Notes"
✅ John's own organization-shared chat about "Project Ideas"

Cannot Access:
❌ Praveen's organization-shared chat (even if shared with organization)
❌ Sarah's organization-shared chat (even if shared with organization)
❌ Raja's organization-shared chat from Team "Holocron" (even if shared with organization)
❌ Praveen's private chat (not shared with organization)
❌ Sarah's private chat (not shared with organization)
❌ Private chats from other team members
❌ Chats from other organizations
```

---

## Chat Sharing Mechanism

### Sharing Levels

#### 1. Private (Default)
- **Default state** when a chat is created
- Only accessible to:
  - The chat owner (user who created it)
  - Team Lead (if owner is in their team)
  - Super Admin (always has access)

#### 2. Organization (Shared)
- User explicitly toggles sharing to "organization"
- Accessible to:
  - The chat owner
  - All members in the same organization
  - All team leads in the same organization
  - Super Admin

### How Sharing Works

```
Chat Creation Flow:
1. User creates a new chat
   └─> Default: sharing_level = 'private'
   
2. User can toggle sharing at any time
   └─> Toggle ON: sharing_level = 'organization'
   └─> Toggle OFF: sharing_level = 'private'
   
3. Sharing status is stored in Embedding table
   └─> Used for access control and search filtering
```

### PDF Sharing

**Important:** PDFs automatically follow the chat's sharing level.

```
If Chat is Private:
└─> PDFs in that chat are private (only owner, team lead, super admin)

If Chat is Shared with Organization:
└─> PDFs in that chat are accessible to all organization members
```

---

## Access Control Matrix

| Role | Own Private | Own Public | Team Private | Team Public | Org Shared (Other Teams) | Other Org Chats |
|------|-------------|------------|--------------|-------------|-------------------------|-----------------|
| **Super Admin** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Team Lead** | ✅ | ✅ | ✅ | ✅ | ✅ (if shared) | ❌ |
| **Member** | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |

---

## Search Query Logic

### Super Admin
```sql
SELECT * FROM embeddings
WHERE embedding_vector IS NOT NULL
-- No additional filters - accesses ALL
```

### Team Lead
```sql
SELECT * FROM embeddings
WHERE embedding_vector IS NOT NULL
AND (
    -- Own chats (private + public)
    user_id = 'team_lead_user_id'
    OR
    -- All team members' chats (private + public)
    team_id = 'team_id'
    OR
    -- Organization shared from other teams
    (organization_id = 'org_id' 
     AND sharing_level = 'organization' 
     AND team_id != 'team_id')
)
```

### Member
```sql
SELECT * FROM embeddings
WHERE embedding_vector IS NOT NULL
AND (
    -- Own chats (private + public) - must be in same organization
    (user_id = 'member_user_id' AND organization_id = 'org_id')
)
```

---

## Real-World Examples

### Example 1: Member Sharing a Chat

**Scenario:**
- Member "John" creates a chat about "Project Alpha"
- Chat is initially **private**
- John shares it with organization
- Chat becomes **organization-shared**

**Access After Sharing:**
- ✅ John (owner) - can access
- ✅ Praveen (Team Lead, same team) - can access
- ✅ Sarah (Team Member, same team) - can access
- ✅ Raja (Team Lead, different team) - can access
- ✅ All members in Organization "Yanthraa" - can access
- ✅ Super Admin - can access

### Example 2: Team Lead Searching

**Scenario:**
- Team Lead "Praveen" searches for "client feedback"
- System searches through:
  1. Praveen's own chats (private + public)
  2. All BART team members' chats (private + public)
  3. Organization-shared chats from other teams

**Results:**
- ✅ Finds: John's private chat about "Client Feedback" (team member)
- ✅ Finds: Sarah's organization-shared chat about "Client Meeting" (team member)
- ✅ Finds: Raja's organization-shared chat about "Client Discussion" (other team, shared)
- ❌ Won't find: Raja's private chat (not shared, different team)

### Example 3: Member Searching

**Scenario:**
- Member "John" searches for "project ideas"
- System searches through:
  1. John's own chats (private + public)
  2. Organization-shared chats from other users

**Results:**
- ✅ Finds: John's own private chat about "Project Ideas"
- ✅ Finds: Praveen's organization-shared chat about "New Project Ideas"
- ✅ Finds: Sarah's organization-shared chat about "Project Planning"
- ❌ Won't find: Praveen's private chat (not shared)
- ❌ Won't find: Sarah's private chat (not shared)

---

## Key Points

1. **Default is Private:** All new chats start as private
2. **User Controls Sharing:** Only the chat owner can toggle sharing
3. **Team Leads See All Team Chats:** Team leads have access to all team members' chats (both private and public)
4. **Members Only See Shared:** Members can only see other users' chats if they're shared with organization
5. **PDFs Follow Chat Sharing:** PDF access is automatically controlled by chat sharing level
6. **Super Admin Override:** Super admin can access everything regardless of sharing level

---

## Implementation Files

- **Search Logic:** `backend/embedding_service.py` - `get_relevant_contexts()`
- **PostgreSQL Function:** `backend/database.py` - `vector_search()` function
- **Access Control:** `backend/main.py` - Chat and PDF access endpoints
- **Sharing Toggle:** `backend/main.py` - `/api/chats/{chat_id}/share` endpoint

---

## Summary

| Role | What They Can Search |
|------|---------------------|
| **Super Admin** | Everything (all organizations, all teams, all users) |
| **Team Lead** | Own chats + All team chats (private+public) + Org shared |
| **Member** | Own chats (private+public) + Org shared chats only |

---

**Last Updated:** 2026-01-27  
**Version:** 1.0
