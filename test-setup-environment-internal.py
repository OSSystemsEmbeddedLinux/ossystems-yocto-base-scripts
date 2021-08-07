from setup_environment_internal import *

import os
import pprint

pp = pprint.pprint

## Some cleanup
files_to_remove = ['test-data/conf2']
for f in files_to_remove:
    if os.path.exists(f):
        os.remove(f)


def get_var(v, conf):
    for var, op, val in conf.conf_data:
        if var == v:
            return val
    return None


##
## Read-only test
##
conf1 = Conf('test-data/conf1', quiet=True)
conf1.read_conf()
assert conf1.conf_data == [('BB_NUMBER_THREADS', '=', ['8']),
                           ('PARALLEL_MAKE', '=', ['-j', '8']),
                           ('PLATFORM_ROOT_DIR', '=', ['/home/mario/src/ossystems-yocto-platform/dora']),
                           ('MACHINE', '?=', ['wandboard-solo']),
                           ('SDKMACHINE', '?=', ['x86_64']),
                           ('DISTRO', '?=', ['oel']),
                           ('PACKAGE_CLASSES', '?=', ['package_ipk']),
                           ('ACCEPT_OSS_EULA', '=', ['1']),
                           ('MULTILINE', '=', ['foo', 'bar', 'baz             ']),
                           ('EMPTY' , '=', []),
                           ('APPEND_append', '=', [' foo']),
                           ('PREPEND_prepend', '=', [' bar  ']),
                           ('APPEND:append', '=', [' foo']),
                           ('PREPEND:prepend', '=', [' bar  ']),
                           ('BBFILES', '+=', ['${@bb.utils.contains("VAR",', '"",', '"",', '"",', 'd)}'])]


## Since test-data/conf1 exists, conf1 is created as read-only
conf1.add('FOO', '=', 'a foo')
assert get_var('FOO', conf1) == None


###
### Read-write test
###
conf2 = Conf('test-data/conf2', quiet=True)

conf2.add('FOO', '=', 'a foo')
assert get_var('FOO', conf2) == ['a', 'foo']

conf2.add('MULTI', '=', 'foo bar baz')
assert get_var('MULTI', conf2) == ['foo', 'bar', 'baz']

conf2.add('EMPTY', '=', '')
assert get_var('EMPTY', conf2) == []

conf2.add('APPEND_append', '=', ' foo bar')
assert get_var('APPEND_append', conf2) == [' foo', 'bar']

conf2.add('PREPEND_prepend', '=', ' xxx yyy  ')
assert get_var('PREPEND_prepend', conf2) == [' xxx', 'yyy  ']

conf2.write()

assert os.path.exists('test-data/conf2')

## Check if we can read what we write
conf2_check = Conf('test-data/conf2', quiet=True)
conf2_check.read_conf()
assert conf2_check.conf_data == [('FOO', '=', ['a', 'foo']),
                                 ('MULTI', '=', ['foo', 'bar', 'baz']),
                                 ('EMPTY', '=', []),
                                 ('APPEND_append', '=', [' foo', 'bar']),
                                 ('PREPEND_prepend', '=', [' xxx', 'yyy  '])]

print('All fine!')
