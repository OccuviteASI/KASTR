# KASTR headless container (0.13.1) -- a relay / publisher box that updates
# itself over the internet.                                   (see DOCKER.md)
#
# The image wraps the WSL-built Linux binary as-is (dist/linux/KASTR, one
# artifact per release with the same sha256 as the fleet feed); nothing is
# compiled here and no network is needed at build time. Build with
# ./docker-build.sh, which refuses a dist/linux that is not at VERSION.
#
# ubuntu:26.04 is not a taste: the binary is built on Ubuntu 26.04 (glibc
# 2.43) and is dynamically linked against that glibc, so an older base
# (bookworm-slim, 24.04) refuses to run it.

# --- stage: lay out /opt/kastr from whatever the build context carries -----
# .dockerignore lets only dist/linux/KASTR, dist/linux/BUILT_VERSION,
# dist/updates/{windows,macos,latest.json} and docker/ through, so `COPY
# dist/` is small and works whether or not dist/updates exists yet (a
# missing optional file would fail a direct COPY).
FROM ubuntu:26.04 AS stage
COPY dist/ /src/
RUN set -eu; \
    mkdir -p /opt/kastr/updates; \
    install -m 0755 /src/linux/KASTR /opt/kastr/KASTR; \
    tr -d '\r' < /src/linux/BUILT_VERSION > /opt/kastr/BUILT_VERSION; \
    if [ -d /src/updates ]; then cp -a /src/updates/. /opt/kastr/updates/; fi; \
    rm -rf /src; \
    echo "image carries KASTR v$(cat /opt/kastr/BUILT_VERSION)"; \
    find /opt/kastr -type f -printf '  %p  %s bytes\n'

# --- runtime -----------------------------------------------------------------
FROM ubuntu:26.04
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl tzdata \
 && rm -rf /var/lib/apt/lists/*
COPY --from=stage /opt/kastr /opt/kastr
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh

# KASTR_CONTAINER=1: relaunch_self exits 75 instead of spawning (the
# entrypoint loop restarts on the -- possibly just updated -- binary).
# KASTR_STATE_DIR: the launcher's state (launch.log, relay-auth.json,
# rtsp-feeds.json, TLS CA ...) lands in the volume, not in /root.
ENV KASTR_CONTAINER=1 \
    KASTR_STATE_DIR=/data/state \
    KASTR_PORT=8000
VOLUME /data
# web, https, relay (QUIC = UDP, and its TCP fallback), token minter, wss
EXPOSE 8000 8443 4443/udp 4443 4444 4445
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${KASTR_PORT:-8000}/api/instance" | grep -q '"app": "KASTR"' || exit 1
ENTRYPOINT ["/entrypoint.sh"]
