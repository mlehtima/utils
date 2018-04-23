#!/usr/bin/env python

import dbus
import os
import sys
import ConfigParser
import StringIO

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

def print_tasks():
    tasks = method("Tasks")()
    if len(tasks) > 0:
        print "[id]", "[state]".ljust(8), "[cmdline]"
        for idno, state, cmd in tasks:
            print("{0:4d} {1:8s} {2:s}".format(idno, state_str(state), cmd))

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
    cmd = ''.join(sys.argv[0].split("/")[-1:])

    if cmd == "sdk-quit":
        quit()

    elif cmd == "sdk-tasks":
        print_tasks()

    elif cmd == "sdk-cancel":
        idno = -1
        if len(sys.argv) > 1:
            if sys.argv[1] == "all":
                cancel_all()
                return
            idno = int(sys.argv[1])
        cancel(idno)

    elif cmd == "sdk-cancelall":
        cancel_all()

    elif cmd == "sdk-default_target":
        if len(sys.argv) > 1:
            set_default_target(sys.argv[1])
        else:
            print get_default_target()

    elif cmd == "sdk-install":
        if len(sys.argv) > 1:
            run_sdk_install(os.getcwd(), sys.argv[1:])

    elif cmd == "sdk-mb2":
        if len(sys.argv) > 1:
            run_mb2(os.getcwd(), sys.argv[1:])

    elif cmd == "sdk-repeat":
        repeat()

    elif len(sys.argv) > 1:
        run(os.getcwd(), sys.argv[1:])

if __name__ == "__main__":
    main()
