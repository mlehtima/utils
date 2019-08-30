#!/usr/bin/env python

import dbus
import dbus.service
import dbus.mainloop.glib
import os
import sys
import distutils.spawn
from subprocess import Popen, PIPE, STDOUT
import ConfigParser
import StringIO
from gi.repository import GObject as gobject

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

def sdk_method(method_name):
    bus = dbus.SessionBus()
    service = bus.get_object(SERVER_NAME, SERVER_PATH)
    return service.get_dbus_method(method_name, SERVER_NAME)

def quit():
    sdk_method("Quit")()

def print_tasks(clear=False, print_empty=False):
    if clear:
        # not best but shortest solution for now
        os.system("clear")
    tasks = sdk_method("Tasks")()
    if len(tasks) > 0:
        print("{0:6s} {1:12s} {2:s}".format("[id/s]", "[path]", "[cmdline]"))
        for idno, state, full_path, cmd in tasks:
            run_path = ''.join(full_path.split("/")[-1:])
            if len(run_path) > 12:
                run_path = ".." + run_path[-10:]
            print("{0:3d} {1:<2s} {2:12s} {3:s}".format(idno, state_short_str(state), run_path, cmd))
    elif print_empty:
        print("No active tasks.")

class TaskMonitor():
    def __init__(self):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        bus = dbus.SessionBus()
        bus.add_signal_receiver(TaskMonitor.task_handler,
                                dbus_interface=SERVER_NAME,
                                signal_name="TaskStateChanged")
        self.mainloop = gobject.MainLoop()

    def run(self):
        print_tasks(True, True)
        try:
            self.mainloop.run()
        except KeyboardInterrupt as e:
            self.mainloop.quit()

    @staticmethod
    def task_handler(new_state, task_id, task_pwd, task_cmd, duration):
        print_tasks(True, True)

def monitor_tasks():
    TaskMonitor().run()

class TaskFollower(dbus.service.Object):
    IFACE   = "org.sailfish.sdk.client"
    PATH    = "/org/sailfish/sdk/client"
    def __init__(self, idno):
        self._name = "org.sailfish.sdk.client{}".format(os.getpid())
        self._idno = int(idno)
        self._retno = 0
        pass

    def _m(self, method_name):
        bus = dbus.SessionBus()
        service = bus.get_object(SERVER_NAME, SERVER_PATH)
        return service.get_dbus_method(method_name, SERVER_NAME)

    def _register_follower(self):
        if self._m("FollowTask")(self._idno, self._name.get_name()):
            self._running = True
        else:
            sys.stderr.write("No task with id {}.\n".format(self._idno))
            sys.stderr.flush()
            self._retno = 1
            self._loop.quit()

    def quit(self):
        if self._running:
            self._m("UnfollowTask")(self._idno, self._name.get_name())
        self._loop.quit()

    def run(self):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self._loop = gobject.MainLoop.new(None, False)
        bus_name = dbus.service.BusName(self._name, dbus.SessionBus())
        dbus.service.Object.__init__(self, bus_name, self.PATH)
        gobject.idle_add(self._register_follower)
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

def follow_task(idno):
    t = TaskFollower(idno)
    t.run()
    sys.exit(t.retno())

def log(idno):
    found, text = sdk_method("Log")(idno)
    if found:
        sys.stdout.write(text)
        sys.stdout.flush()
    else:
        sys.stderr.write("No task with id {}.\n".format(idno))
        sys.stderr.flush()
        sys.exit(1)

def cancel(idno):
    if idno < 0:
        tasks = sdk_method("Tasks")()
        for idn, state, full_path, cmd in tasks:
            if idn > idno:
                idno = idn
    if idno > 0:
        sdk_method("CancelTask")(idno)

def repeat():
    sdk_method("Repeat")()

def reset_task_ids():
    sdk_method("Reset")()

def run_cmd(pwd, cmd, background=False):
    follow = follow_created_task(cmd)
    r = sdk_method("AddTask")(pwd, cmd, background)
    if r > 0 and follow:
        #follow_task(r)
        # This is stupid workaround, but couldn't figure out how to get
        # mainloop running again for the TaskFollower.
        os.execlp("dk-tasks", "dk-tasks", "--follow", str(r))

def get_default_target():
    default = None
    config = ConfigParser.ConfigParser()
    try:
        with open(os.path.expanduser("~/.scratchbox2/config")) as stream:
            stream = StringIO.StringIO("[default]\n" + stream.read())
            config.readfp(stream)
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
        ret = p.communicate(input="\n".join(targets))[0]
        if ret:
            set_default_target(ret.split("\n")[0])

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
        sys.stderr.write("Integer argument required.\n")
        sys.stderr.flush()
        sys.exit(1)
    return i

def main():
    cmd = ''.join(sys.argv[0].split("-")[-1:])

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
            follow_task(sys_int_val(2))
        elif sys_args1("--log", "-l"):
            log(sys_int_val(2))
        else:
            print_tasks()

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
        repeat()

    elif cmd == "reset":
        reset_task_ids()

    elif len(sys.argv) > 1:
        run_cmd(os.getcwd(), sys.argv[1:])

if __name__ == "__main__":
    main()
