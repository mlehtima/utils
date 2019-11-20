# SCRIPTPATH="$(dirname "`readlink -f $0`")"
# source "$SCRIPTPATH/update-common.sh" || exit 1

PRINT_RED='\033[0;31m'
PRINT_GREEN='\033[0;32m'
PRINT_NC='\033[0m'

if [ -z "$script_version" ]; then
    script_version="<undefined>"
fi

print_error() {
    echo -e "${PRINT_RED}$@${PRINT_NC}"
}

print_debug() {
    if [ "$DEBUG" == "1" ]; then
        echo -e "${PRINT_GREEN}$@${PRINT_NC}" >&2
    fi
}

print_normal() {
    echo -e "${PRINT_GREEN}$@${PRINT_NC}" >&1
}

print_version() {
    echo "$(basename $0) v$script_version"
}

run_cmd() {
    print_debug "$ $@"
    "$@"
}

check_bin() {
    local all_good=1
    while [ $# -gt 0 ]; do
        which "$1" 1>/dev/null 2>&1
        if [ ! $? -eq 0 ]; then
            print_error "$1 not found in \$PATH"
            all_good=0
        fi
        shift
    done

    if [ ! $all_good -eq 1 ]; then
        echo "Required bits missing. Abort."
        exit 1
    fi
}

enter_dir() {
    print_debug "# Enter $1"
    pushd "$1" 1>/dev/null 2>&1
}

leave_dir() {
    print_debug "# Leave $1"
    popd 1>/dev/null 2>&1
}
