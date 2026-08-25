#!/usr/bin/env bash
# Pull the base images from an Aliyun ACR repository and retag them to their
# canonical docker.io names, so the Dockerfiles and docker-compose.yml need no
# changes.
#
# Set ACR_REPO to your repository, without a tag. Use the -vpc- host when the
# ECS is in the same region as the registry: it is faster and does not bill
# against public bandwidth.
#
#   export ACR_REPO=registry-vpc.cn-hangzhou.aliyuncs.com/<namespace>/base
#   ./scripts/pull-from-acr.sh
#
# Requires: docker login <registry-host> first.
set -u

: "${ACR_REPO:?set ACR_REPO, e.g. registry-vpc.cn-hangzhou.aliyuncs.com/orchid/base}"

# <acr tag>=<canonical docker.io name>
MAP="
python-3.11-slim=python:3.11-slim
node-20-alpine=node:20-alpine
nginx-1.27-alpine=nginx:1.27-alpine
redis-7-alpine=redis:7-alpine
postgres-16-alpine=postgres:16-alpine
certbot-latest=certbot/certbot:latest
"

failed=""
for pair in $MAP; do
  acr_tag="${pair%%=*}"
  local_tag="${pair#*=}"

  if docker image inspect "$local_tag" >/dev/null 2>&1; then
    echo "== $local_tag already present, skipping"
    continue
  fi

  echo "== $local_tag  <-  $ACR_REPO:$acr_tag"
  if docker pull "$ACR_REPO:$acr_tag"; then
    docker tag "$ACR_REPO:$acr_tag" "$local_tag"
    docker rmi "$ACR_REPO:$acr_tag" >/dev/null 2>&1
    echo "   tagged as $local_tag"
  else
    echo "   FAILED" >&2
    failed="$failed $local_tag"
  fi
done

echo
if [ -n "$failed" ]; then
  echo "FAILED:$failed" >&2
  echo "Check that the ACR build for those tags succeeded, and that you are" >&2
  echo "logged in:  docker login ${ACR_REPO%%/*}" >&2
  exit 1
fi
echo "All base images present. Next: docker compose build"
