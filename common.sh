# Common functions to use in utils.
#
# Add following boilerplate code to beginning of all scripts to get
# fancy collection of helper functions:
# (this apparently doesn't work in BSD, but what gives)
#
# SCRIPTPATH="$(dirname "`readlink -f $0`")"
# source "$SCRIPTPATH/common.sh" || exit 1
#
# All functions exit with 10 if internal error occurs.
#
# Example use:
# Have directory $HOME/bin/utils , with files common.sh (this script) and do_something.sh
# Have symlink in $HOME/bin pointing to your script do_something.sh
#

# Increase this when functionality changes or new helper functions are added
COMMON_VERSION=3

COMMON_CONFIG_LOCATION="$HOME/.config/$(basename $0).config"

# Test for recent enough bash
declare -A ___test_common_sh 2>/dev/null
if [ ! $? -eq 0 ]; then
    echo "$(basename $0): common.sh requires more recent bash version, abort."
    exit 1
fi

# Args: space separated list of binaries that
# need to be found in $PATH
# Exits with 1 if binary not found.
need_binaries() {
    local missing=0
    which 2>/dev/null
    if [ $? -eq 127 ]; then
        echo "$(basename $0): Critical binary which missing, abort."
        exit 10
    fi
    while [ $# -gt 0 ]; do
        which $1 1>/dev/null 2>/dev/null
        if [ $? != 0 ]; then
            echo "$(basename $0): Script dependency $1 not found in \$PATH."
            missing=1
        fi
        shift
    done

    if [ $missing == 1 ]; then
        exit 1
    fi
}

# Args: space separated list of environment variables
# that need to be defined. Default can be set. For example:
# check_config VARIABLE DEFAULT="default value"
# Exits with 2 if environment variable without default value not defined.
check_config() {
    need_binaries cut

    while [ $# -gt 0 ]; do

        local default=""
        local var="$1"
        local var_tmp=

        if [[ "$var" == *"="* ]]; then
            var_tmp="$(echo "$var" | cut -d= -f1)"
            var_tmp=${#var_tmp}
            ((var_tmp+=2))
            default="$(echo "$var" | cut -b${var_tmp}-)"
            var="$(echo "$var" | cut -d= -f1)"
        fi

        if [ -z "${!var}" ]; then
            if [ -z "$default" ]; then
                echo "$(basename $0): Configuration variable $var not defined, abort."
                exit 2
            else
                printf -v "$var" %s "$default"
            fi
        fi

        shift
    done
}

# Check for NEED_USER environment variable. If the variable is defined
# exit with 3 if current user is different.
check_need_user() {
    # If NEED_USER is not defined, allow running as current user
    if [ -z "$NEED_USER" ]; then
        return
    fi

    local user=$(whoami 2>/dev/null)

    if [ ! $? -eq 0 ]; then
        echo "$(basename $0): Critical binary whoami missing, abort."
        exit 10
    fi

    if [ "$user" != "$NEED_USER" ]; then
        echo "$(basename $0): This script needs to be run as $NEED_USER, abort."
        exit 3
    fi
}

# Args: Path to configuration file to source, if file exists.
load_config_absolute() {
    if [ -z "$1" ]; then
        echo "$(basename $0): Incorrect use of load_config_absolute(), abort."
        exit 10
    fi

    if [ -f "$1" ]; then
        source "$1"
    fi
}

# Args: Path to configuration file to source. Abort if file doesn't exist.
# Exit with 4 if file not found.
need_config_absolute() {
    if [ ! -f "$1" ]; then
        echo "$(basename $0): Config file \"$1\" not found, abort."
        exit 4
    fi

    load_config_absolute "$1"
}

# Try to source file from users home .config directory.
# Filename is <SCRIPT NAME>.config
load_config() {
    load_config_absolute "$COMMON_CONFIG_LOCATION"
}

# Try to source file from users home .config directory. Abort if file doesn't exist.
# Filename is <SCRIPT NAME>.config
# Exit with 4 if file not found.
need_config() {
    need_config_absolute "$COMMON_CONFIG_LOCATION"
}

# This can be used to easily check if variable is true or false.
# For example:
# if string_is_true $var; then
#   do_something
# fi
string_is_true() {
    case "${1,,}" in
        yes|y|true|1)       return 0    ;;
        no|n|false|0|"")    return 1    ;;
    esac
    return 0
}

# handle_options: Handle script arguments
#
# Common handlers:
#  - default        Called for every argument in the command line if it is not a switch
#  - error          Called if unknown switch is encountered (has default handler)
#  - missing        Called if switch is missing an argument (has default handler)
#  - autocomplete   Called for --autocomplete with defined switches (has default handler)
#
# Common options:
#  - min-arguments  Minimum number of command line arguments (default 0)
#
# Switch definition line:
#  -[short],--[long],[argument],[function to call or variable to store argument]
#
# [Short] and [long] options for the switch, [argument] can be 0 or 1, defining
# if the switch should have an argument. If the [argument] is 0 and the switch is found
# then the variable is defined with number of how many times the switch is found in
# command line. If [argument] is 1 then the switch value is stored to the [variable].
# If function is defined, then the function is called when the switch is found, if
# the switch has [argument] as 1 then the function shall have the argument passed to it.
#
# After definition of switches pass separator "---" and command line "$@" to the function.
#
# Example
#
# handle_options \
#     "default:  handle_default                                   " \
#     "error:    handle_error                                     " \
#     "  ,  --only-long-option, 0,  function_to_call_if_exists    " \
#     "-h,  ,                   0,  print_help                    " \
#     "-V,  --verbose,          1,  where_parameter_is_stored     " \
#     ---                                                         " \
#     "$@"
#

_handle_options_error_default() {
    echo "Unknown option '$@'." 1>&2
    exit 1
}

_handle_options_missing_default() {
    if [ $# -gt 0 ]; then
        echo "Argument missing for option '$1'" 1>&2
    else
        echo "Arguments missing." 1>&2
    fi
    exit 2
}

_handle_options_autocomplete_default() {
    echo -n "$@"
}

_handle_options_error() {
    local __func=$1
    shift
    $__func "$@"
}

_handle_options_test_func() {
    declare -F $1 1>/dev/null
    if [ ! $? -eq 0 ]; then
        echo "Internal error: Required function $1() not defined." 1>&2
        exit 60
    fi
}

handle_options() {
    declare -A __handle_opt_short
    declare -A __handle_opt_long
    declare -A __handle_opt_arg
    declare -A __handle_opt_func
    declare -A __handle_opt_default

    local __handle_opt_default_func=
    local __handle_opt_default_func_param=
    local __handle_opt_error_func=_handle_options_error_default
    local __handle_opt_missing_func=_handle_options_missing_default
    local __handle_opt_autocomplete_func=_handle_options_autocomplete_default

    declare -i __switch_count=0
    declare -i __arg_count=0
    declare -i __handle_switches=1
    declare -i __min_args=0

    local __line=

    # Handle configuration

    while [ $# -gt 0 ]; do
        # Normalize line (remove whitespace)
        __line="${1//[[:space:]]}"

        if [ "$__line" == "---" ]; then
            shift
            break
        fi

        case "$__line" in
            min-arguments:*)
                __min_args=${__line#min-arguments:}
                shift
                continue
                ;;
            default:*)
                if [[ "$__line" =~ "=" ]]; then
                    local __split_func=${__line#default:}
                    __handle_opt_default_func=${__split_func%=*}
                    __handle_opt_default_func_param=${__split_func#*=}
                else
                    __handle_opt_default_func=${__line#default:}
                fi
                _handle_options_test_func $__handle_opt_default_func
                shift
                continue
                ;;
            error:*)
                __handle_opt_error_func=${__line#error:}
                _handle_options_test_func $__handle_opt_error_func
                shift
                continue
                ;;
            missing:*)
                __handle_opt_missing_func=${__line#missing:}
                _handle_options_test_func $__handle_opt_missing_func
                shift
                continue
                ;;
            autocomplete:*)
                __handle_opt_autocomplete_func=${__line#autocomplete:}
                _handle_options_test_func $__handle_opt_autocomplete_func
                shift
                continue
                ;;
        esac

        if [ "$(echo $__line | grep -o , | wc -l)" != 3 ]; then
            echo "Internal error: Incorrect parameter count on '$__line'" 1>&2
            exit 60
        fi

        local __opt_short=$(echo $__line | cut -d, -f1 --)
        local __opt_long=$(echo $__line | cut -d, -f2 --)
        local __opt_arg=$(echo $__line | cut -d, -f3 --)
        local __opt_function="$(echo $__line | cut -d, -f4 --)"

        ((++__switch_count))

        if [ -n "$__opt_short" ]; then
            __handle_opt_short+=( [$__opt_short]=$__switch_count )
        fi
        if [ -n "$__opt_long" ]; then
            __handle_opt_long+=( [$__opt_long]=$__switch_count )
        fi
        __handle_opt_arg+=( [$__switch_count]=$__opt_arg )
        __handle_opt_func+=( [$__switch_count]=$__opt_function )
        shift
    done

    # Handle command line

    while [ $# -gt 0 ]; do
        declare -i __found=0

        case "$1" in
            --autocomplete)
                $__handle_opt_autocomplete_func -v --version ${!__handle_opt_short[@]} ${!__handle_opt_long[@]}
                exit 0
                ;;
            -v|--version)
                if [ -z "$SCRIPT_VERSION" ]; then
                    SCRIPT_VERSION="(undefined)"
                fi
                echo "$(basename $0) v$SCRIPT_VERSION"
                exit 0
                ;;
            *)
                if [ $__handle_switches -eq 1 ]; then
                    case "$1" in
                        --*)
                            if [ "$1" == "--" ]; then
                                __handle_switches=0
                                shift
                                continue
                            fi

                            if [ -z "${__handle_opt_long[$1]}" ]; then
                                _handle_options_error $__handle_opt_error_func $1
                            else
                                __found=${__handle_opt_long[$1]}
                            fi
                            ;;
                        -*)
                            if [ -z "${__handle_opt_short[$1]}" ]; then
                                _handle_options_error $__handle_opt_error_func $1
                            else
                                __found=${__handle_opt_short[$1]}
                            fi
                            ;;
                    esac
                fi

                if [ $__found -eq 0 ]; then
                    ((++__arg_count))
                    if [ -n "$__handle_opt_default_func" ]; then
                        __handle_opt_default+=( [$__arg_count]="$1" )
                        shift
                        continue
                    fi
                fi
                ;;
        esac

        if [ $__found -gt 0 ]; then
            local __func=${__handle_opt_func[$__found]}
            local __arg=

            if [ "${__handle_opt_arg[$__found]}" == "1" ]; then
                if [ $# -lt 2 ]; then
                    _handle_options_error $__handle_opt_missing_func $__func
                fi
                shift
                __arg="$1"
            fi

            declare -F $__func 1>/dev/null
            if [ $? -eq 0 ]; then
                $__func $__arg
            elif [ -n "$__arg" ]; then
                printf -v "$__func" %s "$__arg"
            else
                local __call_count=1
                if [ -n "$__func" ]; then
                    __call_count=$__func
                    ((++__call_count))
                fi
                printf -v "$__func" %d $__call_count
            fi
        fi

        shift
    done

    # Handle normal arguments (not switches)

    if [ $__arg_count -lt $__min_args ]; then
        _handle_options_error $__handle_opt_missing_func
    fi

    if [ $__arg_count -gt 0 ]; then
        if [ -n "$__handle_opt_default_func" ]; then
            for __i in $(seq $__arg_count); do
                ${__handle_opt_default_func} $__handle_opt_default_func_param "${__handle_opt_default[$__i]}"
            done
        fi
    fi
}

# Common helpers
handle_options_store_to() {
    local __target=$1
    local __string=
    local __pad=" "
    shift
    __string="${!__target}"
    if [ -z "$__string" ]; then
        __pad=""
    fi
    printf -v "$__target" %s "$__string$__pad$@"
}

expect_common_version() {
    if [ $1 -gt $COMMON_VERSION ]; then
        echo "Script expecting version $1 while common.sh is version $COMMON_VERSION. Abort." 1>&2
        exit 100
    fi

    if [ $1 -lt $COMMON_VERSION ]; then
        if [ -n "$DEBUG" ]; then
            echo "Warning: common.sh is version $COMMON_VERSION and script expects version $1." 1>&2
        fi
    fi
}

# Since COMMON_VERSION 3
# Generate temporary file
# Arguments 1:variable name where to store file name (optional) 2:template (optional) 3:path
# With template characters X are replaced with random (when using mktemp) or pseudorandom
# values (resort to bash).
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
