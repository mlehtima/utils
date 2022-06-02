#!/bin/bash

if [ -z "$(ps --help 2>&1 | grep BusyBox)" ]; then
    OUR_TTY=1
else
    OUR_TTY=$(ps -o pid,tty | grep $$ | cut -d, -f2)
fi
WIN_COLUMNS=$(stty -a </dev/pts/$OUR_TTY | grep "columns" | sed -e 's/.*columns \([0-9]*\);.*/\1/')
MAX_LENGTH=$(($WIN_COLUMNS-43))

info_for_name() {
    local mode=$1
    local name="$2"
    local dbus_pid=
    local cmdline=
    local cmdline_len=

    dbus_pid=$(dbus-send --system --print-reply --dest=org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus.GetConnectionUnixProcessID string:"$name" 2>/dev/null | awk '$1 == "uint32" { print $2 }')
    if [ -z "$dbus_pid" ]; then
        if [ "$mode" == "single" ]; then
            echo "Error org.freedesktop.DBus.Error.NameHasNoOwner: Could not get PID of name '$name': no such name" >&2
            exit 1
        fi
        return
    fi

    if [ -n "$dbus_pid" ]; then
        cmdline="$(cat /proc/$dbus_pid/cmdline | tr '\000' ' ' | cut -d" " -f1)"
        if [ "$mode" == "single" ]; then
            echo "$name $dbus_pid $cmdline"
        else
            cmdline_len=${#cmdline}
            if [ $cmdline_len -gt $MAX_LENGTH ]; then
                cmdline="${cmdline:0:$MAX_LENGTH}..."
            fi
            if [ ${#name} -gt 26 ]; then
                echo     "$name \\"
                echo -en "                                      $cmdline\r"
                echo     "                           $dbus_pid"
            else
                echo -en "                                      $cmdline\r"
                echo -en "                           $dbus_pid\r"
                echo     "$name"
            fi
        fi
    fi
}

if [ $# -gt 0 ]; then
    while [ $# -gt 0 ]; do
        info_for_name single "$1"
        shift
    done
else
    for name in $(dbus-send --system --print-reply --dest=org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus.ListNames | awk '$1 == "string" { print $2 }' | cut -d\" -f2); do
        info_for_name all "$name"
    done
fi
