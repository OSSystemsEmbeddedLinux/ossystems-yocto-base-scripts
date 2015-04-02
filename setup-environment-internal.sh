setupenv='sources/base/setup_environment_internal.py'
whitelistenv='sources/base/variable-whitelist.inc'

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
whitelisted_vars=
while read var; do
    if [ -z "$whitelisted_vars" ]; then
        whitelisted_vars=$var
    else
        whitelisted_vars="`echo -n $whitelisted_vars` $var"
    fi
    eval "[ -n \"\$$var\" ] && export $var || true"
done < $whitelistenv

export BB_ENV_EXTRAWHITE="$whitelisted_vars"

# File to which $setupenv will write the environment
env_file=`mktemp`

$setupenv $BUILDDIR $env_file || return $?

while read line; do
    variable=`echo $line | awk -F'=' '{ print $1; }'`
    if grep -w -q $variable $whitelistenv; then
        export "$line"
    fi
done < $env_file

# Support for ye's `cd' command:
[ -e sources/ye/ye-cd ] && . sources/ye/ye-cd

rm $env_file

cd $BUILDDIR
