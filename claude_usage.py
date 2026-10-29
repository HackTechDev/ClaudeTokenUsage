#!/usr/bin/env python3
"""Affiche l'utilisation des limites Claude (session 5h + hebdomadaire)."""
import json, os, sys, urllib.error, urllib.request
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


class UsageError(Exception):
    """Erreur présentable telle quelle à l'utilisateur."""


def read_token():
    try:
        with open(CREDENTIALS) as f:
            return json.load(f)["claudeAiOauth"]["accessToken"]
    except FileNotFoundError:
        raise UsageError(f"Identifiants introuvables ({CREDENTIALS}). "
                         "Connectez-vous à Claude Code avec la commande `claude`.")
    except (json.JSONDecodeError, KeyError, TypeError):
        raise UsageError(f"Format inattendu du fichier {CREDENTIALS}. "
                         "Reconnectez-vous avec `claude` puis `/login`.")


def fetch_raw():
    """Renvoie la réponse brute (dict) de l'endpoint d'usage."""
    req = urllib.request.Request(
        USAGE_URL,
        headers={"Authorization": f"Bearer {read_token()}", "anthropic-beta": "oauth-2025-04-20"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise UsageError("Jeton expiré ou invalide. Lancez `claude` une fois pour le renouveler.")
        if e.code == 429:
            raise UsageError("Trop de requêtes (HTTP 429). Réessayez dans quelques minutes.")
        raise UsageError(f"Erreur du serveur (HTTP {e.code}).")
    except urllib.error.URLError as e:
        raise UsageError(f"Connexion impossible à api.anthropic.com ({e.reason}). Vérifiez le réseau.")
    except TimeoutError:
        raise UsageError("Le serveur n'a pas répondu à temps. Vérifiez le réseau.")
    except json.JSONDecodeError:
        raise UsageError("Réponse du serveur illisible (JSON invalide).")


def fetch_usage():
    """Renvoie la liste des limites actives : (libellé, pourcentage, date de réinit. locale)."""
    data = fetch_raw()
    usage = []
    try:
        for key, label in BUCKETS:
            bucket = data.get(key)
            if bucket:
                reset = datetime.fromisoformat(bucket["resets_at"]).astimezone()
                # L'API renvoie des heures du type 22:49:59.63 : arrondi à la minute
                reset = (reset + timedelta(seconds=30)).replace(second=0, microsecond=0)
                usage.append((label, bucket["utilization"], reset))
    except (AttributeError, KeyError, TypeError, ValueError):
        raise UsageError("Format de réponse inattendu : l'API a peut-être changé.")
    return usage


if __name__ == "__main__":
    try:
        usage = fetch_usage()
    except UsageError as e:
        print(f"Erreur : {e}", file=sys.stderr)
        sys.exit(3)
    for label, percent, reset in usage:
        print(f"{label:<22} {percent:>5.1f} %   réinit. : {reset:%d/%m/%Y %H:%M}")
