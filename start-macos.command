#!/bin/sh
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  printf '%s\n' 'Сначала запустите install-macos.command.' >&2
  exit 1
fi
exec .venv/bin/python -m interfaces.web.app
