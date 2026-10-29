# Idées d'amélioration

✅ fait · ⏸️ non fait (voir la raison)

## Interface Qt

- ✅ **Icône dans la zone de notification**, avec le pourcentage de la limite la plus utilisée et un menu Afficher / Rafraîchir / Quitter.
- ✅ **Compte à rebours** jusqu'à la réinitialisation, à côté de la date.
- ✅ **Notifications de bureau** : seuils d'alerte et critique franchis, limite atteinte, réinitialisation.
- ✅ **Mode compact** (sans bordure, déplaçable) et **toujours au premier plan**.
- ✅ **Thème sombre** qui suit le système.
- ✅ **Bouton désactivé pendant le chargement**.
- ✅ **Position et taille de la fenêtre mémorisées** (`QSettings`).

## Données

- ✅ **Rythme de consommation** et estimation de l'heure à laquelle la limite sera atteinte.
- ✅ **Historique** en SQLite, et mini-graphique de l'évolution sur la fenêtre en cours.
- ✅ **Crédits d'usage supplémentaire** (`extra_usage`).
- ✅ **Répartition par produit** (`seven_day_breakdown`).
- ✅ **Affichage générique des limites** à partir du tableau `limits`.

## Ligne de commande

- ✅ **Sortie JSON** (`--json`).
- ✅ **Mode surveillance** (`--watch`).
- ✅ **Barres de progression en couleur**.
- ✅ **Status line Claude Code** (`--statusline`, avec cache de 60 s).
- ✅ **Codes de retour** selon le seuil (`--check`).

## Robustesse

- ✅ **Messages d'erreur clairs** selon la cause.
- ⏸️ **Rafraîchissement du jeton avec le `refreshToken`** : non fait volontairement. Il faudrait réécrire `~/.claude/.credentials.json`, le fichier de Claude Code. Une écriture concurrente ou un format mal reproduit pourrait déconnecter Claude Code, et le serveur pourrait invalider l'ancien jeton de rafraîchissement. Lancer `claude` une fois suffit à renouveler le jeton.
- ✅ **Prise en charge de macOS** (Trousseau), non testée sur un vrai Mac.
- ✅ **Délai de rafraîchissement adaptatif** en cas d'erreurs répétées.
- ✅ **Tests unitaires** (`tests/`).

## Distribution

- ✅ **Paquet Python** (`pyproject.toml`) avec les commandes `claude-usage` et `claude-usage-gui`.
- ✅ **Fichier `.desktop`** et démarrage automatique (`desktop/install-desktop.sh`).
- ✅ **Capture d'écran** dans le README.
- ⏸️ **Licence** : le choix revient au propriétaire du dépôt (MIT, Apache-2.0, GPL…).
- ✅ **Fichier de configuration** (`~/.config/claude-usage/config.toml`).

## Nouvelles pistes

- Option `--history` dans le CLI pour exporter l'historique en CSV.
- Graphique détaillé de l'historique dans une fenêtre dédiée (plusieurs fenêtres passées).
- Notification quand la projection annonce que la limite sera atteinte avant la réinitialisation.
