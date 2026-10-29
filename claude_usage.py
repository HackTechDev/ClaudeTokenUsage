#!/usr/bin/env python3
"""Affiche l'utilisation des limites Claude (session 5h + hebdomadaire)."""
import argparse, json, os, sys, time, urllib.error, urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta

CREDENTIALS = os.path.expanduser("~/.claude/.credentials.json")
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CACHE_FILE = os.path.expanduser("~/.cache/claude-usage/last.json")

# Seuils (en %) des niveaux « alerte » et « critique »
WARN, CRIT = 75, 90

# Libellés des types de limite connus du tableau `limits` de la réponse ;
# les types inconnus sont affichés d'après leur nom technique.
LABELS = {
    "session": "Session (5 h)",
    "weekly_all": "Hebdomadaire",
    "weekly_opus": "Hebdo Opus",
    "weekly_sonnet": "Hebdo Sonnet",
}
# Libellés courts pour la ligne d'état
SHORT_LABELS = {"session": "5h", "weekly_all": "7j", "weekly_opus": "7j Opus", "weekly_sonnet": "7j Sonnet"}
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

    def remaining(self, now=None):
        """Temps restant avant la réinitialisation (jamais négatif)."""
        now = now or datetime.now().astimezone()
        return max(self.resets_at - now, timedelta(0))

    def to_dict(self):
        return {"kind": self.kind, "label": self.label, "percent": self.percent,
                "resets_at": self.resets_at.isoformat(),
                "resets_in_seconds": int(self.remaining().total_seconds())}


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


def read_cache(max_age):
    """Renvoie la dernière réponse enregistrée si elle a moins de max_age secondes."""
    try:
        if time.time() - os.path.getmtime(CACHE_FILE) < max_age:
            with open(CACHE_FILE) as f:
                return json.load(f)
    except (OSError, json.JSONDecodeError):
        pass
    return None


def write_cache(data):
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        tmp = CACHE_FILE + ".tmp"
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            json.dump(data, f)
        os.replace(tmp, CACHE_FILE)
    except OSError:
        pass  # le cache n'est qu'une optimisation


def fetch_usage(max_age=0):
    """Interroge l'API, ou réutilise la réponse en cache si elle a moins de max_age secondes."""
    data = read_cache(max_age) if max_age else None
    if data is None:
        data = fetch_raw()
        write_cache(data)
    return parse_usage(data)


def format_remaining(delta):
    """Durée lisible : « 2 j 3 h », « 4 h 05 », « 12 min », « < 1 min »."""
    minutes = int(delta.total_seconds() // 60)
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days} j {hours} h"
    if hours:
        return f"{hours} h {minutes:02d}"
    if minutes:
        return f"{minutes} min"
    return "< 1 min"


def severity(percent):
    """Niveau d'une limite : "ok", "warn" ou "crit"."""
    if percent >= CRIT:
        return "crit"
    if percent >= WARN:
        return "warn"
    return "ok"


EXIT_CODES = {"ok": 0, "warn": 1, "crit": 2}
ANSI = {"ok": "\033[32m", "warn": "\033[33m", "crit": "\033[31m"}
ANSI_RESET, ANSI_DIM = "\033[0m", "\033[2m"
BAR_WIDTH = 20


def bar(percent, color):
    filled = round(min(max(percent, 0), 100) / 100 * BAR_WIDTH)
    if not color:
        return "[" + "#" * filled + "-" * (BAR_WIDTH - filled) + "]"
    return ANSI[severity(percent)] + "█" * filled + ANSI_DIM + "░" * (BAR_WIDTH - filled) + ANSI_RESET


def print_table(usage, color):
    for l in usage.limits:
        print(f"{l.label:<16} {bar(l.percent, color)} {l.percent:>5.1f} %"
              f"   réinit. : {l.resets_at:%d/%m/%Y %H:%M} (dans {format_remaining(l.remaining())})")


def statusline(usage, color):
    """Ligne compacte pour la status line de Claude Code, ex. « 5h 28% · 7j 85% »."""
    parts = []
    for l in usage.limits:
        text = f"{SHORT_LABELS.get(l.kind, l.label)} {l.percent:.0f}%"
        parts.append(ANSI[severity(l.percent)] + text + ANSI_RESET if color else text)
    return " · ".join(parts)


def watch(interval, color):
    """Rafraîchit l'affichage dans le terminal jusqu'à Ctrl+C."""
    try:
        while True:
            try:
                usage, error = fetch_usage(), None
            except UsageError as e:
                error = e
            if sys.stdout.isatty():
                print("\033[H\033[2J", end="")
            if error:
                print(f"Erreur : {error}")
            else:
                print_table(usage, color)
            print(f"\nMis à jour à {datetime.now():%H:%M:%S} · "
                  f"rafraîchi toutes les {interval} s · Ctrl+C pour quitter", flush=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Affiche l'utilisation des limites Claude.")
    parser.add_argument("--json", action="store_true", help="sortie JSON")
    parser.add_argument("--no-color", action="store_true", help="désactive les couleurs")
    parser.add_argument("--watch", nargs="?", const=60, type=int, metavar="SECONDES",
                        help="rafraîchit l'affichage en continu (60 s par défaut, 10 s minimum)")
    parser.add_argument("--statusline", action="store_true",
                        help="une ligne compacte pour la status line de Claude Code (cache de 60 s)")
    parser.add_argument("--check", action="store_true",
                        help="code de retour selon la limite la plus utilisée : "
                             f"0 normal, 1 alerte (≥ {WARN} %%), 2 critique (≥ {CRIT} %%), 3 erreur")
    args = parser.parse_args(argv)
    color = sys.stdout.isatty() and not args.no_color and "NO_COLOR" not in os.environ

    if args.statusline:
        # Claude Code interprète les couleurs ANSI même si la sortie n'est pas un terminal
        try:
            print(statusline(fetch_usage(max_age=60), not args.no_color and "NO_COLOR" not in os.environ))
        except UsageError:
            print("usage indisponible")
        return 0

    if args.watch:
        if args.json:
            parser.error("--watch et --json sont incompatibles")
        return watch(max(args.watch, 10), color)

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
        print_table(usage, color)
    if args.check:
        return max((EXIT_CODES[severity(l.percent)] for l in usage.limits), default=0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
