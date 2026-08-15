#!/bin/bash
# Refresca los datos desde el Mac, sin esperar al cron de GitHub.
#
#   ./actualizar.sh          descarga y reescribe docs/data.json
#   ./actualizar.sh --ver    además lo abre en el navegador
#
# La clave se lee de ~/.config/windsor/api_key. Para guardarla la primera vez:
#   mkdir -p ~/.config/windsor
#   read -s -p "Windsor API key: " k && printf '%s' "$k" > ~/.config/windsor/api_key
#   chmod 600 ~/.config/windsor/api_key

set -euo pipefail
cd "$(dirname "$0")"

CLAVE=~/.config/windsor/api_key
if [ ! -f "$CLAVE" ]; then
  echo "No encuentro $CLAVE. Mira la cabecera de este script para crearla." >&2
  exit 1
fi

export WINDSOR_API_KEY="$(cat "$CLAVE")"
python3 fetch_data.py

if [ "${1:-}" = "--ver" ]; then
  # El servidor de vista previa no puede leer de ~/Documents, así que se sirve
  # desde una copia en /tmp.
  TMP=$(mktemp -d)
  cp docs/index.html docs/data.json "$TMP/"
  ( cd "$TMP" && python3 -m http.server 8899 >/dev/null 2>&1 & )
  sleep 1
  open "http://localhost:8899/index.html"
  echo "Sirviendo en http://localhost:8899 — Ctrl+C para parar."
  wait
fi
