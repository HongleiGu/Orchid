# docker-mirror

Passthrough Dockerfiles that exist only so Aliyun ACR can re-host Docker Hub
base images. Nothing here is part of the application build.

Why: mainland ECS cannot reliably pull from Docker Hub, and the registry
accelerators are unreliable (`registry-mirrors` is not a real fallback chain --
one failing entry aborts the pull instead of trying the next). ACR Personal
Edition can build from GitHub on an *overseas* build machine, which reaches
Docker Hub fine, and the result is then pulled domestically.

One ACR build rule per directory, each producing its own tag:

| Directory   | Upstream image           | Suggested ACR tag |
|-------------|--------------------------|-------------------|
| `python/`   | `python:3.11-slim`       | `python-3.11-slim`   |
| `node/`     | `node:20-alpine`         | `node-20-alpine`     |
| `nginx/`    | `nginx:1.27-alpine`      | `nginx-1.27-alpine`  |
| `redis/`    | `redis:7-alpine`         | `redis-7-alpine`     |
| `postgres/` | `postgres:16-alpine`     | `postgres-16-alpine` |
| `certbot/`  | `certbot/certbot:latest` | `certbot-latest`     |

On the server, pull and retag to the canonical names the Dockerfiles and
docker-compose.yml already reference -- see scripts/pull-from-acr.sh.
