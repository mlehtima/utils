#!/usr/bin/env python

import dbus
import os
import sys
import ConfigParser
import StringIO

PATH="/org/sailfish/sdkrun"
NAME="org.sailfish.sdkrun"

def method(method):
    bus = dbus.SessionBus()
    service = bus.get_object(NAME, PATH)
    return service.get_dbus_method(method, NAME)

def quit():
    method("Quit")()

def state_str(state):
    if state == 0:
        return "CREATED"
    elif state == 1:
        return "RUNNING"
    elif state == 2:
        return "DONE"
    return "UNKNOWN"

def print_tasks():
    tasks = method("Tasks")()
    if len(tasks) > 0:
        print("{0:6s} {1:10s} {2:s}".format("[id]", "[state]", "[cmdline]"))
        for idno, state, cmd in tasks:
            print("{0:6d} {1:10s} {2:s}".format(idno, state_str(state), cmd))

def cancel(idno):
    method("CancelTask")(idno)

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

def run_build(pwd, cmd):
    final = ['mb2']
    default = get_default_target()
    if default:
        final.extend(['-t', default])
    final.extend(cmd)
    run(pwd, final)

def run_sdk_install(pwd, cmd):
    final = ['sb2']
    default = get_default_target()
    if default:
        final.extend(['-t', default])
    final.extend(['-m', 'sdk-install', '-R'])
    final.extend(cmd)
    run(pwd, final)

def set_default_target(name):
    cmd = ['sb2-config', '-d', name]
    run(os.path.expanduser("~"), cmd)

def cancel_all():
    method("CancelAll")()

if __name__ == "__main__":
    cmd = ''.join(sys.argv[0].split("/")[-1:])

    if cmd == "sdk-quit":
        quit()
    elif cmd == "sdk-tasks":
        print_tasks()
    elif cmd == "sdk-cancel":
        if len(sys.argv) > 1:
            cancel(int(sys.argv[1]))
    elif cmd == "sdk-cancelall":
        cancel_all()
    elif cmd == "sdk-default_target":
        if len(sys.argv) > 1:
            set_default_target(sys.argv[1])
    elif cmd == "sdk-install":
        if len(sys.argv) > 1:
            run_sdk_install(os.getcwd(), sys.argv[1:])
    elif cmd == "sdk-build":
        if len(sys.argv) > 1:
            run_build(os.getcwd(), sys.argv[1:])
    elif len(sys.argv) > 1:
        run(os.getcwd(), sys.argv[1:])
