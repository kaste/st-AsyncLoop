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
    def __init__(self, use_async=False):
        self.use_async = use_async
        super().__init__()

    def is_running(self):
        return True

    def is_closed(self):
        return False

    def call_soon(self, callback, *args, context=None):
        handle = Handle(callback, args)
        if self.use_async:
            sublime.set_timeout_async(handle, 0)
        else:
            sublime.set_timeout(handle, 0)
        return handle

    def call_later(self, delay, callback, *args, context=None):
        handle = Handle(callback, args)
        delay_ms = max(0, int(delay * 1000))
        if self.use_async:
            sublime.set_timeout_async(handle, delay_ms)
        else:
            sublime.set_timeout(handle, delay_ms)
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

ui_loop = SublimeEventLoop(use_async=False)
worker_loop = SublimeEventLoop(use_async=True)

_thread_local = threading.local()
original_get_running_loop = asyncio.events.get_running_loop
original_get_event_loop = asyncio.events.get_event_loop


def set_event_loop(loop: asyncio.AbstractEventLoop):
    _thread_local.loop = loop


def get_running_loop():
    try:
        return _thread_local.loop
    except AttributeError:
        return original_get_running_loop()


def get_event_loop():
    try:
        return get_running_loop()
    except RuntimeError:
        return original_get_event_loop()


asyncio.events.get_running_loop = get_running_loop
asyncio.events.get_event_loop = get_event_loop


def unpatch_asyncio():
    asyncio.events.get_running_loop = original_get_running_loop
    asyncio.events.get_event_loop = original_get_event_loop


def plugin_loaded():
    sublime.set_timeout(main, 10)

def plugin_unloaded():
    unpatch_asyncio()


# original_get_running_loop = asyncio.events.get_running_loop
# def get_running_loop():
#     return ui_loop if threading.current_thread().name.lower().startswith("m") else worker_loop


# --- Utilities ---

def run_on_ui_loop(fn_or_coro):
    if callable(fn_or_coro):
        @functools.wraps(fn_or_coro)
        def wrapper(*args, **kwargs):
            return asyncio.ensure_future(fn_or_coro(*args, **kwargs), loop=ui_loop)
        return wrapper
    return asyncio.ensure_future(fn_or_coro, loop=ui_loop)

def run_on_worker_loop(fn_or_coro):
    if callable(fn_or_coro):
        @functools.wraps(fn_or_coro)
        def wrapper(*args, **kwargs):
            return asyncio.ensure_future(fn_or_coro(*args, **kwargs), loop=worker_loop)
        return wrapper
    return asyncio.ensure_future(fn_or_coro, loop=worker_loop)

async def switch_to_ui(coro):
    fut = asyncio.Future(loop=ui_loop)

    def _schedule():
        task = asyncio.ensure_future(coro, loop=ui_loop)
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
# from .async_loops import run_on_ui_loop, run_on_worker_loop, switch_to_worker, switch_to_ui
import threading

class example_async(sublime_plugin.TextCommand):
    # def run(self, edit):
    #     # Kick off on the UI loop
    #     print("run")
    #     print(threading.current_thread().name)
    #     run_on_ui_loop(self.run_async)(self.view)

    # async def run_async(self, view):
    @run_on_ui_loop
    async def run(self, view):
        view = self.view
        # Extract view content on UI thread
        content = view.substr(sublime.Region(0, view.size()))
        print("Got content on UI thread")
        print(threading.current_thread().name)

        # Process on worker thread
        processed = await switch_to_worker(self.process_in_background(content))
        print("Got result from worker")
        print(threading.current_thread().name)

        # Draw result on UI thread
        await switch_to_ui(self.draw_result(view, processed))
        print("Finished drawing")
        print(threading.current_thread().name)

    async def process_in_background(self, content):
        print("process_in_background")
        print(threading.current_thread().name)
        await asyncio.sleep(1)  # Simulate heavy work
        await self.still_background()
        return content.upper()[:100]  # Dummy "analysis"

    async def still_background(self):
        print("still_background")
        print(threading.current_thread().name)
        await asyncio.sleep(1)  # Simulate heavy work

    async def draw_result(self, view, result):
        # region = sublime.Region(0, len(result))
        # view.add_regions("example", [region], "string", "", sublime.DRAW_NO_FILL)
        print("draw_result", result[:10])
        print(threading.current_thread().name)


def main():
    print("main")
    w = sublime.active_window()
    v = w.active_view()
    v.run_command("example_async")
