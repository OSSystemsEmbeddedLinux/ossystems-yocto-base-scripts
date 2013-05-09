setupenv='sources/base/setup-environment-internal.py'
whitelistenv='sources/base/variable-whitelist.inc'

if [ -z "$1" ] || [ -z "$MACHINE" ]; then
    # Force usage (exit error)
    $setupenv
    return 1
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    # Force usage (exit ok)
    $setupenv --help
    return 0
fi

# These variable are whitelisted in 'oe-buildenv-internal' so keep it
# in sync as it is know to affect the build setup
while read var; do
    export $var
done < $whitelistenv

env=`$setupenv $1`
ret=$?

if [ "$ret" != "0" ]; then
    echo "$env"
    return $ret
fi

# $setupenv prints as the last line the path to a temporary file which
# contains its environment settings
env=`echo $env | tail -n 1`

while read line; do
    variable=`echo $line | awk -F'=' '{ print $1; }'`
    if grep -w -q $variable $whitelistenv; then
        export $line
    fi
done < $env

rm $env

cd $BUILDDIR
