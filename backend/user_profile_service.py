import logging
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from database import UserProfile
from openai import OpenAI
import json
from config import SUMMARY_MODEL, OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)
logger = logging.getLogger(__name__)

def update_user_profile(db: Session, user_id: str, chat_summary: str) -> UserProfile:
    """
    Update user profile incrementally with new information.
    Uses extraction instead of merging all summaries.
    """
    user_profile = db.query(UserProfile).filter(
        UserProfile.user_id == user_id
    ).first()
    
    if not user_profile:
        # Initialize new profile
        user_profile = UserProfile(
            user_id=user_id,
            preferences={},
            important_facts=[],
            topics_of_interest=[]
        )
        db.add(user_profile)
        db.commit()
        db.refresh(user_profile)
    
    # Extract new facts/preferences from chat summary
    # CRITICAL: Preserve ALL specific details from ANY document type (resume, proposal, technical doc, etc.)
    extraction_prompt = f"""
    Extract and update user information from this conversation summary.
    The conversation may contain ANY type of document or information (resume, proposal, technical document, business plan, research paper, contract, etc.).
    
    PRESERVE ALL SPECIFIC DETAILS regardless of document type:
    - Exact names (people, organizations, places, products, entities) - use EXACT names
    - Precise numbers (scores, percentages, amounts, measurements, dates, years) - use EXACT values
    - Specific qualifications, credentials, certifications, degrees - COMPLETE details
    - Technical specifications, requirements, conditions, terms - EXACT wording where important
    - Projects, work items, tasks, deliverables, milestones - SPECIFIC information
    - Key facts, claims, statements, findings - PRESERVE precision
    
    {chat_summary}
    
    Return a JSON object with:
    {{
        "new_facts": [
            // Include ALL specific factual information from the conversation:
            // - Use EXACT values and names (do NOT generalize)
            // - Examples:
            //   * "CGPA 8.5" not "high GPAs"
            //   * "Project XYZ with budget $50,000" not "large project"
            //   * "Certificate from ABC Institute in 2023" not "recent certificate"
            // - Preserve all specific details that might be queried later
        ],
        "new_preferences": {{"key": "value"}},  // User preferences (if mentioned)
        "new_topics": ["topic1", "topic2"]  // Topics of interest discussed
    }}
    
    IMPORTANT: 
    - Use EXACT values, names, and specific details. Do NOT generalize.
    - Work with ANY document type - extract relevant facts appropriately.
    - Only include NEW information that should be added to the profile.
    - If there's no new information, return empty arrays/objects.
    """
    
    try:
        response = client.chat.completions.create(
            model=SUMMARY_MODEL,
            messages=[
                {"role": "system", "content": "You extract structured information from text. Return only valid JSON."},
                {"role": "user", "content": extraction_prompt}
            ],
            temperature=0.3,
            response_format={"type": "json_object"}  # Ensure valid JSON
        )
        
        extracted = json.loads(response.choices[0].message.content)
        
        # Update profile incrementally
        if extracted.get("new_facts"):
            existing_facts = user_profile.important_facts or []
            new_facts = [f for f in extracted["new_facts"] if f not in existing_facts]
            user_profile.important_facts = existing_facts + new_facts
        
        if extracted.get("new_preferences"):
            existing_prefs = user_profile.preferences or {}
            existing_prefs.update(extracted["new_preferences"])
            user_profile.preferences = existing_prefs
        
        if extracted.get("new_topics"):
            existing_topics = user_profile.topics_of_interest or []
            new_topics = [t for t in extracted["new_topics"] if t not in existing_topics]
            user_profile.topics_of_interest = existing_topics + new_topics
        
        db.commit()
        db.refresh(user_profile)
        
        logger.debug(f"👤 User profile updated | New facts: {len(extracted.get('new_facts', []))} | New preferences: {len(extracted.get('new_preferences', {}))} | New topics: {len(extracted.get('new_topics', []))}")
        
        return user_profile
        
    except Exception as e:
        logger.warning(f"Error updating user profile for user {user_id}: {e}")
        return user_profile

def get_user_profile_context(db: Session, user_id: str) -> Optional[Dict[str, Any]]:
    """Get user profile formatted for context"""
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    
    if not profile:
        return None
    
    return {
        "preferences": profile.preferences or {},
        "important_facts": profile.important_facts or [],
        "topics_of_interest": profile.topics_of_interest or []
    }

def format_user_profile(profile: Dict[str, Any]) -> str:
    """Format user profile for context string"""
    if not profile:
        return ""
    
    parts = []
    
    if profile.get("important_facts"):
        facts = profile["important_facts"][:10]  # Limit to 10 facts
        # Handle cases where facts might be strings or dicts
        facts_str = []
        for fact in facts:
            if isinstance(fact, dict):
                # If fact is a dict, convert to string representation
                if isinstance(fact, dict) and len(fact) == 1:
                    # If single key-value pair, format nicely
                    key, value = next(iter(fact.items()))
                    facts_str.append(f"{key}: {value}")
                else:
                    # Otherwise, use JSON string
                    import json
                    facts_str.append(json.dumps(fact))
            elif isinstance(fact, str):
                facts_str.append(fact)
            else:
                # Convert other types to string
                facts_str.append(str(fact))
        
        if facts_str:
            parts.append(f"Important facts: {', '.join(facts_str)}")
    
    if profile.get("preferences"):
        prefs = profile["preferences"]
        pref_items = [f"{k}: {v}" for k, v in list(prefs.items())[:10]]
        if pref_items:
            parts.append(f"Preferences: {', '.join(pref_items)}")
    
    if profile.get("topics_of_interest"):
        topics = profile["topics_of_interest"][:10]  # Limit to 10 topics
        # Handle cases where topics might be strings or other types
        topics_str = [str(t) for t in topics if t]
        if topics_str:
            parts.append(f"Topics of interest: {', '.join(topics_str)}")
    
    return "\n".join(parts) if parts else ""

