#!/usr/bin/env python3
"""Affiche l'utilisation des limites Claude (session 5h + hebdomadaire)."""
import argparse, json, os, sys, urllib.error, urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta

CREDENTIALS = os.path.expanduser("~/.claude/.credentials.json")
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"

# Libellés des types de limite connus du tableau `limits` de la réponse ;
# les types inconnus sont affichés d'après leur nom technique.
LABELS = {
    "session": "Session (5 h)",
    "weekly_all": "Hebdomadaire",
    "weekly_opus": "Hebdo Opus",
    "weekly_sonnet": "Hebdo Sonnet",
}
# Durée de la fenêtre de chaque groupe de limites
WINDOWS = {"session": timedelta(hours=5), "weekly": timedelta(days=7)}

# Repli pour les réponses sans tableau `limits` : (clé, type, groupe)
LEGACY_BUCKETS = [
    ("five_hour", "session", "session"),
    ("seven_day", "weekly_all", "weekly"),
    ("seven_day_opus", "weekly_opus", "weekly"),
    ("seven_day_sonnet", "weekly_sonnet", "weekly"),
]


@dataclass
class Limit:
    kind: str
    label: str
    percent: float
    resets_at: datetime  # heure locale, arrondie à la minute
    window: timedelta | None = None

    def to_dict(self):
        return {"kind": self.kind, "label": self.label, "percent": self.percent,
                "resets_at": self.resets_at.isoformat()}


@dataclass
class Usage:
    limits: list[Limit]
    raw: dict = field(default_factory=dict, repr=False)

    def to_dict(self):
        return {"limits": [l.to_dict() for l in self.limits]}


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


def parse_reset(value):
    reset = datetime.fromisoformat(value).astimezone()
    # L'API renvoie des heures du type 22:49:59.63 : arrondi à la minute
    return (reset + timedelta(seconds=30)).replace(second=0, microsecond=0)


def make_limit(kind, group, percent, resets_at):
    label = LABELS.get(kind, kind.replace("_", " ").capitalize())
    return Limit(kind, label, float(percent), parse_reset(resets_at), WINDOWS.get(group))


def parse_usage(data):
    """Convertit la réponse brute de l'API en objet Usage."""
    try:
        if data.get("limits"):
            limits = [make_limit(l["kind"], l.get("group"), l["percent"], l["resets_at"])
                      for l in data["limits"]]
        else:
            limits = [make_limit(kind, group, data[key]["utilization"], data[key]["resets_at"])
                      for key, kind, group in LEGACY_BUCKETS if data.get(key)]
    except (AttributeError, KeyError, TypeError, ValueError):
        raise UsageError("Format de réponse inattendu : l'API a peut-être changé.")
    return Usage(limits, data)


def fetch_usage():
    return parse_usage(fetch_raw())


def print_table(usage):
    for l in usage.limits:
        print(f"{l.label:<22} {l.percent:>5.1f} %   réinit. : {l.resets_at:%d/%m/%Y %H:%M}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Affiche l'utilisation des limites Claude.")
    parser.add_argument("--json", action="store_true", help="sortie JSON")
    args = parser.parse_args(argv)

    try:
        usage = fetch_usage()
    except UsageError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, ensure_ascii=False))
        else:
            print(f"Erreur : {e}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(usage.to_dict(), ensure_ascii=False, indent=2))
    else:
        print_table(usage)
    return 0


if __name__ == "__main__":
    sys.exit(main())
