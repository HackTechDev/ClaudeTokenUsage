# ClaudeUsage

Petit script qui affiche l'utilisation des limites d'un abonnement Claude (Pro / Max) :

- **Session** : fenêtre glissante de 5 heures, avec sa date de réinitialisation
- **Hebdomadaire** : limite sur 7 jours (tous modèles), avec sa date de réinitialisation
- **Hebdo Opus / Sonnet** : limites par modèle, affichées seulement quand elles s'appliquent

Les valeurs sont des **pourcentages** de la limite. Anthropic ne publie pas de plafond en nombre de tokens pour les abonnements.

## Exemple

```
$ ./claude_usage.py
Session (5 h)           16.0 %   réinit. : 29/10/2026 23:50
Hebdomadaire            84.0 %   réinit. : 30/10/2026 13:00
```

Les dates sont converties dans le fuseau horaire local et arrondies à la minute.

## Prérequis

- Python 3.7 ou plus récent (bibliothèque standard uniquement)
- Claude Code installé et connecté avec un compte claude.ai, ce qui crée `~/.claude/.credentials.json`
- Pour l'interface graphique : PyQt6 (`sudo apt install python3-pyqt6` ou `pip install PyQt6`)

## Utilisation

### Ligne de commande

```bash
./claude_usage.py
```

### Interface graphique (Qt)

```bash
./claude_usage_qt.py
```

La fenêtre affiche une barre de progression par limite, avec sa date de réinitialisation. La couleur de la barre est verte, orange à partir de 75 %, puis rouge à partir de 90 %. Les données se rafraîchissent automatiquement **toutes les minutes**, et le bouton « Rafraîchir » force une mise à jour immédiate. L'appel réseau passe par un thread séparé pour ne pas figer la fenêtre. En cas d'erreur, par exemple un jeton expiré, le message s'affiche en bas de la fenêtre.

Les deux programmes partagent la fonction `fetch_usage()` de `claude_usage.py`.

## Fonctionnement

Le script lit le jeton OAuth dans `~/.claude/.credentials.json`, puis interroge l'endpoint utilisé par Claude Code :

```bash
TOKEN=$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.claude/.credentials.json')))['claudeAiOauth']['accessToken'])")
curl -s https://api.anthropic.com/api/oauth/usage \
  -H "Authorization: Bearer $TOKEN" \
  -H "anthropic-beta: oauth-2025-04-20"
```

Champs utiles de la réponse :

| Champ | Signification |
|---|---|
| `five_hour.utilization` / `five_hour.resets_at` | Session de 5 h |
| `seven_day.utilization` / `seven_day.resets_at` | Limite hebdomadaire |
| `seven_day_opus`, `seven_day_sonnet` | Limites hebdo par modèle (`null` si non applicables) |
| `extra_usage` | Crédits d'usage supplémentaire |

## Alternative sans script

Dans Claude Code, la commande `/usage` affiche les mêmes informations.

## Limites et précautions

- L'endpoint **n'est pas documenté officiellement** et peut changer sans préavis.
- Le jeton d'accès expire. Claude Code le renouvelle tout seul quand il tourne. Si le script renvoie une erreur `401`, lancez `claude` une fois puis réessayez.
- Le jeton donne accès à votre compte : ne le partagez pas et ne versionnez jamais `~/.claude/.credentials.json`.
