"""Commands whose output takes time -- e.g. ping, one reply per packet.

    run_timed(ctx, steps, finish)

runs `steps`, an iterable of (delay_seconds, action) pairs, one after the
other: each action is called `delay` seconds after the previous one. Then
`finish()` runs -- also when the user stops the job early with Ctrl+C. While
it runs the shell takes no input and holds its prompt back (see
InputHandler.begin_job); it gets the prompt once the job is over.

`steps` can be a generator, so each step can decide its delay from what
happened before (a lost packet waits for the timeout, a reply only for its
round trip). Without an input handler on the context (e.g. a bare test
Context) there's nobody to wait for: everything runs right away."""
from typing import Callable, Iterable

import pyglet

Step = tuple[float, Callable[[], None]]


def run_timed(ctx, steps: Iterable[Step], finish: Callable[[], None] | None = None) -> None:
    steps = iter(steps)
    handler = ctx.input_handler
    if handler is None:
        for _, action in steps:
            action()
        if finish is not None:
            finish()
        return

    pending: dict[str, Callable[[float], None] | None] = {"fire": None}

    def end() -> None:
        if finish is not None:
            finish()
        handler.end_job()

    def schedule_next() -> None:
        step = next(steps, None)
        if step is None:
            pending["fire"] = None
            end()
            return
        delay, action = step

        def fire(dt: float) -> None:
            pending["fire"] = None
            action()
            schedule_next()

        pending["fire"] = fire
        pyglet.clock.schedule_once(fire, max(0.0, delay))

    def cancel() -> None:
        if pending["fire"] is not None:
            pyglet.clock.unschedule(pending["fire"])
            pending["fire"] = None
        ctx.write_line("^C")
        end()

    handler.begin_job(on_cancel=cancel)
    schedule_next()
