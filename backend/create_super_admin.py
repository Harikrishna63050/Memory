"""
Script to create the initial super admin user and teams with team leads.
Production-grade: Creates organization, super admin, and teams.

Usage:
    python create_super_admin.py
"""
import sys
import logging
from database import init_db, get_db, Organization, User, Team, verify_db_connection

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def create_super_admin():
    """Create super admin user with organization and teams with team leads"""
    
    # Super admin credentials
    SUPER_ADMIN_USER_ID = "Abcd"
    ORGANIZATION_ID = "Yanthraa"  # Using Yanthraa as requested
    ORGANIZATION_NAME = "Yanthraa"
    
    # Teams with team leads
    TEAMS = [
        {"team_id": "BART", "team_name": "BART", "team_lead_id": "Praveen"},
        {"team_id": "Holocron", "team_name": "Holocron", "team_lead_id": "Raja"},
        {"team_id": "FAT", "team_name": "FAT", "team_lead_id": "Vivek"},
        {"team_id": "Inpharmd", "team_name": "Inpharmd", "team_lead_id": "Chinna"},
    ]
    
    logger.info("=" * 80)
    logger.info("CREATING SUPER ADMIN AND TEAMS")
    logger.info("=" * 80)
    logger.info(f"Super Admin User ID: {SUPER_ADMIN_USER_ID}")
    logger.info(f"Organization: {ORGANIZATION_ID}")
    logger.info(f"Teams: {len(TEAMS)} teams with team leads")
    logger.info("=" * 80)
    
    # Initialize database and verify connection
    try:
        verify_db_connection()
        init_db()
        logger.info("✅ Database initialized and verified")
    except Exception as e:
        logger.error(f"❌ Error initializing database: {e}")
        return False
    
    # Get database session
    from database import SessionLocal
    db = SessionLocal()
    
    try:
        # Create organization first
        org = db.query(Organization).filter(Organization.organization_id == ORGANIZATION_ID).first()
        if not org:
            logger.info(f"Creating organization: {ORGANIZATION_ID}")
            org = Organization(
                organization_id=ORGANIZATION_ID,
                organization_name=ORGANIZATION_NAME
            )
            db.add(org)
            db.commit()
            logger.info(f"✅ Organization '{ORGANIZATION_ID}' created")
        else:
            logger.info(f"✅ Organization '{ORGANIZATION_ID}' already exists")
        
        # Check if super admin already exists
        existing_super_admin = db.query(User).filter(User.role == 'super_admin').first()
        
        if existing_super_admin:
            # Check if it's the same user
            if existing_super_admin.user_id == SUPER_ADMIN_USER_ID:
                logger.info(f"✅ Super admin '{SUPER_ADMIN_USER_ID}' already exists")
                # Update organization if needed
                if existing_super_admin.organization_id != ORGANIZATION_ID:
                    existing_super_admin.organization_id = ORGANIZATION_ID
                    db.commit()
            else:
                logger.warning(f"⚠️  Different super admin exists: {existing_super_admin.user_id}")
                logger.warning(f"   Cannot create '{SUPER_ADMIN_USER_ID}' as super admin (only one allowed)")
        else:
            # Check if user exists with different role
            existing_user = db.query(User).filter(User.user_id == SUPER_ADMIN_USER_ID).first()
            if existing_user:
                if existing_user.role != 'super_admin':
                    logger.warning(f"⚠️  User '{SUPER_ADMIN_USER_ID}' exists with role '{existing_user.role}'")
                    logger.warning(f"   Cannot change to super_admin (only one super admin allowed)")
                else:
                    # User is already super admin, just update organization
                    existing_user.organization_id = ORGANIZATION_ID
                    db.commit()
                    logger.info(f"✅ Super admin '{SUPER_ADMIN_USER_ID}' already exists")
            else:
                # Create super admin user
                super_admin = User(
                    user_id=SUPER_ADMIN_USER_ID,
                    organization_id=ORGANIZATION_ID,
                    team_id=None,  # Super admin doesn't need a team
                    role='super_admin'
                )
                
                db.add(super_admin)
                db.commit()
                db.refresh(super_admin)
                logger.info(f"✅ Super admin '{SUPER_ADMIN_USER_ID}' created")
        
        # Create teams and team leads
        logger.info("")
        logger.info("Creating teams and team leads...")
        logger.info("-" * 80)
        
        for team_info in TEAMS:
            team_id = team_info["team_id"]
            team_name = team_info["team_name"]
            team_lead_id = team_info["team_lead_id"]
            
            # Create or update team
            team = db.query(Team).filter(Team.team_id == team_id).first()
            if not team:
                team = Team(
                    team_id=team_id,
                    organization_id=ORGANIZATION_ID,
                    team_name=team_name,
                    team_lead_id=team_lead_id
                )
                db.add(team)
                db.commit()
                logger.info(f"✅ Team '{team_name}' ({team_id}) created")
            else:
                # Update team lead if changed
                if team.team_lead_id != team_lead_id:
                    team.team_lead_id = team_lead_id
                    db.commit()
                logger.info(f"✅ Team '{team_name}' ({team_id}) already exists")
            
            # Create team lead user if specified
            if team_lead_id:
                team_lead = db.query(User).filter(User.user_id == team_lead_id).first()
                if not team_lead:
                    team_lead = User(
                        user_id=team_lead_id,
                        organization_id=ORGANIZATION_ID,
                        team_id=team_id,
                        role='team_lead'
                    )
                    db.add(team_lead)
                    db.commit()
                    logger.info(f"   ✅ Team Lead '{team_lead_id}' created for team '{team_name}'")
                else:
                    # Update existing user to be team lead
                    if team_lead.role != 'team_lead' or team_lead.team_id != team_id:
                        team_lead.role = 'team_lead'
                        team_lead.organization_id = ORGANIZATION_ID
                        team_lead.team_id = team_id
                        db.commit()
                        logger.info(f"   ✅ User '{team_lead_id}' updated to Team Lead for '{team_name}'")
                    else:
                        logger.info(f"   ✅ Team Lead '{team_lead_id}' already exists for team '{team_name}'")
        
        db.commit()
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("✅ SETUP COMPLETED SUCCESSFULLY")
        logger.info("=" * 80)
        logger.info(f"Super Admin User ID: {SUPER_ADMIN_USER_ID}")
        logger.info(f"Organization: {ORGANIZATION_ID}")
        logger.info("")
        logger.info("📋 Teams Status:")
        for team_info in TEAMS:
            if team_info["team_lead_id"]:
                logger.info(f"   • {team_info['team_name']} ({team_info['team_id']}) - Lead: {team_info['team_lead_id']}")
            else:
                logger.info(f"   • {team_info['team_name']} ({team_info['team_id']}) - No Lead")
        logger.info("=" * 80)
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Error creating super admin: {e}", exc_info=True)
        db.rollback()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    success = create_super_admin()
    sys.exit(0 if success else 1)
