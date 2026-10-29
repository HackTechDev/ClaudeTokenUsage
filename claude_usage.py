#!/usr/bin/env python3
"""Affiche l'utilisation des limites Claude (session 5h + hebdomadaire)."""
import json, os, urllib.request
from datetime import datetime

creds = json.load(open(os.path.expanduser("~/.claude/.credentials.json")))
token = creds["claudeAiOauth"]["accessToken"]

req = urllib.request.Request(
    "https://api.anthropic.com/api/oauth/usage",
    headers={"Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20"},
)
data = json.load(urllib.request.urlopen(req))

def show(label, bucket):
    if not bucket:
        return
    reset = datetime.fromisoformat(bucket["resets_at"]).astimezone()
    print(f"{label:<22} {bucket['utilization']:>5.1f} %   réinit. : {reset:%d/%m/%Y %H:%M}")

show("Session (5 h)", data.get("five_hour"))
show("Hebdomadaire", data.get("seven_day"))
show("Hebdo Opus", data.get("seven_day_opus"))
show("Hebdo Sonnet", data.get("seven_day_sonnet"))
