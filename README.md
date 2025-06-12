Yet another asyncio implementation

After staring at @daveleroy's https://github.com/daveleroy/SublimeDebugger plus
what got posted on https://github.com/sublimehq/sublime_text/issues/3129

The idea is that we run one pseudo-eventloop per Sublime thread and allow switching
between them.

E.g.

```python
    @run_on_ui_loop
    async def run(self, view):
        view = self.view
        content = view.substr(sublime.Region(0, view.size()))
        processed = await switch_to_worker(self.process_in_background(content))
        print("Got result from worker", processed)

    async def process_in_background(self, content):
        await asyncio.sleep(1)  # Simulate heavy work
        return content.upper()[:10]  # Dummy "analysis"
```

Four utility functions: `run_on_ui_loop`, `run_on_worker_loop` to lift coroutines
into an event loop; and `switch_to_ui` and `switch_to_worker` to switch the event
loops.

If you load the package as a plugin, two things should run "at the same time":
(1) an animated `quick_panel`, (2) a heavy `TextCommand` which prints to the console.



