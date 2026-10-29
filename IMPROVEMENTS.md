# Idées d'amélioration

Classées par thème. Les éléments marqués ⭐ offrent le meilleur rapport utilité / effort.

## Interface Qt

- ⭐ **Icône dans la zone de notification** (`QSystemTrayIcon`) : afficher le pourcentage de session directement dans l'icône, avec un menu « Afficher / Rafraîchir / Quitter ». La fenêtre deviendrait facultative.
- ⭐ **Compte à rebours** jusqu'à la réinitialisation (« dans 2 h 14 min ») à côté de la date absolue, mis à jour chaque minute.
- **Notifications de bureau** quand un seuil est franchi (75 %, 90 %, 100 %) et quand une limite se réinitialise.
- **Mode compact / toujours au premier plan** : petite fenêtre sans bordure, à garder dans un coin de l'écran.
- **Thème sombre** qui suit le thème du système.
- **Bouton désactivé pendant le chargement**, avec un indicateur d'activité.
- **Mémoriser la position et la taille** de la fenêtre (`QSettings`).

## Données

- ⭐ **Rythme de consommation** : comparer le pourcentage utilisé au temps écoulé dans la fenêtre. Exemple : 84 % consommés en 85 % de la semaine, c'est le bon rythme ; 84 % en 50 %, risque de blocage. Afficher une estimation du moment où la limite sera atteinte.
- **Historique** : enregistrer chaque mesure (SQLite ou CSV) et afficher un petit graphique de l'évolution sur la session et la semaine.
- **Crédits d'usage supplémentaire** : afficher `extra_usage`, c'est-à-dire le montant consommé, le plafond mensuel et le statut (activé ou épuisé).
- **Répartition par produit** : afficher `seven_day_breakdown` (Claude Code, Chats, Cowork…).
- **Affichage générique des limites** : utiliser le tableau `limits` de la réponse plutôt qu'une liste de clés codées en dur, pour afficher automatiquement les nouvelles limites qu'Anthropic pourrait ajouter.

## Ligne de commande

- ⭐ **Sortie JSON** (`--json`) pour l'intégration dans d'autres outils (scripts, Waybar, Polybar, Conky…).
- **Mode surveillance** (`--watch`) qui rafraîchit l'affichage dans le terminal.
- **Barres de progression en couleur** dans le terminal.
- **Status line Claude Code** : un mode `--statusline` à sortie d'une ligne (`S 20% · H 84%`) à brancher dans `settings.json`.
- **Codes de retour** selon le seuil atteint (utile dans des scripts : `0` normal, `1` alerte, `2` limite atteinte).

## Robustesse

- ⭐ **Messages d'erreur clairs** : distinguer le fichier d'identifiants absent, le jeton expiré (`401`), l'absence de réseau et un format de réponse inattendu, avec la marche à suivre pour chacun.
- **Rafraîchissement du jeton** : utiliser le `refreshToken` quand l'`accessToken` a expiré, pour ne plus dépendre de Claude Code ouvert. À faire avec prudence : le jeton renouvelé doit être réécrit sans casser le fichier utilisé par Claude Code.
- **Prise en charge de macOS** : les identifiants y sont stockés dans le Trousseau, pas dans `~/.claude/.credentials.json`.
- **Délai de rafraîchissement adaptatif** : espacer les appels en cas d'erreurs répétées pour ne pas solliciter inutilement l'API.
- **Tests unitaires** sur l'analyse de la réponse, avec des réponses JSON d'exemple (y compris des champs `null` ou absents).

## Distribution

- **Paquet Python** (`pyproject.toml`) avec deux commandes : `claude-usage` et `claude-usage-gui`.
- **Fichier `.desktop`** pour lancer l'interface depuis le menu des applications, et option de démarrage automatique à l'ouverture de session.
- **Capture d'écran** de l'interface dans le README.
- **Licence** : choisir et ajouter un fichier `LICENSE`. Le dépôt est public mais n'a pas de licence pour l'instant.
- **Configuration** : un fichier (`~/.config/claude-usage/config.toml`) pour l'intervalle de rafraîchissement, les seuils de couleur et les notifications.
