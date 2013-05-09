#! /usr/bin/env python

import os
import sys
import re
import glob
import tempfile
import subprocess

def usage(exit_code=None):
    message = 'Usage: MACHINE=<machine> %s <build dir>\n' % (os.path.basename(sys.argv[0]).replace('-internal.py', ''))
    if exit_code and exit_code != 0:
        sys.stderr.write(message)
    else:
        sys.stdout.write(message)
    if not exit_code is None:
        sys.exit(exit_code)

###
### Paths
###
PLATFORM_ROOT_DIR = os.getcwd()
OEROOT = None
LOCAL_CONF = None
BBLAYERS_CONF = None


###
### API to be used by modules
###
def set_var(var, val, op='=', quote='"'):
    set_in_oe_conf_file(LOCAL_CONF, var, val, op, quote)

def append_var(var, val, quote='"'):
    localconf = open(LOCAL_CONF, 'a')
    localconf.write('%s += %s%s%s\n' % (var, quote, val, quote))
    localconf.close()

def append_layers(layers):
    bblayers = open(BBLAYERS_CONF, 'a')
    bblayers.write('BBLAYERS += "\\\n')
    for layer in layers:
        bblayers.write('  %s \\\n' % (layer))
    bblayers.write('"\n')
    bblayers.close()


###
### Hooks & modules
###
HOOKS = { 'before-init': [],
          'after-init': [] }

def run_before_init(fn):
    HOOKS['before-init'].append(fn)

def run_after_init(fn):
    HOOKS['after-init'].append(fn)

def run_hook(hook):
    [ fn() for fn in HOOKS[hook] ]

def find_modules():
    modules = []
    maxdepth = 3
    command = ["find", os.path.join(PLATFORM_ROOT_DIR, "sources"), "-maxdepth", str(maxdepth), "-type", "d"]
    proc = subprocess.Popen(command, stdout = subprocess.PIPE)
    for dir in proc.stdout.readlines():
        dir = dir.strip()
        if os.path.basename(dir) == 'setup-environment.d':
            modules += (glob.glob(os.path.join(dir, "*.py")))
    return modules

def load_modules():
    for module in find_modules():
        execfile(module)


###
### Setting OE variables
###
def set_in_oe_conf_file(conf_file, var, val, op, quote):
    lines = open(conf_file).readlines()
    new_lines = []
    assignment_pattern = re.compile(' *%s *([\\?\\+:]*=) *[\'"]([^"]*)[\'"]' % (var))
    replaced = False
    for line in lines:
        m = assignment_pattern.match(line)
        if m:
            new_lines.append('%s %s %s%s%s\n' % (var, op or m.groups()[0], quote, val, quote))
            replaced = True
        else:
            # Clean up comments
            if line.strip() != '' and not line.strip().startswith('#'):
                new_lines.append(line)
    conf = open(conf_file, 'w')
    for line in new_lines:
        conf.write(line)
    if not replaced:
        conf.write('%s %s %s%s%s' % (var, op, quote, str(val), quote))
    conf.write('\n')
    conf.close()


###
### Misc
###
def maybe_set_envvar(var, val=None):
    try:
        os.environ[var]
    except:
        if val:
            os.environ[var] = val
        else:
            print "ERROR: %s not specified. Exiting..." % (var)
            sys.exit(1)


def run_oe_init_build_env(build_dir):
    os.chdir(OEROOT)
    command = ['bash',
               '-c',
               'source ./oe-init-build-env %s > /dev/null && env' % os.path.join(PLATFORM_ROOT_DIR, build_dir)]
    proc = subprocess.Popen(command, stdout = subprocess.PIPE)
    # Update the current environment
    for line in proc.stdout.readlines():
        (var, _, val) = line.strip().partition("=")
        os.environ[var] = val

def report_environment():
    tmpfd, tmpfname = tempfile.mkstemp()
    tmp = os.fdopen(tmpfd, 'w')
    for var,val in os.environ.items():
        tmp.write('%s=%s\n' % (var, val))
    tmp.close()
    print tmpfname

def number_of_cpus():
    ncpus = 0
    for line in open('/proc/cpuinfo').readlines():
        if line.startswith('processor'):
            ncpus += 1
    return ncpus

###
### Parse command line and do stuff
###
if os.getuid() == 0:
    print "ERROR: do not use the BSP as root. Exiting..."
    sys.exit(1)

if len(sys.argv) < 2:
    usage(1)

if sys.argv[1] in [ '--help', '-h' ]:
    usage(0)

build_dir = sys.argv[1]
LOCAL_CONF = os.path.join(PLATFORM_ROOT_DIR, build_dir, 'conf', 'local.conf')
BBLAYERS_CONF = os.path.join(PLATFORM_ROOT_DIR, build_dir, 'conf', 'bblayers.conf')

maybe_set_envvar('MACHINE')
maybe_set_envvar('SDKMACHINE', 'i686')
maybe_set_envvar('DISTRO', 'poky')

if os.path.exists('sources/oe-core'):
    OEROOT = 'sources/oe-core'
else:
    OEROOT = 'sources/poky'

os.environ['OEROOT'] = OEROOT
os.environ['PLATFORM_ROOT_DIR'] = PLATFORM_ROOT_DIR

if os.path.exists(LOCAL_CONF) or os.path.exists(BBLAYERS_CONF):
    print "%s or %s exits.  Not overwriting them." % (LOCAL_CONF, BBLAYERS_CONF)
    sys.exit(1)
else:
    run_hook('before-init')
    run_oe_init_build_env(build_dir)

load_modules()

## Set some basic variables here, so that they can be overwritten by
## after-init scripts
ncpus = number_of_cpus()
set_var('BB_NUMBER_THREADS', ncpus)
set_var('PARALLEL_MAKE', '-j %s' % (ncpus))
set_var('PLATFORM_ROOT_DIR', PLATFORM_ROOT_DIR)
set_var('MACHINE', os.environ['MACHINE'], op='?=')
set_var('SDKMACHINE', os.environ['SDKMACHINE'], op='?=')
set_var('DISTRO', os.environ['DISTRO'], op='?=')

run_hook('after-init')
report_environment()
