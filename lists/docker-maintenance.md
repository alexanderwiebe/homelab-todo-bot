# Docker maintenance

- [ ] Pin image tags to specific versions instead of `:latest` across ~/docker/core/docker-compose.yml and ~/docker/otel/docker-compose.yml (13 services currently float on `:latest`, no reproducible rollback target)
- [ ] Reclaim disk space: 10 dangling images + 1 unused local volume, ~6GB reclaimable (`docker system df` / `docker image prune`)
- [ ] Investigate and remove unused images if no longer needed: `appropriate/curl:latest` (8 years old, abandoned upstream image), `busybox:latest`, `dev_container_feature_content_temp:latest`
- [ ] Set up automated/scheduled image updates or a manual update cadence (e.g. watchtower, or a recurring reminder) now that there's a way to track it here
