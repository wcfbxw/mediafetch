#!/usr/bin/env sh
set -eu

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env. Replace TOKEN_SECRET before exposing this service."
fi

docker compose up -d --build
docker compose ps
