#!/usr/bin/env python

import dbus
import dbus.mainloop.glib
import os
import sys
import signal
import distutils.spawn
from subprocess import Popen, PIPE, STDOUT
import ConfigParser
import StringIO
from gi.repository import GObject as gobject

PATH="/org/sailfish/sdkrun"
NAME="org.sailfish.sdkrun"

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

def method(method):
    bus = dbus.SessionBus()
    service = bus.get_object(NAME, PATH)
    return service.get_dbus_method(method, NAME)

def quit():
    method("Quit")()

def print_tasks(clear=False, print_empty=False):
    if clear:
        # not best but shortest solution for now
        os.system("clear")
    tasks = method("Tasks")()
    if len(tasks) > 0:
        print "[id]", "[state]".ljust(8), "[cmdline]"
        for idno, state, cmd in tasks:
            print("{0:4d} {1:8s} {2:s}".format(idno, state_str(state), cmd))
    elif print_empty:
        print("No active tasks.")

class TaskMonitor():
    def __init__(self):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        bus = dbus.SessionBus()
        bus.add_signal_receiver(TaskMonitor.task_handler,
                                dbus_interface=NAME,
                                signal_name="TaskStateChanged")
        self.mainloop = gobject.MainLoop()

    def run(self):
        print_tasks(True, True)
        self.mainloop.run()

    @staticmethod
    def task_handler(new_state, task_id, task_pwd, task_cmd, duration):
        print_tasks(True, True)

def monitor_tasks():
    TaskMonitor().run()

def cancel(idno):
    if idno < 0:
        tasks = method("Tasks")()
        for idn, state, cmd in tasks:
            if state == STATE_RUNNING:
                idno = idn
                break
    if idno > 0:
        method("CancelTask")(idno)

def repeat():
    method("Repeat")()

def run(pwd, cmd):
    method("AddTask")(pwd, cmd)

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

def apply_default(cmd, final):
    use_default = True
    for arg in cmd:
        if arg == '-t':
            use_default = False
            break
    if use_default:
        default = get_default_target()
        if default:
            final.extend(['-t', default])

def run_mb2(pwd, cmd):
    final = ['mb2']
    apply_default(cmd, final)
    final.extend(cmd)
    run(pwd, final)

def run_sdk_install(pwd, cmd):
    final = ['sb2']
    apply_default(cmd, final)
    final.extend(['-m', 'sdk-install', '-R'])
    final.extend(cmd)
    run(pwd, final)

def set_default_target(name):
    cmd = ['sb2-config', '-d', name]
    run(os.path.expanduser("~"), cmd)

def cancel_all():
    method("CancelAll")()

def main():
    cmd = ''.join(sys.argv[0].split("-")[-1:])

    if cmd == "quit":
        quit()

    elif cmd == "tasks":
        if len(sys.argv) > 1 and sys.argv[1] == "--monitor":
            monitor_tasks()
        else:
            print_tasks()

    elif cmd == "cancel":
        idno = -1
        if len(sys.argv) > 1:
            if sys.argv[1] == "all":
                cancel_all()
                return
            idno = int(sys.argv[1])
        cancel(idno)

    elif cmd == "cancelall":
        cancel_all()

    elif cmd == "default_target":
        if len(sys.argv) > 1:
            set_default_target(sys.argv[1])
        else:
            if distutils.spawn.find_executable("dmenu"):
                targets = []
                default_target = get_default_target()
                sb2 = os.path.expanduser("~/.scratchbox2")
                files = os.listdir(sb2)
                for f in files:
                    if os.path.isdir(os.path.join(sb2, f)) and default_target != f:
                        targets.append(f)
                targets.sort()
                if default_target:
                    targets.insert(0, default_target)
                if len(targets) > 0:
                    p = Popen(["dmenu", "-p", "set default sb2 target:"], stdin=PIPE, stdout=PIPE, stderr=STDOUT)
                    ret = p.communicate(input="\n".join(targets))[0]
                    if ret:
                        set_default_target(ret.split("\n")[0])
            else:
                print get_default_target()

    elif cmd == "install":
        if len(sys.argv) > 1:
            run_sdk_install(os.getcwd(), sys.argv[1:])

    elif cmd == "zypper":
        run_sdk_install(os.getcwd(), [ 'zypper' ] + sys.argv[1:])

    elif cmd == "rpm":
        run_sdk_install(os.getcwd(), [ 'rpm' ] + sys.argv[1:])

    elif cmd == "mb2":
        if len(sys.argv) > 1:
            run_mb2(os.getcwd(), sys.argv[1:])

    elif cmd == "repeat":
        repeat()

    elif len(sys.argv) > 1:
        run(os.getcwd(), sys.argv[1:])

if __name__ == "__main__":
    main()
