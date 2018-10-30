#!/usr/bin/env python

import os
import threading
import subprocess
import signal
import re
import sys
import time
import Queue

import dbus
import dbus.service
import dbus.mainloop.glib

from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GObject as gobject

SERVICE_NAME = "org.sailfish.sdkrun"
SERVICE_PATH = "/org/sailfish/sdkrun"

MIN_LINES_FOR_ERROR = 20
ERROR_STR           = "\x1b[31m%s\x1b[39m"
WARN_STR            = "\x1b[33m%s\x1b[39m"

class WorkerPrinter():
    def __init__(self, debug=False):
        self.reset()

        self._match = []
        self._match.append((re.compile(r'^.*:\d+:\d+: error:'), ERROR_STR, True))
        self._match.append((re.compile(r'^.*:\d+:\d+: fatal error:'), ERROR_STR, True))
        self._match.append((re.compile(r'^.*No rule to make target.*Stop.'), ERROR_STR, True))
        self._match.append((re.compile(r'^.*:\d+: error:'), ERROR_STR, True))
        self._match.append((re.compile(r'^.*:\d+:\d+: warning:'), WARN_STR, False))

        self._queue = Queue.Queue()
        self._running = True

        self._thread = threading.Thread(target=self._handler)
        self._thread.start()

        self._debug_enabled = debug

    def _handler(self):
        while self._running:
            line = self._queue.get()
            sys.stdout.write(line)
            sys.stdout.flush()
            self._queue.task_done()

    def _print(self, line):
        self._queue.put(line)

    def debug_enabled(self):
        return self._debug_enabled

    def debug(self, line):
        if self._debug_enabled:
            self.println("DEBUG: " + line)

    def println(self, line):
        self._print(line + "\n")

    def reset(self):
        self._lines = 0
        self._errors = []

    def process(self, line):
        printed = False
        for regex, pr, error in self._match:
            if regex.match(line):
                self._print(pr % line)
                printed = True
                if error:
                    self._errors.append(line)
                break
        if not printed:
            self._print(line)

        self._lines += 1

    def end(self):
        if len(self._errors) > 0 and self._lines > MIN_LINES_FOR_ERROR:
            for line in self._errors:
                self._print(line)
        self.reset()

    def done(self):
        self._running = False
        self._print("")


class Task(threading.Thread):
    global_id = 0

    CREATED     = 0
    STARTING    = 1
    CANCEL      = 2
    RUNNING     = 3
    DONE        = 4
    FAIL        = 5

    @staticmethod
    def reset_ids():
        Task.global_id = 0

    def __init__(self, pwd, argv, state_callback=None, process_callback=None):
        threading.Thread.__init__(self)
        self._pwd = pwd
        self._argv = list(argv)
        Task.global_id += 1
        self._id = Task.global_id
        self._state = Task.CREATED
        self._process = None
        self._process_lock = threading.Lock()
        self._state_cb = state_callback
        self._process_cb = process_callback
        self._returncode = -1
        self._start_time = time.time()
        self._duration = -1

    def lock(self):
        self._process_lock.acquire();

    def unlock(self):
        self._process_lock.release();

    def set_state_callback(self, cb):
        self._state_cb = cb

    def set_process_callback(self, cb):
        self._process_cb = cb

    def id(self):
        return self._id

    def pwd(self):
        return self._pwd

    def argv(self):
        return self._argv

    def cmdline(self):
        return ' '.join(self._argv)

    def _set_state(self, state, lock=True):
        if lock:
            self.lock();
        if self._state != state:
            self._state = state
            if self._state_cb:
                self._state_cb(self)
        if lock:
            self.unlock()

    def state(self):
        return self._state

    def returncode(self):
        return self._returncode

    def time(self):
        return self._duration

    def run(self):
        if self._state != Task.CREATED:
            return

        self.lock()
        self._set_state(Task.STARTING, lock=False)
        try:
            self._process = subprocess.Popen(self._argv, cwd=self._pwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, close_fds=True)
        except OSError as e:
            print e
            self._process = None
            self._set_state(Task.FAIL, lock=False)

        if not self._process:
            self.unlock()
            return

        self._set_state(Task.RUNNING, lock=False)
        self.unlock()

        iterator = iter(self._process.stdout.readline, '')

        while True:
            line = next(iterator, None)
            if not line:
                self._process.wait()
                self.lock()
                self._returncode = self._process.returncode
                self.unlock()
                break

            if self._process_cb:
                self._process_cb(line)

        self._duration = time.time() - self._start_time

        if self._returncode == 0:
            self._set_state(Task.DONE)
        else:
            self._set_state(Task.FAIL)

        # clean up
        self.lock()
        if self._process.stdin:
            self._process.stdin.close()
        if self._process.stdout:
            self._process.stdout.close()
        if self._process.stderr:
            self._process.stderr.close()
        self._process = None
        self.unlock()

    def cancel(self):
        self.lock()
        if self._process:
            self._process.kill()
        self.unlock()

class TaskManager():
    def __init__(self, service):
        self._tasks = []
        self._tasks_lock = threading.Lock()
        self._service = service
        self._printer = WorkerPrinter()
        self._last_pwd = None
        self._last_cmdline = None

    def tasks(self):
        ret = []
        self._tasks_lock.acquire()
        for i in self._tasks:
            ret.append((i.id(), i.state(), i.pwd(), i.cmdline()))
        self._tasks_lock.release()
        return ret

    def add_task(self, pwd, cmdline):
        self._tasks_lock.acquire()
        if len(self._tasks) == 0:
            Task.reset_ids()
        task = Task(pwd, cmdline, self._task_state_changed, self._task_process_line)
        try:
            if len(self._tasks) == 0:
                task.start()
        except:
            self._printer.println("[\x1b[32m%s\x1b[39m] %s  \x1b[31mFailed to create task thread\x1b[39m" % (task.pwd(), task.cmdline()))
            self._tasks_lock.release()
            return -1

        self._tasks.append(task)
        self._tasks_lock.release()

        self._last_pwd = pwd
        self._last_cmdline = cmdline
        self._printer.debug("task added")
        self._service.TaskStateChanged(task.state(), task.id(), task.pwd(), task.cmdline(), task.time())
        return task.id()

    def repeat_task(self):
        if not self._last_cmdline:
            return -1
        return self.add_task(self._last_pwd, self._last_cmdline)

    def cancel_task(self, idno):
        self._tasks_lock.acquire()
        for task in self._tasks:
            if task.id() == idno:
                self._tasks.remove(task)
                task.cancel()
                break
        self._tasks_lock.release()

    def cancel_all(self):
        self._tasks_lock.acquire()
        running = None
        while len(self._tasks) > 0:
            task = self._tasks.pop()
            task.lock()
            if task.state() == Task.RUNNING:
                running = task
            task.unlock()
            if task != running:
                task.cancel()
        if running:
            running.cancel()
        self._tasks_lock.release()
        if running:
            running.join()

    def quit(self):
        self.cancel_all()
        self._printer.done()

    # called from task thread
    def _task_process_line(self, line):
        self._printer.process(line)

    # called from task thread (task lock held)
    def _print_and_remove(self, task, line, last=False):
        if task in self._tasks:
            self._tasks.remove(task);
        self._printer.println(line)
        if last:
            self._printer.end()
        if len(self._tasks) > 0:
            self._tasks[0].start()

    # called from task thread (task lock held)
    def _task_state_changed(self, task):
        if self._printer.debug_enabled():
            self._printer.debug("task \"%s\" state %d" % (task.cmdline(), task.state()))

        if task.state() == Task.STARTING:
            self._printer.reset()
            self._printer.println("[\x1b[32m%s\x1b[39m] %s" % (task.pwd(), task.cmdline()))

        elif task.state() == Task.DONE:
            self._tasks_lock.acquire()
            self._print_and_remove(task, "[\x1b[32m%s\x1b[39m] %s  \x1b[32mSUCCESS\x1b[39m" % (task.pwd(), task.cmdline()))
            self._tasks_lock.release()

        elif task.state() == Task.FAIL:
            self._tasks_lock.acquire()
            self._print_and_remove(task, "[\x1b[32m%s\x1b[39m] %s  \x1b[31mFAIL\x1b[39m (%d)" % (task.pwd(), task.cmdline(), task.returncode()), last=True)
            self._tasks_lock.release()

        self._service.TaskStateChanged(task.state(), task.id(), task.pwd(), task.cmdline(), task.time())



class Service(dbus.service.Object):
    def __init__(self):
        self._manager = TaskManager(self)

    def run(self):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        bus_name = dbus.service.BusName(SERVICE_NAME, dbus.SessionBus())
        dbus.service.Object.__init__(self, bus_name, SERVICE_PATH)

        self._loop = gobject.MainLoop()
        print("Service running...")
        self._loop.run()
        self._manager.quit()
        print("Service stopped")

    @dbus.service.method(SERVICE_NAME, in_signature='', out_signature='a(iiss)')
    def Tasks(self):
        return self._manager.tasks()

    @dbus.service.method(SERVICE_NAME, in_signature='sas', out_signature='i')
    def AddTask(self, pwd, cmdline):
        if len(cmdline) > 0:
            return self._manager.add_task(pwd, cmdline)
        return -1

    @dbus.service.method(SERVICE_NAME, in_signature='', out_signature='i')
    def Repeat(self):
        return self._manager.repeat_task()

    @dbus.service.method(SERVICE_NAME, in_signature='i', out_signature='')
    def CancelTask(self, idno):
        return self._manager.cancel_task(idno)

    @dbus.service.method(SERVICE_NAME, in_signature='', out_signature='')
    def CancelAll(self):
        return self._manager.cancel_all()

    @dbus.service.method(SERVICE_NAME, in_signature='', out_signature='')
    def Quit(self):
        self._manager.cancel_all()
        self._loop.quit()

    @dbus.service.signal(SERVICE_NAME)
    def TaskStateChanged(self, new_state, task_id, task_pwd, task_cmd, duration):
        pass

if __name__ == "__main__":
    Service().run()
