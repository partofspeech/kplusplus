#!/bin/sh
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1
for python_command in python3.14 python3.13 python3.12 python3.11 python3 python; do
  if command -v "$python_command" >/dev/null 2>&1 && "$python_command" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    exec "$python_command" "$project_dir/install.py" "$@"
  fi
done
printf '%s\n' 'Нужен Python 3.11 или новее: https://www.python.org/downloads/' >&2
exit 1
