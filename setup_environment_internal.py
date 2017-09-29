#! /usr/bin/env python3

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
### Debug
###
DEBUG_SETUP_ENVIRONMENT = 'DEBUG_SETUP_ENVIRONMENT' in os.environ

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
    LOCAL_CONF.add(var, op, val)

def append_var(var, val, quote='"'):
    # quote is not currently used.  It's been kept in the function
    # prototype for backward compatibility
    LOCAL_CONF.add(var, '+=', val)

def remove_var(var):
    # Remove `var' from the configuration
    LOCAL_CONF.remove(var)

def reset_var(var, val, op='='):
    remove_var(var)
    set_var(var, val, op)

def append_layer(layer_dir):
    priority = get_layer_priority(layer_dir)
    data = BBLAYERS_CONF._simplify()
    layers = []
    for expr in data:
        if expr[0] == 'BBLAYERS':
            layers = expr[2]
            break
    layers.append(layer_dir)
    layers = [l.strip() for l in layers]
    layers = sorted(layers, key=get_layer_priority, reverse=True)
    BBLAYERS_CONF.remove('BBLAYERS')
    BBLAYERS_CONF.add('BBLAYERS', '+=', ' '.join(layers))

def append_layers(layer_dirs):
    for layer_dir in layer_dirs:
        append_layer(layer_dir)

def get_machines_by_layer(layer):
    layers = find_layers()
    if layer in layers.keys():
        machines_dir = os.path.join(layers[layer]['path'], 'conf', 'machine')
        machine_conf_files = []
        try:
            machine_conf_files = glob.glob(os.path.join(machines_dir, '*.conf'))
        except:
            raise Exception('Could not list machines for layer %s' % layer)
        return [ os.path.basename(os.path.splitext(f)[0]) \
                     for f in machine_conf_files ]
    else:
        raise Exception('Could not find layer %s' % layer)

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

def read_project_priority(mod):
    ''' Projects that are not proper Yocto Project layers can specify
    their priority in a setup-environment.d/priority file.  This is
    required because setup-environment requires hook scripts to have a
    priority setting, to execute them in a deterministic order.'''
    mod_dir = os.path.dirname(mod)
    priority_file = os.path.join(mod_dir, 'priority')
    priority = None
    try:
        priority = int(open(priority_file).readline().strip())
    except:
        debug('Could not determine priority for project %s' % os.path.dirname(mod_dir))
    return priority

def find_modules():
    ''' Return a list of modules.  Lower priority ones first. '''
    layers = find_layers()
    mod_dirs = system_find(os.path.join(PLATFORM_ROOT_DIR, "sources"),
                           maxdepth = 3,
                           type = 'd',
                           name = 'setup-environment.d')
    modules = []
    for dir in mod_dirs:
        modules += glob.glob(os.path.join(dir, "*.py"))

    ## Build up a dict mapping module paths to their priorities (None
    ## if no priority).  The priority is the layer priority.
    modules_with_priorities = []
    for mod in modules:
        for layer, layer_props in layers.items():
            layer_path = layer_props['path']
            debug('layer: %s, path: %s' % (layer, layer_path))
            layer_priority = layer_props['priority']
            ## Append a `/' to layer_path, to make it explicit that we
            ## are considering directories, otherwise we may risk
            ## ignoring layer directories whose basedir is a substring
            ## of other layers (e.g., .../foo and .../foobar)
            if mod.startswith(layer_path + '/'):
                modules_with_priorities.append((mod, layer_priority))
                break
        else:
            modules_with_priorities.append((mod, read_project_priority(mod)))

    ## Remove any module without priority from
    ## modules_with_priorities.  We allow only a single module without
    ## priority (usually a configuration repository which is not a
    ## proper Yocto Project layer -- i.e., no layer.conf)
    module_without_priority = None
    for mod, priority in modules_with_priorities[:]:
        if not priority:
            if module_without_priority:
                sys.stderr.write('ERROR: found more than one module without priority:\n')
                sys.stderr.write(' * %s\n' % module_without_priority)
                sys.stderr.write(' * %s\n' % mod)
                sys.exit(1)
            else:
                modules_with_priorities.remove((mod, priority))
                module_without_priority = mod

    ## Sort modules by layer priority
    modules_with_priorities = sorted(modules_with_priorities, key=lambda item: item[1])

    ## Append module_without_priority to modules_with_priorities, as
    ## the module without priority is considered to have the highest
    ## priority
    debug('modules_with_priorities: %s' % modules_with_priorities)
    debug('module_without_priority: %s' % module_without_priority)
    modules = [ m[0] for m in modules_with_priorities ]
    if module_without_priority:
        modules.append(module_without_priority)

    debug('modules in order: %s' % modules)
    return modules

def load_modules():
    for module in find_modules():
        with open(module) as module_source:
            exec(module_source.read())


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
        eula_file_path = os.path.join(PLATFORM_ROOT_DIR, 'sources', eula_file)

        if os.path.exists(eula_file_path):
            os.system('more -d "%s"' % eula_file_path)
            answer = None
            while not answer in ['y', 'Y', 'n', 'N']:
                print('Accept EULA (%s)? [y/n] ' % eula_file, end = '', flush = True)
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
                    print('Press ENTER to continue ', end = '', flush = True)
                    sys.stdin.readline()
                self._require_eula_acceptance(eula_file, eula_acceptance_expr)


###
### Configuration files handling
###
def parse_value(val):
    return split_keep_spaces(str(eval(val)))

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
            if char in ['=', '?', ':', '+', '.']:
                op += char
                if len(char) > 3:
                    raise Exception('Syntax error (operator): %s' % line)
            elif char == ' ':
                if not op in ['=', '+=', '=+', '?=', '??=', ':=', '.=', '=.']:
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
            rstripped_line = line.rstrip()
            if stripped_line.startswith('#') or stripped_line == '':
                linebuf = ''
                continue
            if rstripped_line.endswith('\\'):
                prev_line_continued = True
                linebuf += rstripped_line[:-1]
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
            lstripped_line = line.lstrip()
            if (lstripped_line.startswith('require') or
                lstripped_line.startswith('include')):
                continue
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
            self.conf_data.append((var, op, split_keep_spaces(str(val))))

    def remove(self, var):
        if not self.read_only:
            new_conf = []
            for expr in self.conf_data:
                if var != expr[0]:
                    new_conf.append(expr)
            self.conf_data = new_conf

def write_confs():
    LOCAL_CONF.write()
    BBLAYERS_CONF.write()

###
### Misc
###
def debug(msg):
    if DEBUG_SETUP_ENVIRONMENT:
        sys.stderr.write('DEBUG: ' + msg + '\n')

def count_leading_spaces(s):
    return len(s) - len(s.lstrip(' '))

def count_trailing_spaces(s):
    return len(s) - len(s.rstrip(' '))

def split_keep_spaces(s):
    lspaces = ' ' * count_leading_spaces(s)
    tspaces = ' ' * count_trailing_spaces(s)
    tokens = s.split()
    if tokens:
        if len(tokens) > 1:
            return ([lspaces + tokens[0]] +
                    tokens[1:-1] +
                    [tokens[-1] + tspaces])
        else:
            return [lspaces + tokens[0] + tspaces]
    else:
        return tokens

def system_find(basedir, maxdepth=None, type=None, expr=None, path=None, name=None):
    if path and name:
        raise Exception('path and name cannot be used together.')
    args = [basedir]
    if maxdepth:
        args += ['-maxdepth', str(maxdepth)]
    if type:
        args += ['-type', type]
    if expr:
        args += [expr]
    if path:
        args += ['-path', path]
    if name:
        args += ['-name', name]
    command = ["find"] + args
    proc = subprocess.Popen(command, stdout = subprocess.PIPE)
    ## Remove the trailing newlines
    return [ l[:-1].decode() for l in proc.stdout.readlines() ]

def get_layer_priority(layer_dir):
    conf_file = os.path.join(layer_dir, 'conf', 'layer.conf')
    c = Conf(conf_file, quiet=True)
    c.read_conf()
    priority = None
    for expr in c.conf_data:
        ## Although it's quite sloppy, let's consider a layer conf
        ## file will only set the priority for itself.  Just pick
        ## anything that starts with BBFILE_PRIORITY
        if expr[0].startswith('BBFILE_PRIORITY'):
            priority = int(expr[2][0])
    if priority is None:
        debug('Could not determine priority for layer (%s). Setting it as "1."' % conf_file)
        priority = 1
    return priority

def find_layers():
    ''' Return a dict mapping layer names to their paths '''
    layer_conf_paths = system_find(os.path.join(PLATFORM_ROOT_DIR, "sources"),
                                   maxdepth = 4,
                                   path = '*/conf/layer.conf')
    layers = {}
    for layer_conf_path in layer_conf_paths:
        layer_dir = os.path.dirname(os.path.dirname(layer_conf_path))
        layer = os.path.basename(layer_dir)
        layers[layer] = layer_dir

    # Determine priorities
    layers_with_priorities = {}
    for name, layer_dir in layers.items():
        priority = get_layer_priority(layer_dir)
        layers_with_priorities[name] = {'priority': priority,
                                        'path': layer_dir }
    return layers_with_priorities

def weak_set_var(var):
    # Use the environment as value or take the default, making it weak
    # in the local.conf
    try:
        val = os.environ[var]
    except:
        val = DEFAULTS[var]

    reset_var(var, val, op='?=')

def run_oe_init_build_env(build_dir, bitbake_dir):
    build_dir_path = os.path.join(PLATFORM_ROOT_DIR, build_dir)
    bitbake_dir_path = os.path.join(PLATFORM_ROOT_DIR, bitbake_dir)

    command = ['bash',
               '-c',
               'source %s/oe-init-build-env %s %s > /dev/null && env' % (OEROOT, build_dir_path, bitbake_dir_path)]
    proc = subprocess.Popen(command, stdout = subprocess.PIPE)
    # Update the current environment
    for line in proc.stdout.readlines():
        (var, _, val) = line.strip().decode().partition("=")
        os.environ[var] = val

    # Enable site.conf use
    for p in ['.oe', '.yocto']:
        source_site_conf = os.path.join(os.getenv('HOME'), p, 'site.conf')
        dest_site_conf = os.path.join(PLATFORM_ROOT_DIR, build_dir, 'conf', 'site.conf')
        if os.path.exists(source_site_conf):
            if os.path.exists(dest_site_conf) and not os.path.islink(dest_site_conf):
                print("WARNING: The conf/site.conf file is not a symlink, not touching it")
            elif os.path.islink(dest_site_conf):
                os.unlink(dest_site_conf)

            print("INFO: Linking %s to conf/site.conf" % source_site_conf)
            os.symlink(source_site_conf, dest_site_conf)
            break

def report_environment(env_file):
    env_fd = open(env_file, 'w')
    for var,val in os.environ.items():
        env_fd.write('%s=%s\n' % (var, val))
    env_fd.close()

###
### Parse command line and do stuff
###
if __name__ == '__main__':
    if os.getuid() == 0:
        print("ERROR: do not use the BSP as root. Exiting...")
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

    os.environ['PLATFORM_ROOT_DIR'] = PLATFORM_ROOT_DIR

    # Identify the OEROOT to use
    if os.path.exists(os.path.join(PLATFORM_ROOT_DIR, 'sources/oe-core')):
        OEROOT = os.path.join(PLATFORM_ROOT_DIR, 'sources/oe-core')
    elif os.path.exists(os.path.join(PLATFORM_ROOT_DIR, 'sources/openembedded-core')):
        OEROOT = os.path.join(PLATFORM_ROOT_DIR, 'sources/openembedded-core')
    elif os.path.exists(os.path.join(PLATFORM_ROOT_DIR, 'sources/poky')):
        OEROOT = os.path.join(PLATFORM_ROOT_DIR, 'sources/poky')
    else:
        sys.stderr.write("ERROR: Neither OE-Core or Poky could be found inside 'sources' directory.\n")
        sys.exit(1)

    os.environ['OEROOT'] = OEROOT

    # Identify BitBake directory
    if os.path.exists(os.path.join(PLATFORM_ROOT_DIR, 'sources/bitbake')):
        bitbake_dir = os.path.join(PLATFORM_ROOT_DIR, 'sources/bitbake')
    else:
        bitbake_dir = os.path.join(OEROOT, 'bitbake')

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

    run_hook('before-init')
    run_oe_init_build_env(build_dir, bitbake_dir)

    ## Now that run_oe_init_build_env has been run, we can actually
    ## read the configuration files
    LOCAL_CONF.read_conf()
    BBLAYERS_CONF.read_conf()

    ## Set some basic variables here, so that they can be overwritten by
    ## after-init scripts
    reset_var('PLATFORM_ROOT_DIR', PLATFORM_ROOT_DIR)

    weak_set_var('MACHINE')
    weak_set_var('SDKMACHINE')
    weak_set_var('DISTRO')
    weak_set_var('PACKAGE_CLASSES')

    run_hook('after-init')
    write_confs()

    eulas.handle()

    report_environment(env_file)
