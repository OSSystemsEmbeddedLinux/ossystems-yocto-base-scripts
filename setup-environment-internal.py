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

LOCAL_CONF_EXISTS = None
BBLAYERS_CONF_EXISTS = None

###
### API to be used by modules
###
def set_default(var, val):
    DEFAULTS[var] = val

def set_var(var, val, op='=', quote='"'):
    os.environ[var] = str(val)
    if not LOCAL_CONF_EXISTS:
        set_in_oe_conf_file(LOCAL_CONF, var, val, op, quote)

def append_var(var, val, quote='"'):
    if not LOCAL_CONF_EXISTS:
        # First try to determine the current values for the given variable
        assignment_pattern = variable_assignment_pattern(var)
        current_values = []
        lines = open(LOCAL_CONF).readlines()
        for line in lines:
            m = assignment_pattern.match(line)
            if m:
                current_values.append(m.groups()[1])

        # Don't do anything if the given value is in the set of values
        # bound to the given variable
        if val in current_values:
            return
        else:
            # Append the given value the given variable
            localconf = open(LOCAL_CONF, 'a')
            localconf.write('%s += %s%s%s\n' % (var, quote, val, quote))
            localconf.close()

def append_layers(layers):
    if not BBLAYERS_CONF_EXISTS:
        bblayers = open(BBLAYERS_CONF, 'a')
        bblayers.write('BBLAYERS += "\\\n')
        for layer in layers:
            bblayers.write('  %s \\\n' % (layer))
        bblayers.write('"\n')
        bblayers.close()


###
### Hooks & modules
###
HOOKS = { 'set-defaults': [],
          'before-init': [],
          'after-init': [] }

DEFAULTS = { 'DISTRO': 'poky',
             'SDKMACHINE': 'i686',
             'PACKAGE_CLASSES': 'package_ipk' }

def run_set_defaults(fn):
    HOOKS['set-defaults'].append(fn)

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
    assignment_pattern = variable_assignment_pattern(var)
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
### EULAs
###
class eulas():
    accept = {}


def set_eula_accepted(acceptance_expr):
    conf = open(LOCAL_CONF, 'a')
    conf.write(acceptance_expr + '\n')
    conf.close()


def require_eula_acceptance(eula_file, acceptance_expr):
    ## The current directory is the poky layer root directory, so
    ## we prepend ../ to the eula file path
    eula_file_path = os.path.join('..', eula_file)

    if os.path.exists(eula_file_path):
        print(
            '==========================================================================\n'
            '=== Some SoC depends on libraries and packages that requires accepting ===\n' +
            '=== an EULA. To have the right to use those binaries in your images    ===\n' +
            '=== you need to read and accept the EULA that will be displayed.       ===\n' +
            '==========================================================================\n\n')
        os.system('more -d "%s"' % eula_file_path)
        answer = None
        while not answer in ['y', 'Y', 'n', 'N']:
            sys.stderr.write('Accept EULA? [y/n] ')
            answer = sys.stdin.readline().strip()
        if answer in ['y', 'Y']:
            set_eula_accepted(acceptance_expr)
    else:
        sys.stderr.write('%s does not exist. Aborting.\n' % (eula_file))
        sys.exit(1)


def handle_eulas():
    accepted_eulas = []
    try:
        accepted_eulas = os.environ['ACCEPTED_EULAS'].split()
    except:
        pass

    for eula_file, eula_acceptance_expr in eulas.accept.items():
        if eula_file in accepted_eulas:
            ## If EULA has been accepted via the environment, set it
            ## accepted without displaying the EULA text
            acceptance_expr = eulas.accept[eula_file]
            set_eula_accepted(acceptance_expr)
        else:
            ## Prompt for EULAs acceptance based on settings in hook scripts
            require_eula_acceptance(eula_file, eula_acceptance_expr)


###
### Misc
###
def variable_assignment_pattern(var):
    return re.compile(' *%s *([\\?\\+:]*=) *[\'"]([^"]*)[\'"]' % (var))


def maybe_set_envvar(var, val=None):
    # Only set the given environment variable if it is not set in the
    # current environment and if `val' is not None.
    try:
        os.environ[var]
    except:
        if val:
            os.environ[var] = val

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

    # Enable site.conf use
    for p in ['.oe', '.yocto']:
        source_site_conf = os.path.join(os.getenv('HOME'), p, 'site.conf')
        dest_site_conf = os.path.join(PLATFORM_ROOT_DIR, build_dir, 'conf', 'site.conf')
        if os.path.exists(source_site_conf):
            if os.path.exists(dest_site_conf) and not os.path.islink(dest_site_conf):
                print "WARNING: The conf/site.conf file is not a symlink, not touching it"
            elif os.path.islink(dest_site_conf):
                os.unlink(dest_site_conf)

            print "INFO: Linking %s to conf/site.conf" % source_site_conf
            os.symlink(source_site_conf, dest_site_conf)
            break

def report_environment(env_file):
    env_fd = open(env_file, 'w')
    for var,val in os.environ.items():
        env_fd.write('%s=%s\n' % (var, val))
    env_fd.close()

def number_of_cpus():
   # Python 2.6+
    try:
        import multiprocessing
        return multiprocessing.cpu_count()
    except (ImportError, NotImplementedError):
        print "WARNING: Failed to identify the number of CPUs, falling back to 1."
        return 1

###
### Parse command line and do stuff
###
if os.getuid() == 0:
    print "ERROR: do not use the BSP as root. Exiting..."
    sys.exit(1)

if len(sys.argv) < 3:
    usage(1)

if sys.argv[1] in [ '--help', '-h' ]:
    usage(0)

build_dir = sys.argv[1]
env_file = sys.argv[2] # file where the environment will be reported to

# Check if env_file really exists, just in case.
if not os.path.exists(env_file):
    sys.stderr.write('env file (%s) does not exist.  Aborting.\n' % env_file)

LOCAL_CONF = os.path.join(PLATFORM_ROOT_DIR, build_dir, 'conf', 'local.conf')
BBLAYERS_CONF = os.path.join(PLATFORM_ROOT_DIR, build_dir, 'conf', 'bblayers.conf')

LOCAL_CONF_EXISTS = os.path.exists(LOCAL_CONF)
BBLAYERS_CONF_EXISTS = os.path.exists(BBLAYERS_CONF)

maybe_set_envvar('MACHINE')

if os.path.exists('sources/oe-core'):
    OEROOT = 'sources/oe-core'
else:
    OEROOT = 'sources/poky'

os.environ['OEROOT'] = OEROOT
os.environ['PLATFORM_ROOT_DIR'] = PLATFORM_ROOT_DIR

if os.path.exists(LOCAL_CONF) or os.path.exists(BBLAYERS_CONF):
    sys.stderr.write("WARNING: %s or %s exits.  Not overwriting them.\n" % (LOCAL_CONF, BBLAYERS_CONF))

load_modules()

run_hook('set-defaults')

maybe_set_envvar('DISTRO', DEFAULTS['DISTRO'])
maybe_set_envvar('SDKMACHINE', DEFAULTS['SDKMACHINE'])
maybe_set_envvar('PACKAGE_CLASSES', DEFAULTS['PACKAGE_CLASSES'])

run_hook('before-init')
run_oe_init_build_env(build_dir)

## Set some basic variables here, so that they can be overwritten by
## after-init scripts
ncpus = number_of_cpus()
machine = None
try:
    machine = os.environ['MACHINE']
except:
    pass
set_var('BB_NUMBER_THREADS', ncpus)
set_var('PARALLEL_MAKE', '-j %s' % (ncpus))
set_var('PLATFORM_ROOT_DIR', PLATFORM_ROOT_DIR)
if machine:
    set_var('MACHINE', machine, op='?=')
set_var('SDKMACHINE', os.environ['SDKMACHINE'], op='?=')
set_var('DISTRO', os.environ['DISTRO'], op='?=')
set_var('PACKAGE_CLASSES', os.environ['PACKAGE_CLASSES'], op='?=')

run_hook('after-init')

handle_eulas()

report_environment(env_file)
