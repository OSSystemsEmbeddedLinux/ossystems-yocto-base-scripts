#! /usr/bin/env python

import os
import re
import sys
import glob
import pipes
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

###
### Configuration files data
###
LOCAL_CONF = None
BBLAYERS_CONF = None

###
### API to be used by modules
###
def set_default(var, val):
    DEFAULTS[var] = val

def set_var(var, val, op='=', quote='"'):
    # quote is not currently used.  It's been kept in the function
    # prototype for backward compatibility
    os.environ[var] = str(val)
    LOCAL_CONF.add(var, op, val)

def append_var(var, val, quote='"'):
    # quote is not currently used.  It's been kept in the function
    # prototype for backward compatibility
    LOCAL_CONF.add(var, '+=', val)

def append_layers(layers):
    BBLAYERS_CONF.add('BBLAYERS', '+=', ' '.join(layers))


###
### Hooks & modules
###
HOOKS = { 'set-defaults': [],
          'before-init': [],
          'after-init': [] }

DEFAULTS = { 'DISTRO': 'poky',
             'MACHINE': 'qemuarm',
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
### EULAs
###
class Eula():
    def __init__(self, local_conf_file):
        self.accept = {}
        self.local_conf_file = local_conf_file

    def _set_eula_accepted(self, acceptance_expr):
        conf = open(self.local_conf_file, 'a')
        conf.write(acceptance_expr + '\n')
        conf.close()

    def _require_eula_acceptance(self, eula_file, acceptance_expr):
        ## The current directory is the poky layer root directory, so
        ## we prepend ../ to the eula file path
        eula_file_path = os.path.join('..', eula_file)

        if os.path.exists(eula_file_path):
            os.system('more -d "%s"' % eula_file_path)
            answer = None
            while not answer in ['y', 'Y', 'n', 'N']:
                sys.stdout.write('Accept EULA (%s)? [y/n] ' % eula_file)
                answer = sys.stdin.readline().strip()
            if answer in ['y', 'Y']:
                self._set_eula_accepted(acceptance_expr)
        else:
            sys.stderr.write('%s does not exist. Aborting.\n' % (eula_file))
            sys.exit(1)


    def _local_conf_accepted_eulas(self):
        "Return a list of accepted EULAS (indicated by the EULA file) in local.conf"
        eula_files = []
        local_conf = Conf(self.local_conf_file, quiet=True)
        local_conf.read_conf()
        local_conf_data = local_conf.conf_data
        for eula_file, acceptance_expr in eulas.accept.items():
            ae_var = ae_op = ae_val = None
            try:
                ae_var, ae_op, ae_val = parse_assignment_expr(acceptance_expr)
            except:
                pass
            if ae_var:
                for lc_var, lc_op, lc_val in local_conf_data:
                    ## We ignore the operator when comparing
                    ## acceptance expressions.  We probably shouldn't.
                    if lc_var == ae_var and lc_val == ae_val:
                        eula_files.append(eula_file)
                        break
        return eula_files

    def handle(self):
        accepted_eulas = []
        try:
            accepted_eulas = os.environ['ACCEPTED_EULAS'].split()
        except:
            pass

        already_accepted_eulas = self._local_conf_accepted_eulas()
        show_eula_banner = True

        for eula_file, eula_acceptance_expr in eulas.accept.items():
            if eula_file in already_accepted_eulas:
                ## EULA has been set as accepted in local.conf, so just
                ## ignore it
                pass
            elif eula_file in accepted_eulas:
                ## If EULA has been accepted via the environment, set it
                ## accepted without displaying the EULA text
                acceptance_expr = eulas.accept[eula_file]
                self._set_eula_accepted(acceptance_expr)
            else:
                ## Prompt for EULAs acceptance based on settings in hook scripts
                if show_eula_banner:
                    show_eula_banner = False # show banner only once
                    print(
                        '\n\n==========================================================================\n'
                        '=== Some SoC depends on libraries and packages that requires accepting ===\n' +
                        '=== EULA(s). To have the right to use those binaries in your images    ===\n' +
                        '=== you need to read and accept the EULA(s) that will be displayed.    ===\n' +
                        '==========================================================================\n\n')
                    sys.stdout.write('Press ENTER to continue')
                    sys.stdin.readline()
                self._require_eula_acceptance(eula_file, eula_acceptance_expr)


###
### Configuration files handling
###
def parse_value(val):
    return eval(val).split()

def parse_assignment_expr(line):
    var = ''
    op = ''
    val = ''
    looking_for = 'var'
    line = line.strip()
    for pos, char in enumerate(line):
        if looking_for == 'var':
            if char not in ['=', '?', ':', '+']:
                if char == ' ':
                    looking_for = 'op'
                else:
                    var += char
            else:
                looking_for = 'op'
        elif looking_for == 'op':
            if char in ['=', '?', ':', '+']:
                op += char
                if len(char) > 3:
                    raise Exception('Syntax error (operator): %s' % line)
            elif char == ' ':
                if not op in ['=', '+=', '=+', '?=', '??=', ':=']:
                    raise Exception('Invalid operator: %s' % op)
                looking_for = 'val'
            else:
                raise Exception('Syntax error (operator): %s' % line)
        else:
            val = line[pos:]
            break
    if var and op and val:
        return (var, op, parse_value(val))
    else:
        return None # Not an assignment line

def format_value(val):
    escaped = pipes.quote(' '.join(map(str, val)))
    ## pipe.quote doesn't seem to actually quote the given argument,
    ## unless it's necessary.  We want arguments to be always quoted.
    if not escaped.startswith("'"):
        escaped = "'%s'" % escaped
    if len(escaped) > 65:
        lines = escaped.split()
        if len(lines) < 2:
            return escaped
        indent = ' ' * 4
        lines[0] = lines[0][1:] # remove initial quote
        lines[-1] = lines[-1][:-1] # remove end quote
        fmt_val = "'\\\n"
        for line in lines:
            fmt_val += indent + line + ' \\\n'
        fmt_val += "'"
        return fmt_val
    else:
        return escaped


class Conf(object):
    def __init__(self, conf_file, quiet=False):
        self.conf_file = conf_file
        self.read_only = os.path.exists(conf_file)
        if self.read_only and not quiet:
            sys.stderr.write("WARNING: %s exists.  Not overwriting it.\n" % conf_file)
        self.conf_data = []

    def _read_conf(self):
        lines = open(self.conf_file).readlines()
        content = []
        linebuf = ''
        for line in lines:
            stripped_line = line.strip()
            if stripped_line.startswith('#') or stripped_line == '':
                linebuf = ''
                continue
            if line.endswith('\\\n'):
                prev_line_continued = True
                linebuf += line[:-2]
                continue
            if linebuf:
                linebuf += line
                content.append(linebuf)
            else:
                content.append(line)
            linebuf = ''
        return(content)

    def _parse_conf(self, lines):
        assignments = []
        for line in lines:
            expr = parse_assignment_expr(line)
            if expr:
                assignments.append(expr)
        return assignments

    def _simplify(self):
        ## Squash multiple values for sequential assignment
        ## expressions which envolve the same variable and operator is
        ## '+='.  So:
        ##     foo += 'bar'
        ##     foo += 'baz'
        ## is turned into:
        ##     foo += 'bar baz'
        simpl_data = []
        for expr in self.conf_data:
            if simpl_data:
                prev_var, prev_op, prev_val = simpl_data[-1]
                if prev_var == expr[0] and prev_op == '+=' and prev_op == expr[1]:
                    simpl_data[-1] = (prev_var, prev_op, prev_val + expr[2])
                    continue
            simpl_data.append(expr)
        return simpl_data


    def read_conf(self):
        self.conf_data = self._parse_conf(self._read_conf())


    def write(self):
        if not self.read_only:
            conf_fd = open(self.conf_file, 'w')
            for var, op, val in self._simplify():
                conf_fd.write('%s %s %s\n' % (var, op, format_value(val)))
            conf_fd.close()

    def add(self, var, op, val):
        if not self.read_only:
            self.conf_data.append((var, op, str(val).split()))

def write_confs():
    LOCAL_CONF.write()
    BBLAYERS_CONF.write()

###
### Misc
###
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
if __name__ == '__main__':
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

    maybe_set_envvar('MACHINE', DEFAULTS['MACHINE'])

    if os.path.exists('sources/oe-core'):
        OEROOT = 'sources/oe-core'
    else:
        OEROOT = 'sources/poky'

    os.environ['OEROOT'] = OEROOT
    os.environ['PLATFORM_ROOT_DIR'] = PLATFORM_ROOT_DIR

    local_conf_file = os.path.join(PLATFORM_ROOT_DIR, build_dir, 'conf', 'local.conf')
    bblayers_conf_file = os.path.join(PLATFORM_ROOT_DIR, build_dir, 'conf', 'bblayers.conf')

    ## Create the configuration objects here, before loading modules
    ## and before running run_oe_init_build_env, but don't try to read
    ## the configuration files yet.
    LOCAL_CONF = Conf(local_conf_file)
    BBLAYERS_CONF = Conf(bblayers_conf_file)

    ## Create the eula object here, so hook scripts can add stuff to
    ## eulas.accept
    eulas = Eula(local_conf_file)

    ## Load all the hook scripts
    load_modules()

    run_hook('set-defaults')

    maybe_set_envvar('DISTRO', DEFAULTS['DISTRO'])
    maybe_set_envvar('SDKMACHINE', DEFAULTS['SDKMACHINE'])
    maybe_set_envvar('PACKAGE_CLASSES', DEFAULTS['PACKAGE_CLASSES'])

    run_hook('before-init')
    run_oe_init_build_env(build_dir)

    ## Now that run_oe_init_build_env has been run, we can actually
    ## read the configuration files
    LOCAL_CONF.read_conf()
    BBLAYERS_CONF.read_conf()

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
    write_confs()

    eulas.handle()

    report_environment(env_file)
