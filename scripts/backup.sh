#!/bin/sh
# Copies the database and all media to another drive. Run weekly, with the stack up:
#   scripts/backup.sh /Volumes/Backup/course-assistant
set -eu
target=${1:?Usage: scripts/backup.sh TARGET_DIRECTORY}
stamp=$(date +%Y-%m-%d)
mkdir -p "$target/$stamp"

docker compose exec -T postgres pg_dump -U course -Fc course > "$target/$stamp/database.dump"
docker run --rm \
    -v course-assistant_minio:/data:ro \
    -v "$target/$stamp:/backup" \
    alpine tar -C /data -czf /backup/media.tar.gz .

echo "Backed up to $target/$stamp"
df -h "$target" | tail -1
