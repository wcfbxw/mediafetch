#!/usr/bin/env sh
set -eu

docker compose run --rm cleanup python -m app.services.cleanup --once
