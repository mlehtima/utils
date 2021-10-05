#!/usr/bin/env python3

import dbus
import dbus.service
import dbus.mainloop.glib
import os
import sys
import distutils.spawn
from subprocess import Popen, PIPE, STDOUT
import configparser
import io
from gi.repository import GLib

SERVER_PATH="/org/sailfish/sdkrun"
SERVER_NAME="org.sailfish.sdkrun"

TARGET_ARG="-t"
BACKGROUND_ARG="--bg"
FOLLOW_ARG="--follow"

STATE_CREATED   = 0
STATE_STARTING  = 1
STATE_CANCEL    = 2
STATE_RUNNING   = 3
STATE_DONE      = 4
STATE_FAIL      = 5

LOG_STR = dict()
LOG_STR[STATE_CREATED]  = "{0}"
LOG_STR[STATE_STARTING] = "{0}"
LOG_STR[STATE_CANCEL]   = "\x1b[33m{0}\x1b[39m"
LOG_STR[STATE_RUNNING]  = "\x1b[94m{0}\x1b[39m"
LOG_STR[STATE_DONE]     = "\x1b[32m{0}\x1b[39m"
LOG_STR[STATE_FAIL]     = "\x1b[31m{0}\x1b[39m"

PAGER_GUI               = [ "gvim", "-" ]
PAGER_CLI               = [ "less", "-N" ]

def state_str(state):
    if state == STATE_CREATED:
        return "CREATED"
    elif state == STATE_STARTING:
        return "STARTING"
    elif state == STATE_CANCEL:
        return "CANCEL"
    elif state == STATE_RUNNING:
        return "RUNNING"
    elif state == STATE_DONE:
        return "DONE"
    elif state == STATE_FAIL:
        return "FAIL"
    return "UNKNOWN"

def state_short_str(state):
    if state == STATE_CREATED:
        return "-"
    elif state == STATE_STARTING:
        return "s"
    elif state == STATE_CANCEL:
        return "c"
    elif state == STATE_RUNNING:
        return "*"
    elif state == STATE_DONE:
        return "d"
    elif state == STATE_FAIL:
        return "f"
    return "UNKNOWN"

def log_err(msg, exit=True, code=1):
    sys.stderr.write("{}\n".format(msg))
    sys.stderr.flush()
    if exit:
        sys.exit(code)

def sdk_method(method_name):
    bus = dbus.SessionBus()
    try:
        service = bus.get_object(SERVER_NAME, SERVER_PATH)
    except dbus.exceptions.DBusException as e:
        print("Cannot reach server: {}".format(e))
        sys.exit(255)
    return service.get_dbus_method(method_name, SERVER_NAME)

def quit():
    sdk_method("Quit")()

def set_debug(enabled):
    s = False
    if enabled:
        s = True
    sdk_method("Debug")(s)

def print_tasks(monitor=False):
    tasks = sdk_method("Tasks")()
    if monitor:
        # not best but shortest solution for now
        os.system("clear")
    if len(tasks) > 0:
        print("\x1b[30;107m{0:6s}\x1b[39;49m \x1b[30;107m{1:12s}\x1b[39;49m \x1b[30;107m{2:24s}\x1b[39;49m".format("[id/s]", "[path]", "[cmdline]"))
        for idno, state, full_path, cmd, ret, duration in tasks:
            run_path = ''.join(full_path.split("/")[-1:])
            if len(run_path) > 12:
                run_path = ".." + run_path[-10:]
            line = "{0:3d} {1:<2s} {2:12s} {3:s}".format(idno, state_short_str(state), run_path, cmd)
            print(LOG_STR[state].format(line))
    elif monitor:
        print("No tasks.")

class TaskMonitor():
    def __init__(self):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        bus = dbus.SessionBus()
        bus.add_signal_receiver(TaskMonitor.task_handler,
                                dbus_interface=SERVER_NAME,
                                signal_name="TaskStateChanged")
        self.mainloop = GLib.MainLoop()

    def run(self):
        print_tasks(True)
        try:
            self.mainloop.run()
        except KeyboardInterrupt as e:
            self.mainloop.quit()

    @staticmethod
    def task_handler(new_state, task_id, task_pwd, task_cmd, duration):
        print_tasks(True)

def monitor_tasks():
    TaskMonitor().run()

class TaskFollower(dbus.service.Object):
    IFACE   = "org.sailfish.sdk.client"
    PATH    = "/org/sailfish/sdk/client"
    def __init__(self, idno):
        self._name = "org.sailfish.sdk.client{}".format(os.getpid())
        self._idno = int(idno)
        self._retno = 0
        self._running = False
        pass

    def _m(self, method_name):
        bus = dbus.SessionBus()
        service = bus.get_object(SERVER_NAME, SERVER_PATH)
        return service.get_dbus_method(method_name, SERVER_NAME)

    def _register_follower(self):
        if self._m("FollowTask")(self._idno, self._name.get_name()):
            self._running = True
        else:
            log_err("No task with id {}.".format(self._idno), exit=False)
            self._retno = 1
            self._loop.quit()

    def quit(self):
        if self._running:
            self._m("UnfollowTask")(self._idno, self._name.get_name())
        self._loop.quit()

    def run(self):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self._loop = GLib.MainLoop.new(None, False)
        bus_name = dbus.service.BusName(self._name, dbus.SessionBus())
        dbus.service.Object.__init__(self, bus_name, self.PATH)
        GLib.idle_add(self._register_follower)
        try:
            self._loop.run()
        except KeyboardInterrupt as e:
            self.quit()

    def retno(self):
        return self._retno

    @dbus.service.method(IFACE, in_signature='i', out_signature='')
    def Quit(self, returncode):
        self._retno = int(returncode)
        self._loop.quit()

    @dbus.service.method(IFACE, in_signature='s', out_signature='')
    def Write(self, line):
        sys.stdout.write(line)
        sys.stdout.flush()

# This is stupid workaround, but couldn't figure out how to get
# mainloop running again for the TaskFollower.
def follow_task_hack_execlp(idno):
    os.execlp("dk-tasks", "dk-tasks", "--follow-hack", str(idno))

def follow_task_hack(idno):
    t = TaskFollower(idno)
    t.run()
    sys.exit(t.retno())

def follow_task(idno):
    if idno > 0:
        idn, state, full_path, cmd, ret, duration = sdk_method("Task")(idno)
        if idn < 0:
            log_err("No task with id {} found.".format(idno))
        if state != STATE_RUNNING:
            log_err("Task {0} [{1}] already done with return code {2}.".format(idn, cmd, ret), code=0)
    else:
        tasks = sdk_method("Tasks")()
        for idn, state, full_path, cmd, ret, duration in tasks:
            if state == STATE_RUNNING and idn > idno:
                idno = idn
        if idno == 0:
            log_err("No running tasks found.")
    follow_task_hack_execlp(idno)

def latest_task_id(idno):
    if idno < 0:
        tasks = sdk_method("Tasks")()
        for idn, state, full_path, cmd, ret, duration in tasks:
            if idn > idno:
                idno = idn
    return idno

def log(idno):
    idno = latest_task_id(idno)
    found, text = sdk_method("Log")(idno)
    if found:
        sys.stdout.write(text)
        sys.stdout.flush()
    else:
        log_err("No task with id {}.".format(idno))

def lastlog():
    idno = latest_task_id(-1)
    found, text = sdk_method("Log")(idno)
    if found:
        if sys.stdin.isatty():
            args = PAGER_CLI
        else:
            args = PAGER_GUI
        p = Popen(args, stdin=PIPE, close_fds=True)
        ret = p.communicate(input=text.encode())

def cancel(idno):
    idno = latest_task_id(idno)
    if idno > 0:
        sdk_method("CancelTask")(idno)

def repeat(idno):
    sdk_method("Repeat")(idno)

def reset_task_ids():
    sdk_method("Reset")()

def run_cmd(pwd, cmd, background=False):
    follow = follow_created_task(cmd)
    r = sdk_method("AddTask")(pwd, cmd, background)
    if r > 0 and follow:
        follow_task_hack_execlp(r)

def get_default_target():
    default = None
    config = configparser.ConfigParser()
    try:
        with open(os.path.expanduser("~/.scratchbox2/config")) as stream:
            stream = io.StringIO("[default]\n" + stream.read())
            config.read_file(stream)
        default = config.get("default", "DEFAULT_TARGET")
    except IOError:
        pass
    return default

def is_background(cmd):
    if BACKGROUND_ARG in cmd:
        cmd.remove(BACKGROUND_ARG)
        return True
    return False

def follow_created_task(cmd):
    if FOLLOW_ARG in cmd:
        cmd.remove(FOLLOW_ARG)
        return True
    return False

def apply_default(cmd, final):
    use_default = True
    if TARGET_ARG in cmd:
        i = cmd.index(TARGET_ARG)
        if len(cmd) >= i + 2:
            cmd.pop(i)
            final.extend([TARGET_ARG, cmd[i]])
            cmd.pop(i)
            use_default = False
    if use_default:
        default = get_default_target()
        if default:
            final.extend([TARGET_ARG, default])

def run_target_cmd(pwd, exe, cmd):
    final = [exe]
    bg = is_background(cmd)
    apply_default(cmd, final)
    final.extend(cmd)
    run_cmd(pwd, final, bg)

def run_sdk_install(pwd, cmd):
    final = ['sb2']
    bg = is_background(cmd)
    apply_default(cmd, final)
    final.extend(['-m', 'sdk-install', '-R'])
    final.extend(cmd)
    run_cmd(pwd, final, bg)

def set_default_target(name):
    cmd = ['sb2-config', '-d', name]
    run_cmd(os.path.expanduser("~"), cmd)

def cancel_all():
    sdk_method("CancelAll")()

def sb2_targets(ignore=None):
    targets = []
    sb2 = os.path.expanduser("~/.scratchbox2")
    files = os.listdir(sb2)
    for f in files:
        if os.path.isdir(os.path.join(sb2, f)):
            if ignore and ignore == f:
                continue
            targets.append(f)
    return targets

def sb2_default_target():
    if not distutils.spawn.find_executable("dmenu"):
        print(get_default_target())
        sys.exit(0)

    default_target = get_default_target()
    targets = sb2_targets(ignore=default_target)
    targets.sort()
    if default_target:
        targets.insert(0, default_target)
    if len(targets) > 0:
        p = Popen(["dmenu", "-fn", "Droid Sans Mono-17", "-p", "set default sb2 target:"], stdin=PIPE, stdout=PIPE, stderr=STDOUT)
        ret = p.communicate(input="\n".join(targets).encode())[0]
        if ret:
            set_default_target(ret.decode().split("\n")[0])

def sys_args1(*argv):
    if len(sys.argv) > 1:
        for arg in argv:
            if arg == sys.argv[1]:
                return True
    return False

def sys_int_val(pos, default=None):
    r = True
    if len(sys.argv) <= pos:
        if default is None:
            r = False
        else:
            i = default
    else:
        try:
            i = int(sys.argv[pos])
        except ValueError as e:
            r = False

    if not r:
        log_err("Integer argument required.")
    return i

def main():
    cmd = os.path.basename(sys.argv[0])
    if cmd.find("-") > -1:
        cmd = ''.join(cmd.split("-", 1)[-1:])
    else:
        cmd = ""

    if cmd == "quit":
        quit()

    elif cmd == "tasks":
        if sys_args1("--autocomplete"):
            print("--monitor -m --follow -f --log -l")
        elif sys_args1("--autocomplete2"):
            print("--follow|-f|--log|-l")
        elif sys_args1("--monitor", "-m"):
            monitor_tasks()
        elif sys_args1("--follow", "-f"):
            follow_task(sys_int_val(2, default=0))
        elif sys_args1("--follow-hack"):
            follow_task_hack(sys_int_val(2))
        elif sys_args1("--log", "-l"):
            log(sys_int_val(2, default=-1))
        else:
            print_tasks()

    elif cmd == "lastlog":
        lastlog()

    elif cmd == "cancel":
        if sys_args1("all"):
            cancel_all()
            return
        idno = sys_int_val(1, default=-1)
        cancel(idno)

    elif cmd == "cancelall":
        cancel_all()

    elif cmd == "default_target":
        if sys_args1("--list"):
            for p in sb2_targets():
                print(p)
        elif sys_args1("--current"):
            print(get_default_target())
        elif len(sys.argv) > 1:
            arg = sys.argv[1]
            if arg in sb2_targets():
                set_default_target(arg)
            else:
                print("Target '%s' not found." % arg)
                sys.exit(1)
        else:
            sb2_default_target()

    elif cmd == "install":
        if len(sys.argv) > 1:
            run_sdk_install(os.getcwd(), sys.argv[1:])

    elif cmd == "zypper" or cmd == "rpm":
        run_sdk_install(os.getcwd(), [ cmd ] + sys.argv[1:])

    elif cmd == "mb2" or cmd == "sb2":
        if len(sys.argv) > 1:
            run_target_cmd(os.getcwd(), cmd, sys.argv[1:])

    elif cmd == "repeat":
        idno = sys_int_val(1, default=-1)
        repeat(idno)

    elif cmd == "reset":
        reset_task_ids()

    elif sys_args1("--debug"):
        set_debug(sys_int_val(2, 1))

    # Handle commands from symbolic links, like sdk-foobar
    elif len(cmd) > 0:
        run_cmd(os.getcwd(), [ cmd ] + sys.argv[1:])

    elif len(sys.argv) > 1:
        run_cmd(os.getcwd(), sys.argv[1:])

if __name__ == "__main__":
    main()
