#!/usr/bin/env bash
# install.sh — installe mailcli dans ~/.local/bin
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${HOME}/.local/bin/mailcli"
SHARE="${HOME}/.local/share/mailcli"

mkdir -p "${HOME}/.local/bin" "${SHARE}"

cp "${DIR}/mailcli.py" "${SHARE}/mailcli.py"
chmod +x "${SHARE}/mailcli.py"

cat > "${TARGET}" <<EOF
#!/usr/bin/env bash
exec python3 "${SHARE}/mailcli.py" "\$@"
EOF
chmod +x "${TARGET}"

# config example
if [ ! -f "${HOME}/.config/mailcli/config.json" ]; then
    mkdir -p "${HOME}/.config/mailcli"
    cp "${DIR}/config.example.json" "${HOME}/.config/mailcli/config.json"
    chmod 600 "${HOME}/.config/mailcli/config.json"
    echo "Config créée : ${HOME}/.config/mailcli/config.json"
    echo "Édite ce fichier avec ton email et ton mot de passe d'application, puis lance : mailcli whoami"
else
    echo "Config existante conservée."
fi

echo "Installation terminée. Vérifie : mailcli --help"
EOF
chmod +x /home/terry/.local/share/mailcli/install.sh