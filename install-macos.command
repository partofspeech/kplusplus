#!/bin/sh
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1
"$project_dir/install.sh" "$@"
install_result=$?
printf '\nНажмите Enter, чтобы закрыть окно…\n'
read -r reply
exit "$install_result"
