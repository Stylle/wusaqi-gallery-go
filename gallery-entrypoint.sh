#!/bin/sh
set -eu
if [ "$(id -u)" = 0 ]; then
  /app/data-init
  exec gosu 10001:10001 /app/gallery "$@"
fi
exec /app/gallery "$@"
