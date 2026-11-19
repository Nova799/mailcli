# mailcli

[![secret-scan](https://github.com/Nova799/mailcli/actions/workflows/secret-scan.yml/badge.svg)](https://github.com/Nova799/mailcli/actions/workflows/secret-scan.yml)

CLI Python pour lire (et seulement lire) une boîte mail **Gmail** depuis le terminal, via IMAP et un mot de passe d'application. Sans navigateur, sans client lourd, scriptable.

> ⚠️ `mailcli` ne permet pas d'envoyer des mails. Il est orienté lecture : lister, rechercher, lire, télécharger les pièces jointes, marquer lu/non lu, supprimer.

## Installation

```bash
git clone https://github.com/Nova799/mailcli.git
cd mailcli
./install.sh
```

L'installation :
- copie `mailcli.py` dans `~/.local/share/mailcli/`
- crée un wrapper `~/.local/bin/mailcli`
- crée `~/.config/mailcli/config.json` à partir de `config.example.json` si absent (permissions `600`)

Vérifie que `~/.local/bin` est dans ton `PATH`.

## Configuration

1. Génère un **mot de passe d'application** : Compte Google → Sécurité → Mots de passe des applications (16 caractères, ton mot de passe Gmail habituel ne fonctionne pas).
2. Renseigne la config :

```bash
mailcli setup        # interactif, teste la connexion
# ou édite directement ~/.config/mailcli/config.json
```

Ou via variables d'environnement (prioritaires sur la config) :

| Variable | Défaut | Description |
| --- | --- | --- |
| `MAILCLI_EMAIL` | (config) | Adresse email |
| `MAILCLI_PASSWORD` | (config) | Mot de passe d'application |
| `MAILCLI_IMAP_HOST` | `imap.gmail.com` | Serveur IMAP |
| `MAILCLI_IMAP_PORT` | `993` | Port IMAP |

**Ne commit jamais `config.json`.** Il est dans `.gitignore`. Le fichier est en clair : garde-le en `600` et ne le partage pas. Préfère les variables d'environnement en CI.

## Utilisation

```bash
mailcli whoami                      # compte configuré
mailcli folders                     # lister les dossiers (accents/espaces gérés)
mailcli list [DOSSIER]              # lister les mails (défaut INBOX)
mailcli list INBOX -n 30 -u         # 30 non-lus
mailcli unread-count [DOSSIER]      # ne compte que les non-lus
mailcli read UID [--mark-read]      # lire un mail
mailcli attachments UID             # lister les pièces jointes
mailcli download UID [-o DIR] [-i N]# télécharger les pièces jointes
mailcli search "texte"              # rechercher
mailcli search --from x@y.com --subject facture --since 2026-11-01
mailcli search --raw "has:attachment larger:5M"  # opérateurs Gmail
mailcli mark-read UID | mark-unread UID
mailcli delete UID                  # vers la corbeille
```

Ajoutez `--json` **après** la sous-commande pour une sortie machine-readable :

```bash
mailcli list INBOX -n 5 --json
mailcli search --raw "from:github.com" --json
```

## Exemples

```bash
# 10 derniers non-lus
mailcli list INBOX -u -n 10

# Mails GitHub depuis une date, en JSON
mailcli search --from github.com --since 2026-11-15 --json

# Lire puis télécharger la pièce jointe n°1
mailcli read <uid>
mailcli download <uid> -i 1 -o ~/Downloads
```

## Sécurité & limites

- Lecture seule (IMAP), aucun envoi.
- Un seul compte à la fois.
- Pièces jointes chargées en mémoire avant écriture.
- `delete` copie le mail dans la corbeille détectée automatiquement avant de l'expunger.
- Le HTML est converti en texte basique.
- Le dépôt utilise un workflow `secret-scan` ([badge](https://github.com/Nova799/mailcli/actions/workflows/secret-scan.yml)) qui vérifie que le dépôt (historique compris) ne contient pas de credentials : [gitleaks](https://github.com/gitleaks/gitleaks) + recherche de motifs de mots de passe d'application Gmail + contrôle que `config.json` n'est jamais tracké.

Pour ajouter votre propre scan local avant `git push` :

```bash
gitleaks detect --source . --config .gitleaks.toml
```

## Licence

MIT — voir [LICENSE](LICENSE).
