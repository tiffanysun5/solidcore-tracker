"""Quick test: send a dummy digest email to verify SMTP works."""
import os, sys
from pathlib import Path

# Load .env manually (no python-dotenv needed)
for line in Path(".env").read_text().splitlines():
    if line.strip() and not line.startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

from src.filters import MatchedClass
from src.wellhub_api import ClassSlot
from src.email_digest import send_digest
from datetime import datetime

# Fake match so we can test the email template
fake_slot = ClassSlot(
    wellhub_class_id="test-123",
    studio="Chelsea",
    instructor="Maya P.",
    dt=datetime(2026, 4, 5, 12, 0),
)
fake_match = MatchedClass(
    slot=fake_slot,
    muscles=["Leg Wrap"],
    all_muscles=["Leg Wrap", "Triceps"],
    preferred_time=True,
)

send_digest([fake_match], os.environ["SMTP_USER"])
print("Done — check tiffanysun27@gmail.com")
