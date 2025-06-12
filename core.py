import asyncio
import functools
import sublime
import threading


# --- Core ---

class Handle:
    def __init__(self, callback, args):
        self.callback = callback
        self.args = args

    def __call__(self):
        if self.callback:
            self.callback(*self.args)

    def cancel(self):
        self.callback = None
        self.args = None


class SublimeEventLoop(asyncio.BaseEventLoop):
    def __init__(self, scheduler):
        self._schedule = scheduler
        super().__init__()

    def is_running(self):
        return True

    def is_closed(self):
        return False

    def call_soon(self, callback, *args, context=None):
        handle = Handle(callback, args)
        self._schedule(handle)
        return handle

    def call_later(self, delay, callback, *args, context=None):
        handle = Handle(callback, args)
        delay_ms = max(0, int(delay * 1000))
        self._schedule(handle, delay_ms)
        return handle

    def call_soon_threadsafe(self, callback, *args):
        return self.call_soon(callback, *args)

    def create_future(self):
        return asyncio.Future(loop=self)

    def create_task(self, coro):
        task = asyncio.Task(coro, loop=self)
        task._log_destroy_pending = False
        return task

    def get_debug(self):
        return False


# --- Create UI and Worker loops ---

ui_loop = SublimeEventLoop(sublime.set_timeout)
worker_loop = SublimeEventLoop(sublime.set_timeout_async)

local = {}
original_get_running_loop = asyncio.events.get_running_loop


def _set_event_loop(loop: asyncio.AbstractEventLoop):
    local[threading.get_ident()] = loop


def get_running_loop():
    try:
        return local[threading.get_ident()]
    except KeyError:
        return original_get_running_loop()


asyncio.events.get_running_loop = get_running_loop
_set_event_loop(ui_loop)
sublime.set_timeout_async(lambda: _set_event_loop(worker_loop))


def unpatch_asyncio():
    asyncio.events.get_running_loop = original_get_running_loop


def plugin_loaded():
    sublime.set_timeout(main2, 1000)


def plugin_unloaded():
    unpatch_asyncio()


# --- Utilities ---

def run_on_ui_loop(fn_or_coro):
    if asyncio.iscoroutine(fn_or_coro):
        # Direct coroutine passed: schedule and return task
        return ui_loop.create_task(fn_or_coro)

    elif callable(fn_or_coro):
        @functools.wraps(fn_or_coro)
        def wrapper(*args, **kwargs):
            coro = fn_or_coro(*args, **kwargs)
            return ui_loop.create_task(coro)
        return wrapper

    raise TypeError("run_on_ui_loop expects a coroutine or a callable returning a coroutine")

def run_on_worker_loop(fn_or_coro):
    if callable(fn_or_coro):
        @functools.wraps(fn_or_coro)
        def wrapper(*args, **kwargs):
            return asyncio.ensure_future(fn_or_coro(*args, **kwargs), loop=worker_loop)
        return wrapper
    return asyncio.ensure_future(fn_or_coro, loop=worker_loop)

async def switch_to_ui(coro):
    fut = asyncio.Future(loop=worker_loop)

    def _schedule():
        task = ui_loop.create_task(coro)
        task.add_done_callback(lambda t: _transfer_result(t, fut))

    sublime.set_timeout(_schedule, 0)
    return await fut

async def switch_to_worker(coro):
    fut = asyncio.Future(loop=ui_loop)

    def _schedule():
        task = asyncio.ensure_future(coro, loop=worker_loop)
        task.add_done_callback(lambda t: _transfer_result(t, fut))

    sublime.set_timeout_async(_schedule, 0)
    return await fut

def _transfer_result(task, fut):
    if task.cancelled():
        fut.cancel()
    elif task.exception():
        fut.set_exception(task.exception())
    else:
        fut.set_result(task.result())


import sublime
import sublime_plugin


def thname():
    return threading.current_thread().name


class example_async(sublime_plugin.TextCommand):
    @run_on_ui_loop
    async def run(self, view):
        view = self.view
        # Extract view content on UI thread
        content = view.substr(sublime.Region(0, view.size()))
        print("Got content on UI thread", thname())

        # Process on worker thread
        processed = await switch_to_worker(self.process_in_background(content))
        print("Got result from worker", thname())

        # Draw result on UI thread
        await self.draw_result(view, processed)
        print("Finished drawing", thname())

    async def process_in_background(self, content):
        print("process_in_background", thname())
        await asyncio.sleep(1)  # Simulate heavy work
        file_name = await switch_to_ui(self.more_context())
        await self.still_background(file_name)
        return content.upper()[:100]  # Dummy "analysis"

    async def more_context(self):
        print("more_context", thname())
        await asyncio.sleep(0.01)  # Simulate light work
        return self.view.file_name()

    async def still_background(self, fname):
        print("still_background", thname(), fname)
        await asyncio.sleep(1)  # Simulate heavy work

    async def draw_result(self, view, result):
        print("draw_result", result[:10], thname())


def main():
    print("main")
    w = sublime.active_window()
    v = w.active_view()
    v.run_command("example_async")



from itertools import cycle

@run_on_ui_loop
async def main2():
    # Showcase that Sublime UI loop has no "holes", i.e. it does not flicker
    # Abort the spinner with <escape>.
    print("main2")
    window = sublime.active_window()

    text = cycle(("Loading...", "Loading.."))
    ignore_next_abort = False
    aborted = False
    sleeper = None

    def done(n):
        nonlocal aborted, ignore_next_abort
        if ignore_next_abort:
            ignore_next_abort = False
            return
        if n == -1:
            aborted = True
        else:
            sleeper.cancel()

    for _ in range(10):
        text_ = next(text)
        window.show_quick_panel([text_], done)
        sleeper = run_on_ui_loop(asyncio.sleep(0.3))
        try:
            await sleeper
        except asyncio.CancelledError:
            pass
        if aborted:
            break
        ignore_next_abort = True
        window.run_command("hide_overlay")
    else:
        print("never resolved")
