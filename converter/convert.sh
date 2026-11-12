#!/bin/sh
# Runs with no network and no secrets. Sees only the shared /convert folder.
# A job is a folder holding input.<ext>, a `format` file, and a `ready` marker.
set -u
cd /convert || exit 1
while true; do
    for marker in */ready; do
        [ -e "$marker" ] || continue
        job=$(dirname "$marker")
        rm -f "$marker"
        format=$(cat "$job/format")
        input=$(ls "$job"/input.* | head -n 1)
        if timeout 500 soffice --headless --norestore \
            -env:UserInstallation=file:///tmp/lo-profile \
            --convert-to "$format" --outdir "$job/out" "$input" > "$job/log" 2>&1 \
            && [ -f "$job/out/input.$format" ]; then
            mv "$job/out/input.$format" "$job/input.$format"
            touch "$job/done"
        else
            tail -n 3 "$job/log" > "$job/error"
        fi
    done
    sleep 1
done
