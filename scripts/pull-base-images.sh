#!/usr/bin/env bash
# Pull the base images by naming a mirror registry explicitly, then retag them
# to their canonical docker.io names so the Dockerfiles and compose file find
# them unchanged.
#
# Why this exists: the daemon's registry-mirrors list is not a reliable
# fallback chain. It picks a mirror and, if that mirror fails partway through a
# blob (e.g. a 500 from an Aliyun accelerator), the pull aborts rather than
# retrying the next entry. Naming the registry in the image reference sidesteps
# that and lets us do the retry ourselves, in the same first-one-wins style as
# the package mirrors in the Dockerfiles.
#
#     ./scripts/pull-base-images.sh            # all images
#     ./scripts/pull-base-images.sh build      # only what `compose build` needs
#     ./scripts/pull-base-images.sh runtime    # only what `compose up` pulls
set -u

MIRRORS="${DOCKER_MIRRORS:-docker.m.daocloud.io docker.1ms.run docker.xuanyuan.me}"

BUILD_IMAGES="library/python:3.11-slim library/node:20-alpine"
RUNTIME_IMAGES="library/nginx:1.27-alpine library/postgres:16-alpine library/redis:7-alpine certbot/certbot:latest"

case "${1:-all}" in
  build)   IMAGES="$BUILD_IMAGES" ;;
  runtime) IMAGES="$RUNTIME_IMAGES" ;;
  all)     IMAGES="$BUILD_IMAGES $RUNTIME_IMAGES" ;;
  *) echo "usage: $0 [all|build|runtime]" >&2; exit 2 ;;
esac

failed=""
for img in $IMAGES; do
  # docker.io implies the library/ namespace, so the local tag drops it
  local_tag="${img#library/}"

  if docker image inspect "$local_tag" >/dev/null 2>&1; then
    echo "== $local_tag already present, skipping"
    continue
  fi

  ok=0
  for m in $MIRRORS; do
    echo "== $local_tag via $m"
    if docker pull "$m/$img"; then
      docker tag "$m/$img" "$local_tag"
      docker rmi "$m/$img" >/dev/null 2>&1   # drop the mirror-qualified tag only
      echo "   tagged as $local_tag"
      ok=1
      break
    fi
    echo "   $m failed, trying next" >&2
  done

  [ "$ok" = 1 ] || { echo "   NO MIRROR SERVED $local_tag" >&2; failed="$failed $local_tag"; }
done

echo
if [ -n "$failed" ]; then
  echo "FAILED:$failed" >&2
  echo "Fall back to loading these from a machine that can reach Docker Hub:" >&2
  echo "  docker save <images> | gzip > base.tar.gz   # there" >&2
  echo "  docker load < base.tar.gz                   # here" >&2
  exit 1
fi
echo "All base images present. Next: docker compose build"
