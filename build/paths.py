from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = ROOT / "build"
AUTOMATIONS_DIR = ROOT / "automations"
MAIN_WORKFLOW_JSON = AUTOMATIONS_DIR / "mini_automation_for_reels.json"
MAIN_WORKFLOW_NAME = "Mini Automation for Reels"
LINKEDIN_WORKFLOW_JSON = AUTOMATIONS_DIR / "linkedin_post_automation.json"
LINKEDIN_WORKFLOW_NAME = "LinkedIn Post Automation"
ARCHIVE_DIR = AUTOMATIONS_DIR / "archive"
