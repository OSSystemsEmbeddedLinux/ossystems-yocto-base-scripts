setupenv='sources/base/setup_environment_internal.py'
passthrough_env='sources/base/variable-passthrough.inc'

if [ -z "$1" ]; then
    # Force usage (exit error)
    $setupenv
    return 1
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    # Force usage (exit ok)
    $setupenv --help
    return 0
fi

BUILDDIR="`pwd`/$1"

# These variable are whitelisted in 'oe-buildenv-internal' so keep it
# in sync as it is know to affect the build setup
passthrough_env_additions=
while read var; do
    if [ -z "$passthrough_env_additions" ]; then
        passthrough_env_additions=$var
    else
        passthrough_env_additions="`echo -n $passthrough_env_additions` $var"
    fi
    eval "[ -n \"\$$var\" ] && export $var || true"
done < $passthrough_env

export BB_ENV_PASSTHROUGH_ADDITIONS="$BB_ENV_PASSTHROUGH_ADDITIONS $passthrough_env_additions"

# File to which $setupenv will write the environment
env_file=`mktemp`

$setupenv $BUILDDIR $env_file || return $?

while read line; do
    variable=`echo $line | awk -F'=' '{ print $1; }'`
    if grep -w -q $variable $passthrough_env; then
        export "$line"
    fi
done < $env_file

# Support for ye's `cd' command:
[ -e sources/ye/ye-cd ] && . sources/ye/ye-cd

# Enable ye autocompletion
if [ -e sources/ye/ye-completion.sh ]; then
    # Load bash completion module for ZSH
    [[ -n $ZSH_VERSION ]] && autoload bashcompinit && bashcompinit

    . sources/ye/ye-completion.sh
fi

rm $env_file

cd $BUILDDIR
