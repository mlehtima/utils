#!/usr/bin/env python

import os
import dbus
import dbus.service
import dbus.mainloop.glib

from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GObject as gobject

TASK_DONE = 4
TASK_FAIL = 5

MIN_DONE_DURATION = 10
MIN_FAIL_DURATION = 0.5

def state_changed_handler(new_state, task_id, task_pwd, task_cmd, duration):
    if new_state != TASK_DONE and new_state != TASK_FAIL:
        return

    if new_state == TASK_DONE:
        icon = "dialog-information"
        header = "SUCCESS"
        if duration < MIN_DONE_DURATION:
            return
    else:
        icon = "dialog-error"
        header = "FAIL"
        if duration < MIN_FAIL_DURATION:
            return

    os.system('notify-send -t 3000 -i %s "%s" "%s"' % (icon, header, task_cmd))

def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    loop = gobject.MainLoop()
    bus.add_signal_receiver(state_changed_handler,
                            dbus_interface='org.sailfish.sdkrun',
                            signal_name='TaskStateChanged')
    loop.run()

if __name__ == "__main__":
    main()
