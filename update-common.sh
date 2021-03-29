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
    local line="$@"
    line="${line//%nc/${PRINT_NC}}"
    line="${line//%gc/${PRINT_GREEN}}"
    line="${line//%rc/${PRINT_RED}}"
    echo -e "${PRINT_GREEN}$line${PRINT_NC}" >&1
}

print_version() {
    echo "$(basename $0) $script_version"
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

common_tempfile() {
    if [ $# -lt 1 ]; then
        echo "Internal error: Incorrect parameter count for common_tempfile()" 1>&2
        exit 100
    fi

    local _store_to=$1
    shift

    local _template=
    if [ $# -gt 0 ]; then
        _template="$1"
    else
        _template="$(basename $0).$$.XXXXXX"
    fi
    shift

    local _path="/tmp"
    if [ $# -gt 0 ]; then
        _path="$1"
    fi

    local _fn=

    # Try mktemp first
    if which mktemp >/dev/null; then
        _fn="$(mktemp --tmpdir="$_path" "${_template}")"
    else
        local _n=
        local _test=

        if [ -z "$_path" ]; then
            _path="/tmp"
        fi

        while [[ -z "$_test" || -f "$_path/$_test" ]]; do
            _test="$_template"
            while [[ "$_test" =~ "X" ]]; do
                ((_n = RANDOM % 9))
                _test="${_test/X/$_n}"
            done
        done
        _fn="$_path/$_test"
        touch "$_fn"
    fi

    printf -v "$_store_to" %s "$_fn"
}
