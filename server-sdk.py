#!/usr/bin/env python3

import os
import threading
import subprocess
import signal
import re
import sys
import time
import queue
import traceback
from datetime import timedelta
from unicodedata import normalize
from pathlib import Path

import dbus
import dbus.service
import dbus.mainloop.glib

from gi.repository import GLib

SERVICE_NAME = "org.sailfish.sdkrun"
SERVICE_PATH = "/org/sailfish/sdkrun"

BUILD_LOGS_ENABLED  = True
BUILD_LOGS_PATH     = ".build_logs"

TASK_HISTORY_LENGTH = 50
MIN_LINES_FOR_ERROR = 20
ERROR_STR           = "\x1b[31m{}\x1b[39m"
WARN_STR            = "\x1b[33m{}\x1b[39m"
LOG_STATE_STR       = "\x1b[33m({0:>3})\x1b[39m [\x1b[32m{1}\x1b[39m] {2}"
LOG_SUCCESS_STR     = "\x1b[32mSUCCESS\x1b[39m"
LOG_CANCEL_STR      = "\x1b[33mCANCEL\x1b[39m"
LOG_FAIL_STR        = "\x1b[31mFAIL\x1b[39m"

class WorkerPrinter():
    def __init__(self, debug=False):
        self.reset()

        self._match = []
        self._match.append((re.compile(r'^.*:\d+:\d+: error:'),                 ERROR_STR,  True    ))
        self._match.append((re.compile(r'^.*:\d+:\d+: fatal error:'),           ERROR_STR,  True    ))
        self._match.append((re.compile(r'^.*No rule to make target.*Stop.'),    ERROR_STR,  True    ))
        self._match.append((re.compile(r'^.*:\d+: error:'),                     ERROR_STR,  True    ))
        self._match.append((re.compile(r'^.*:\d+:\d+: warning:'),               WARN_STR,   False   ))

        self._queue = queue.Queue()
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

    def set_debug(self, enabled):
        self._debug_enabled = enabled

    def debug_enabled(self):
        return self._debug_enabled

    def debug(self, line):
        if self._debug_enabled:
            self.println("DEBUG: {}".format(line))

    def println(self, line):
        self._print("{}\n".format(line))

    def reset(self):
        self._lines = 0
        self._errors = []

    def process(self, line):
        printed = False
        for regex, pr, error in self._match:
            if regex.match(line):
                self._print(pr.format(line))
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
                self._print(ERROR_STR.format(line))
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

    def __init__(self, pwd, argv, state_callback=None, process_callback=None, background=False):
        threading.Thread.__init__(self)
        self._pwd = pwd
        self._argv = list(argv)
        Task.global_id += 1
        self._id = Task.global_id
        self._state = Task.CREATED
        self._background = background
        self._process = None
        self._process_lock = threading.Lock()
        self._state_cb = state_callback
        self._process_cb = process_callback
        self._returncode = -1
        self._start_time = 0
        self._duration = 0
        self._followers = []
        self._output = []
        self._log_file = None

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

    def state_pretty_str(self):
        s = LOG_STATE_STR.format(self.id(), self.pwd(), self.cmdline())
        if self._state > Task.STARTING:
            s = "{0} ({1:0>8})".format(s, str(timedelta(seconds=self.time())))
        return s

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

    def background(self):
        return self._background

    def returncode(self):
        return self._returncode

    def time(self):
        if self._state == Task.DONE:
            return int(self._duration)
        else:
            return int(time.time() - self._start_time)

    def _quit_follower(self, method_quit):
        method_quit(self._returncode)

    def register_follower(self, name):
        IFACE = "org.sailfish.sdk.client"
        PATH  = "/org/sailfish/sdk/client"
        bus = dbus.SessionBus()
        service = bus.get_object(name, PATH)
        method_write = service.get_dbus_method("Write", IFACE)
        method_quit = service.get_dbus_method("Quit", IFACE)
        if self._state in (Task.CREATED, Task.STARTING, Task.RUNNING):
            self._followers.append((method_write, method_quit, name))
        else:
            GLib.idle_add(self._quit_follower, method_quit)

    def unregister_follower(self, unregister_name):
        i = 0
        for method_write, method_quit, name in self._followers:
            if unregister_name == name:
                self._followers.pop(i)
                break
            i += 1

    def log(self):
        return "".join(self._output)

    def _process_line(self, line):
        self._output.append(line)
        if self._log_file:
            self._log_file.write(line)

        if len(self._followers):
            for method_write, method_quit, name in self._followers:
                method_write(line)

        if self._process_cb:
            self._process_cb(self, line)

    def slugify(self):
        """
        Normalizes string, converts to lowercase, removes non-alpha characters,
        and converts spaces to hyphens.
        """
        value = normalize('NFKD', "{0:s}-{1:s}".format(self.pwd(), self.cmdline())).encode('ascii', 'ignore')
        value = re.sub(r'[^\w\s-]', '_', value.decode()).strip().lower()
        value = re.sub(r'[-\s]+', '-', value)
        # Max filename length is usually 255 characters, so let's stick to something sane.
        if len(value) > 160:
            value = value[:160]
        return value

    def run(self):
        if self._state != Task.CREATED:
            return

        self._start_time = time.time()

        if BUILD_LOGS_ENABLED:
            log_path = Path(os.path.join(str(Path.home()), BUILD_LOGS_PATH))
            log_fn = os.path.join(str(log_path), "{0:d}-{1:s}.log".format(int(time.time()), self.slugify()))
            if not log_path.exists():
                log_path.mkdir()
            self._log_file = open(log_fn, "w")
            self._log_file.write("{0:s} $ {1:s}\n".format(self.pwd(), self.cmdline()))
            self._log_file.write("================log================\n")

        self.lock()
        self._set_state(Task.STARTING, lock=False)
        try:
            self._process = subprocess.Popen(self._argv, cwd=self._pwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, close_fds=True)
        except OSError as e:
            print(e)
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

            self._process_line(line.decode('utf-8'))

        self._duration = time.time() - self._start_time

        if self._returncode == 0:
            self._set_state(Task.DONE)
        else:
            self._set_state(Task.FAIL)

        # clean up
        self.lock()
        for method_write, method_quit, name in self._followers:
            method_quit(self._returncode)
        while len(self._followers):
            self._followers.pop()
        if self._process.stdin:
            self._process.stdin.close()
        if self._process.stdout:
            self._process.stdout.close()
        if self._process.stderr:
            self._process.stderr.close()
        self._process = None
        self._log_file = None
        self.unlock()

    def cancel(self):
        self.lock()
        if self._process:
            self._process.kill()
        if self._state == Task.RUNNING:
            self._set_state(Task.CANCEL, lock=False)
        self.unlock()

class TaskManager():
    def __init__(self, service):
        self._tasks = []
        self._tasks_lock = threading.Lock()
        self._service = service
        self._printer = WorkerPrinter()
        self._last_pwd = None
        self._last_cmdline = None
        self._history_length = TASK_HISTORY_LENGTH
        signal.signal(signal.SIGINT, self._sigint_handler)

    def tasks(self):
        ret = []
        self._tasks_lock.acquire()
        for i in self._tasks:
            ret.append((i.id(), i.state(), i.pwd(), i.cmdline(), i.returncode(), i.time()))
        self._tasks_lock.release()
        return ret

    def task(self, idno):
        ret = None
        self._tasks_lock.acquire()
        for i in self._tasks:
            if i.id() == idno:
                ret = (i.id(), i.state(), i.pwd(), i.cmdline(), i.returncode(), i.time())
                break
        self._tasks_lock.release()
        return ret

    # run with task lock acquired
    def _append_task(self, task):
        if len(self._tasks) >= self._history_length:
            i = 0
            for t in self._tasks:
                if t.state() in (Task.DONE, Task.CANCEL, Task.FAIL):
                    self._tasks.pop(i)
                    break
            i += 1
        self._tasks.append(task)

    def _run_task(self, task):
        try:
            task.start()
            return True
        except Exception as e:
            self._printer.println("[\x1b[32m{}\x1b[39m] {}  \x1b[31mFailed to create task thread: {}\x1b[39m".format(task.pwd(), task.cmdline(), e))
            self._printer.println(traceback.format_exc())
            return False


    def add_task(self, pwd, cmdline, background):
        self._tasks_lock.acquire()
        #if len(self._tasks) == 0:
        #    Task.reset_ids()
        cb = None
        if not background:
            cb = self._task_process_line
        task = Task(pwd, cmdline, self._task_state_changed, cb, background)
        if background or not self._find_task(Task.RUNNING):
            if not self._run_task(task):
                self._tasks_lock.release()
                return -1
        self._append_task(task)
        self._tasks_lock.release()

        self._last_pwd = pwd
        self._last_cmdline = cmdline
        self._last_background = background
        self._printer.debug("({0}) {1}task added".format(task.id(), "background " if task.background() else ""))
        self._service.TaskStateChanged(task.state(), task.id(), task.pwd(), task.cmdline(), task.time())
        return task.id()

    def repeat_task(self):
        if not self._last_cmdline:
            return -1
        return self.add_task(self._last_pwd, self._last_cmdline, self._last_background)

    def cancel_task(self, idno):
        self._tasks_lock.acquire()
        for task in self._tasks:
            if task.id() == idno:
                task.cancel()
                break
        self._tasks_lock.release()

    def cancel_all(self, clear_history=False):
        self._tasks_lock.acquire()
        running = None
        for task in self._tasks:
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
        if clear_history:
            while len(self._tasks):
                self._tasks.pop()

    def _task_with_id(self, idno):
        for task in self._tasks:
            if task.id() == idno:
                return task
        return None

    def follow_task(self, idno, name):
        task = self._task_with_id(idno)
        if task:
            task.register_follower(name)
            return True
        return False

    def unfollow_task(self, idno, name):
        task = self._task_with_id(idno)
        if task:
            task.unregister_follower(name)

    def task_log(self, idno):
        task = self._task_with_id(idno)
        if task:
            return True, task.log()
        return False, ""

    def quit(self):
        self.cancel_all()
        self._printer.done()

    # called from task thread
    def _task_process_line(self, task, line):
        self._printer.process("[{0:4d}s] {1}".format(task.time(), line))

    # return first task of task_type
    def _find_task(self, task_type, background=False):
        for task in self._tasks:
            if task.state() == task_type and task.background() == background:
                return task
        return None

    # called from task thread (task lock held)
    def _print_and_remove(self, task, line, last=False):
        self._printer.println(line)
        if last:
            self._printer.end()
        if not self._find_task(Task.RUNNING):
            task = self._find_task(Task.CREATED)
            if task:
                self._run_task(task)

    # called from task thread (task lock held)
    def _task_state_changed(self, task):
        if self._printer.debug_enabled():
            self._printer.debug("({0}) task \"{1}\" state {2}".format(task.id(), task.cmdline(), task.state()))

        if task.state() == Task.STARTING:
            self._printer.reset()
            self._printer.println(task.state_pretty_str())

        elif task.state() == Task.CANCEL:
            # Cancel state is reached with _tasks_lock acquired
            self._print_and_remove(task, "{0}  {1}".format(task.state_pretty_str(), LOG_CANCEL_STR));

        elif task.state() == Task.DONE:
            self._tasks_lock.acquire()
            self._print_and_remove(task, "{0}  {1}".format(task.state_pretty_str(), LOG_SUCCESS_STR));
            self._tasks_lock.release()

        elif task.state() == Task.FAIL:
            self._tasks_lock.acquire()
            self._print_and_remove(task, "{0}  {1} ({2})".format(task.state_pretty_str(), LOG_FAIL_STR, task.returncode()), last=True);
            self._tasks_lock.release()

        self._service.TaskStateChanged(task.state(), task.id(), task.pwd(), task.cmdline(), task.time())

    # Gobble ctrl+c so that it doesn't kill us but trickles down to the subprocess
    # we are running
    def _sigint_handler(self, sig, frame):
        pass


class Service(dbus.service.Object):
    def __init__(self):
        self._manager = TaskManager(self)

    def run(self):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        bus_name = dbus.service.BusName(SERVICE_NAME, dbus.SessionBus())
        dbus.service.Object.__init__(self, bus_name, SERVICE_PATH)

        # GLib MainLoop installs by default signal handler for SIGINT
        # creating the MainLoop with new(None, False) disables the signal
        # handler so we can handle the signal later
        self._loop = GLib.MainLoop.new(None, False)
        print("Service running...")
        self._loop.run()
        self._manager.quit()
        print("Service stopped")

    @dbus.service.method(SERVICE_NAME, in_signature='i', out_signature='iissii')
    def Task(self, idno):
        t = self._manager.task(idno)
        if t:
            return t
        return (-1, -1, "", "", -1, -1)

    @dbus.service.method(SERVICE_NAME, in_signature='', out_signature='a(iissii)')
    def Tasks(self):
        return self._manager.tasks()

    @dbus.service.method(SERVICE_NAME, in_signature='sasb', out_signature='i')
    def AddTask(self, pwd, cmdline, background):
        if len(cmdline) > 0:
            return self._manager.add_task(pwd, cmdline, background)
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
    def Reset(self):
        self._manager.cancel_all(clear_history=True)
        Task.reset_ids()
        # This is slight hack for now, just nudge the client so it updates task list
        self.TaskStateChanged(Task.DONE, 0, "", "", 0)

    @dbus.service.method(SERVICE_NAME, in_signature='is', out_signature='b')
    def FollowTask(self, idno, name):
        return self._manager.follow_task(idno, name)

    @dbus.service.method(SERVICE_NAME, in_signature='is', out_signature='')
    def UnfollowTask(self, idno, name):
        self._manager.unfollow_task(idno, name)

    @dbus.service.method(SERVICE_NAME, in_signature='i', out_signature='bs')
    def Log(self, idno):
        return self._manager.task_log(idno)

    @dbus.service.method(SERVICE_NAME, in_signature='', out_signature='')
    def Quit(self):
        self._manager.cancel_all()
        self._loop.quit()

    @dbus.service.method(SERVICE_NAME, in_signature='b', out_signature='')
    def Debug(self, enabled):
        self._manager._printer.set_debug(enabled)

    @dbus.service.signal(SERVICE_NAME)
    def TaskStateChanged(self, new_state, task_id, task_pwd, task_cmd, duration):
        pass

if __name__ == "__main__":
    Service().run()
