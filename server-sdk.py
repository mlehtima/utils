#!/usr/bin/env python

import os
import threading
import subprocess
import signal
import re
import sys

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
    def __init__(self):
        self.reset()

        self._match = []
        self._match.append((re.compile(r'^.*:\d+:\d+: error:'), ERROR_STR, True))
        self._match.append((re.compile(r'^.*:\d+:\d+: warning:'), WARN_STR, False))

    def reset(self):
        self._lines = 0
        self._errors = []

    def process(self, line):
        printed = False
        for regex, pr, error in self._match:
            if regex.match(line):
                sys.stdout.write(pr % line)
                printed = True
                if error:
                    self._errors.append(line)
                break
        if not printed:
            sys.stdout.write(line)
        sys.stdout.flush()

        self._lines += 1

    def end(self):
        if len(self._errors) > 0 and self._lines > MIN_LINES_FOR_ERROR:
            for line in self._errors:
                print line,
        self.reset()

class Worker(threading.Thread):
    def __init__(self, cb):
        threading.Thread.__init__(self)
        self._pending_tasks = []
        self._append_cond = threading.Condition()
        self._state = 1
        self._task_done = cb
        self._process = None
        self._process_lock = threading.Lock()
        self._printer = WorkerPrinter()

    def run(self):
        while self._state != 0:
            task = None
            self._append_cond.acquire()
            if len(self._pending_tasks) > 0:
                task = self._pending_tasks.pop(0)
            else:
                self._append_cond.wait()
            self._append_cond.release()

            if task:
                task.print_exec()
                task.set_state(Task.RUNNING)
                self._process_lock.acquire()
                try:
                    self._process = subprocess.Popen(task.argv(), cwd=task.pwd(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                except OSError as e:
                    print e
                    self._process = None
                    task.set_state(Task.DONE)
                self._process_lock.release()

                if self._process:
                    for line in iter(self._process.stdout.readline, ''):
                        self._printer.process(line)
                    self._process.wait()
                    self._process_lock.acquire()
                    task.set_state(Task.DONE)
                    task.print_done(self._process.returncode)
                    self._process = None
                    self._process_lock.release()
                    self._printer.end()

                self._task_done(task)

    def add_task(self, task):
        self._append_cond.acquire()
        self._pending_tasks.append(task)
        self._append_cond.notify()
        self._append_cond.release()

    def cancel_task(self, task):
        cancelled = False
        self._append_cond.acquire()
        if task in self._pending_tasks and task.state() != Task.RUNNING:
            self._pending_tasks.remove(task)
            cancelled = True
        self._append_cond.release()
        return cancelled

    def quit(self):
        self._process_lock.acquire()
        if self._process:
            self._process.terminate()
        self._process_lock.release()

        self._append_cond.acquire()
        self._state = 0
        self._append_cond.notify()
        self._append_cond.release()


class Task():
    global_id = 0

    CREATED = 0
    RUNNING = 1
    DONE    = 2

    def __init__(self, pwd, argv):
        self._pwd = pwd
        self._argv = list(argv)
        Task.global_id += 1
        self._id = Task.global_id
        self._state = Task.CREATED

    def id(self):
        return self._id

    def pwd(self):
        return self._pwd

    def argv(self):
        return self._argv

    def cmdline(self):
        return ' '.join(self._argv)

    def set_state(self, state):
        self._state = state

    def state(self):
        return self._state

    def print_exec(self):
        print "[\x1b[32m%s\x1b[39m] %s" % (self.pwd(), self.cmdline())

    def print_done(self, code):
        if code == 0:
            print "[\x1b[32m%s\x1b[39m] %s  \x1b[32mSUCCESS\x1b[39m" % (self.pwd(), self.cmdline())
        else:
            print "[\x1b[32m%s\x1b[39m] %s  \x1b[31mFAIL\x1b[39m (%d)" % (self.pwd(), self.cmdline(), code)

class Boss():
    def __init__(self, service):
        self._tasks = []
        self._tasks_lock = threading.Lock()
        self._service = service
        self._worker = Worker(self._task_done)
        self._worker.start()

    def tasks(self):
        ret = []
        self._tasks_lock.acquire()
        for i in self._tasks:
            ret.append((i.id(), i.state(), i.cmdline()))
        self._tasks_lock.release()
        return ret

    def add_task(self, pwd, cmdline):
        task = Task(pwd, cmdline)
        self._tasks_lock.acquire()
        self._tasks.append(task)
        self._tasks_lock.release()
        self._worker.add_task(task)
        return task.id()

    def cancel_task(self, idno):
        self._tasks_lock.acquire()
        for task in self._tasks:
            if task.id() == idno:
                if self._worker.cancel_task(task):
                    self._tasks.remove(task)
                break
        self._tasks_lock.release()

    def cancel_all(self):
        self._tasks_lock.acquire()
        running = None
        while len(self._tasks) > 0:
            task = self._tasks.pop()
            if not self._worker.cancel_task(task):
                running = task
        if running:
            self._tasks.append(running)
        self._tasks_lock.release()

    def quit(self):
        self._worker.quit()
        self._worker.join()

    def _task_done(self, task):
        self._tasks_lock.acquire()
        self._tasks.remove(task)
        self._tasks_lock.release()


class Service(dbus.service.Object):
    def __init__(self):
        self._boss = Boss(self)

    def run(self):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        bus_name = dbus.service.BusName(SERVICE_NAME, dbus.SessionBus())
        dbus.service.Object.__init__(self, bus_name, SERVICE_PATH)

        self._loop = gobject.MainLoop()
        print "Service running..."
        self._loop.run()
        self._boss.quit()
        print "Service stopped"

    @dbus.service.method(SERVICE_NAME, in_signature='', out_signature='a(iis)')
    def Tasks(self):
        return self._boss.tasks()

    @dbus.service.method(SERVICE_NAME, in_signature='sas', out_signature='i')
    def AddTask(self, pwd, cmdline):
        if len(cmdline) > 0:
            return self._boss.add_task(pwd, cmdline)
        return -1

    @dbus.service.method(SERVICE_NAME, in_signature='i', out_signature='')
    def CancelTask(self, idno):
        return self._boss.cancel_task(idno)

    @dbus.service.method(SERVICE_NAME, in_signature='', out_signature='')
    def CancelAll(self):
        return self._boss.cancel_all()

    @dbus.service.method(SERVICE_NAME, in_signature='', out_signature='')
    def Quit(self):
        self._boss.cancel_all()
        self._loop.quit()

if __name__ == "__main__":
    Service().run()
