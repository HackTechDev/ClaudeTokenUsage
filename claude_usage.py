#!/usr/bin/env python3
"""Affiche l'utilisation des limites Claude (session 5h + hebdomadaire)."""
import json, os, urllib.request
from datetime import datetime, timedelta

CREDENTIALS = os.path.expanduser("~/.claude/.credentials.json")
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"

# (clé dans la réponse, libellé affiché)
BUCKETS = [
    ("five_hour", "Session (5 h)"),
    ("seven_day", "Hebdomadaire"),
    ("seven_day_opus", "Hebdo Opus"),
    ("seven_day_sonnet", "Hebdo Sonnet"),
]


def fetch_usage():
    """Renvoie la liste des limites actives : (libellé, pourcentage, date de réinit. locale)."""
    # Relu à chaque appel : Claude Code renouvelle le jeton régulièrement
    with open(CREDENTIALS) as f:
        token = json.load(f)["claudeAiOauth"]["accessToken"]

    req = urllib.request.Request(
        USAGE_URL,
        headers={"Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.load(resp)

    usage = []
    for key, label in BUCKETS:
        bucket = data.get(key)
        if bucket:
            reset = datetime.fromisoformat(bucket["resets_at"]).astimezone()
            # L'API renvoie des heures du type 22:49:59.63 : arrondi à la minute
            reset = (reset + timedelta(seconds=30)).replace(second=0, microsecond=0)
            usage.append((label, bucket["utilization"], reset))
    return usage


if __name__ == "__main__":
    for label, percent, reset in fetch_usage():
        print(f"{label:<22} {percent:>5.1f} %   réinit. : {reset:%d/%m/%Y %H:%M}")
