#!/usr/bin/env python3
"""Affiche l'utilisation des limites Claude (session 5h + hebdomadaire)."""
import argparse, contextlib, json, os, sqlite3, sys, time, tomllib, urllib.error, urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta

CREDENTIALS = os.path.expanduser("~/.claude/.credentials.json")
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CACHE_FILE = os.path.expanduser("~/.cache/claude-usage/last.json")
CONFIG_FILE = os.path.expanduser("~/.config/claude-usage/config.toml")
HISTORY_DB = os.path.expanduser("~/.local/share/claude-usage/history.db")
HISTORY_DAYS = 30  # durée de conservation de l'historique

DEFAULT_CONFIG = {
    "refresh_interval": 60,  # secondes, 10 minimum
    "warn_threshold": 75,    # % à partir duquel une limite passe en alerte
    "crit_threshold": 90,    # % à partir duquel elle devient critique
    "theme": "auto",         # interface Qt : "auto" (suit le système), "light" ou "dark"
    "notifications": True,   # interface Qt : seuils franchis et réinitialisations
}


def load_config(path=CONFIG_FILE):
    """Configuration par défaut, complétée par le fichier TOML s'il existe."""
    config = dict(DEFAULT_CONFIG)
    try:
        with open(path, "rb") as f:
            user = tomllib.load(f)
    except FileNotFoundError:
        return config
    except (OSError, tomllib.TOMLDecodeError) as e:
        print(f"Configuration ignorée ({path}) : {e}", file=sys.stderr)
        return config
    for key, value in user.items():
        if key not in DEFAULT_CONFIG:
            print(f"Option inconnue ignorée dans {path} : {key}", file=sys.stderr)
        elif type(value) is not type(DEFAULT_CONFIG[key]):
            print(f"Valeur invalide ignorée dans {path} : {key} = {value!r}", file=sys.stderr)
        else:
            config[key] = value
    config["refresh_interval"] = max(config["refresh_interval"], 10)
    return config


CONFIG = load_config()

# Seuils (en %) des niveaux « alerte » et « critique »
WARN, CRIT = CONFIG["warn_threshold"], CONFIG["crit_threshold"]

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

    def elapsed(self, now=None):
        """Temps écoulé depuis le début de la fenêtre, ou None si sa durée est inconnue."""
        if not self.window:
            return None
        return min(max(self.window - self.remaining(now), timedelta(0)), self.window)

    def pace(self, now=None):
        """Rapport entre la part consommée et la part de fenêtre écoulée.

        1.0 = rythme qui atteint 100 % pile à la réinitialisation ; > 1 = trop rapide.
        None si la fenêtre est inconnue ou commence à peine (moins de 15 min).
        """
        elapsed = self.elapsed(now)
        if elapsed is None or elapsed < timedelta(minutes=15):
            return None
        return (self.percent / 100) / (elapsed / self.window)

    def exhaustion(self, now=None):
        """Heure estimée à laquelle la limite sera atteinte au rythme actuel,
        ou None si elle ne le sera pas avant la réinitialisation."""
        now = now or datetime.now().astimezone()
        elapsed = self.elapsed(now)
        if self.pace(now) is None or self.percent <= 0:
            return None
        if self.percent >= 100:
            return now
        at = now + elapsed * ((100 - self.percent) / self.percent)
        return at if at < self.resets_at else None

    def to_dict(self):
        pace, exhaustion = self.pace(), self.exhaustion()
        return {"kind": self.kind, "label": self.label, "percent": self.percent,
                "resets_at": self.resets_at.isoformat(),
                "resets_in_seconds": int(self.remaining().total_seconds()),
                "pace": round(pace, 2) if pace is not None else None,
                "projected_exhaustion": exhaustion.replace(microsecond=0).isoformat() if exhaustion else None}


DISABLED_REASONS = {"out_of_credits": "crédits épuisés"}


@dataclass
class ExtraUsage:
    """Crédits d'usage supplémentaire, utilisés une fois les limites du forfait atteintes."""
    enabled: bool
    used: float
    limit: float
    currency: str
    disabled_reason: str | None = None

    @property
    def percent(self):
        return self.used / self.limit * 100 if self.limit else 0.0

    def describe(self):
        text = (f"{self.used:.2f} / {self.limit:.2f} {self.currency} ({self.percent:.0f} %)"
                .replace(".", ","))
        if not self.enabled:
            reason = DISABLED_REASONS.get(self.disabled_reason, self.disabled_reason)
            text += f" · désactivés{' : ' + reason if reason else ''}"
        return text

    def to_dict(self):
        return {"enabled": self.enabled, "used": self.used, "limit": self.limit,
                "currency": self.currency, "disabled_reason": self.disabled_reason}


@dataclass
class Usage:
    limits: list[Limit]
    extra: ExtraUsage | None = None
    breakdown: list[tuple[str, float]] = field(default_factory=list)  # (produit, % de la semaine)
    raw: dict = field(default_factory=dict, repr=False)

    def describe_breakdown(self):
        return " · ".join(f"{name} {percent:.0f} %" for name, percent in self.breakdown if percent)

    def to_dict(self):
        return {"limits": [l.to_dict() for l in self.limits],
                "extra_usage": self.extra.to_dict() if self.extra else None,
                "breakdown": [{"name": n, "percent": p} for n, p in self.breakdown]}


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
    return Usage(limits, parse_extra(data.get("extra_usage")),
                 parse_breakdown(data.get("seven_day_breakdown")), data)


# Les deux sections suivantes sont secondaires : un format inattendu les
# masque au lieu de faire échouer tout l'affichage.

def parse_extra(extra):
    try:
        scale = 10 ** extra.get("decimal_places", 2)
        return ExtraUsage(bool(extra["is_enabled"]), extra["used_credits"] / scale,
                          extra["monthly_limit"] / scale, extra.get("currency", ""),
                          extra.get("disabled_reason"))
    except (AttributeError, KeyError, TypeError, ZeroDivisionError):
        return None


def parse_breakdown(breakdown):
    try:
        return [(row["display_name"], float(row["percent"])) for row in breakdown["rows"]]
    except (KeyError, TypeError, ValueError):
        return []


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
    """Interroge l'API, ou réutilise la réponse en cache si elle a moins de max_age secondes.

    Chaque réponse obtenue de l'API est ajoutée à l'historique.
    """
    data = read_cache(max_age) if max_age else None
    if data is not None:
        return parse_usage(data)
    data = fetch_raw()
    write_cache(data)
    usage = parse_usage(data)
    record_history(usage)
    return usage


def open_history(path=HISTORY_DB):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    db = sqlite3.connect(path, timeout=5)
    db.execute("CREATE TABLE IF NOT EXISTS measures "
               "(ts REAL NOT NULL, kind TEXT NOT NULL, percent REAL NOT NULL)")
    db.execute("CREATE INDEX IF NOT EXISTS measures_kind_ts ON measures (kind, ts)")
    return db


def record_history(usage, path=HISTORY_DB, now=None):
    """Enregistre le pourcentage de chaque limite et purge les mesures trop anciennes."""
    now = now or time.time()
    try:
        with contextlib.closing(open_history(path)) as db, db:
            db.executemany("INSERT INTO measures VALUES (?, ?, ?)",
                           [(now, l.kind, l.percent) for l in usage.limits])
            db.execute("DELETE FROM measures WHERE ts < ?", (now - HISTORY_DAYS * 86400,))
    except (OSError, sqlite3.Error):
        pass  # l'historique est facultatif


def load_history(kind, since, path=HISTORY_DB):
    """Mesures [(datetime locale, pourcentage)] d'un type de limite depuis `since`."""
    try:
        with contextlib.closing(open_history(path)) as db:
            rows = db.execute("SELECT ts, percent FROM measures WHERE kind = ? AND ts >= ? "
                              "ORDER BY ts", (kind, since.timestamp())).fetchall()
    except (OSError, sqlite3.Error):
        return []
    return [(datetime.fromtimestamp(ts).astimezone(), percent) for ts, percent in rows]


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


def format_pace(limit):
    """Ex. « rythme ×1.8, limite atteinte vers 21:40 », ou "" si non calculable."""
    pace = limit.pace()
    if pace is None:
        return ""
    text = f"rythme ×{pace:.1f}"
    exhaustion = limit.exhaustion()
    if exhaustion:
        fmt = "%H:%M" if exhaustion.date() == datetime.now().date() else "%d/%m %H:%M"
        text += f", limite atteinte vers {exhaustion:{fmt}}"
    return text


def severity(percent):
    """Niveau d'une limite : "ok", "warn" ou "crit"."""
    if percent >= CRIT:
        return "crit"
    if percent >= WARN:
        return "warn"
    return "ok"


LEVELS = ["ok", "warn", "crit", "full"]


def level(percent):
    """Comme severity(), avec un niveau "full" supplémentaire une fois la limite atteinte."""
    return "full" if percent >= 100 else severity(percent)


def notifications(previous, usage):
    """Messages à notifier depuis le précédent relevé.

    previous : état renvoyé par l'appel précédent ({type: (niveau, réinitialisation)}),
    ou None au premier relevé, qui ne notifie rien. Renvoie (messages, nouvel état).
    """
    state = {l.kind: (level(l.percent), l.resets_at) for l in usage.limits}
    if previous is None:
        return [], state
    messages = []
    for l in usage.limits:
        if l.kind not in previous:
            continue
        old_level, old_reset = previous[l.kind]
        new_level = state[l.kind][0]
        if l.resets_at > old_reset and old_level != "ok":
            messages.append(f"{l.label} : limite réinitialisée ({l.percent:.0f} % utilisés).")
        elif LEVELS.index(new_level) > LEVELS.index(old_level):
            if new_level == "full":
                messages.append(f"{l.label} : limite atteinte. "
                                f"Réinitialisation dans {format_remaining(l.remaining())}.")
            else:
                messages.append(f"{l.label} : {l.percent:.0f} % utilisés "
                                f"(réinit. dans {format_remaining(l.remaining())}).")
    return messages, state


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
        pace = format_pace(l)
        if pace:
            if color and l.exhaustion():
                pace = ANSI["warn"] + pace + ANSI_RESET
            print(f"{'':<16} {pace}")
    if usage.extra:
        print(f"{'Crédits supp.':<16} {usage.extra.describe()}")
    if usage.describe_breakdown():
        print(f"{'Répartition 7 j':<16} {usage.describe_breakdown()}")


def statusline(usage, color):
    """Ligne compacte pour la status line de Claude Code, ex. « 5h 28% · 7j 85% »."""
    parts = []
    for l in usage.limits:
        text = f"{SHORT_LABELS.get(l.kind, l.label)} {l.percent:.0f}%"
        parts.append(ANSI[severity(l.percent)] + text + ANSI_RESET if color else text)
    return " · ".join(parts)


MAX_RETRY_DELAY = 15 * 60


def retry_delay(interval, failures):
    """Délai avant le prochain appel : doublé à chaque échec consécutif, plafonné à 15 min."""
    return min(interval * 2 ** failures, max(interval, MAX_RETRY_DELAY))


def watch(interval, color):
    """Rafraîchit l'affichage dans le terminal jusqu'à Ctrl+C."""
    failures = 0
    try:
        while True:
            try:
                # Réutilise une réponse récente (status line, interface Qt) si possible
                usage, error, failures = fetch_usage(max_age=interval - 5), None, 0
            except UsageError as e:
                error, failures = e, failures + 1
            delay = retry_delay(interval, failures)
            if sys.stdout.isatty():
                print("\033[H\033[2J", end="")
            if error:
                print(f"Erreur : {error}")
            else:
                print_table(usage, color)
            print(f"\nMis à jour à {datetime.now():%H:%M:%S} · "
                  f"prochain rafraîchissement dans {delay} s · Ctrl+C pour quitter", flush=True)
            time.sleep(delay)
    except KeyboardInterrupt:
        return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Affiche l'utilisation des limites Claude.")
    parser.add_argument("--json", action="store_true", help="sortie JSON")
    parser.add_argument("--no-color", action="store_true", help="désactive les couleurs")
    parser.add_argument("--watch", nargs="?", const=CONFIG["refresh_interval"], type=int,
                        metavar="SECONDES",
                        help="rafraîchit l'affichage en continu "
                             f"({CONFIG['refresh_interval']} s par défaut, 10 s minimum)")
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
