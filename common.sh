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

COMMON_CONFIG_LOCATION="$HOME/.config/$(basename $0).config"

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

        if [ -z "$(eval echo \$$var)" ]; then
            if [ -z "$default" ]; then
                echo "$(basename $0): Configuration variable $var not defined, abort."
                exit 2
            else
                eval "$var=\"$default\""
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
