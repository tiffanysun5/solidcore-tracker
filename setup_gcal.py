#!/usr/bin/env python3
"""
One-time setup: authorize Google Calendar access and print the refresh token.

Usage:
  1. Download OAuth2 credentials from Google Cloud Console as client_secret.json
     (OAuth 2.0 Client ID, type: Desktop app)
  2. Put client_secret.json in this directory
  3. Run:  python setup_gcal.py
  4. A browser opens — sign in as tiffanysun27@gmail.com and allow access
  5. Copy the three values printed at the end into GitHub Secrets:
       GOOGLE_CLIENT_ID
       GOOGLE_CLIENT_SECRET
       GOOGLE_REFRESH_TOKEN
"""

import json
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

def main():
    secret_file = Path("client_secret.json")
    if not secret_file.exists():
        print("ERROR: client_secret.json not found.")
        print("Download it from https://console.cloud.google.com/")
        print("  APIs & Services → Credentials → OAuth 2.0 Client ID (Desktop app) → Download JSON")
        return

    flow = InstalledAppFlow.from_client_secrets_file(str(secret_file), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    client_id     = creds.client_id
    client_secret = creds.client_secret
    refresh_token = creds.refresh_token

    print("\n" + "="*60)
    print("Add these three values as GitHub repository secrets:")
    print("="*60)
    print(f"\nGOOGLE_CLIENT_ID     = {client_id}")
    print(f"GOOGLE_CLIENT_SECRET = {client_secret}")
    print(f"GOOGLE_REFRESH_TOKEN = {refresh_token}")
    print("\nAlso add them to your local .env file.")


if __name__ == "__main__":
    main()
