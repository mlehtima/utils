#!/bin/bash

SDK_PATH="/srv/mer/sdks/sdk"

running=$(dk-parse --running-id)
if [ $? -eq 0 ]; then
    # something is running, let's wait until it's done
    dk-tasks --follow-hack $running > /dev/null
    if [ $? -ne 0 ]; then
        exit 1
    fi
fi

last_path="$(dk-parse --last-path)"
if [ $? -eq 0 ] && [ ! -z "$last_path" ]; then
    logfile=$(tempfile -d $SDK_PATH/tmp -p post-)
    touch "$logfile"

    cd "$last_path"
    install-built "$@" >> "$logfile" &
    ppid=$!

    dk tail --pid $ppid -f "/tmp/$(basename $logfile)" --follow
    rm "$logfile"
fi
