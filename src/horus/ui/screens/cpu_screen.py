import math
from dataclasses import dataclass
from typing import Callable

import pyglet

from horus.display.colors import NAMED_COLORS
from horus.display.screen_buffer import ScreenBuffer
from horus.hardware.cpu import CoreState
from horus.ui.box_drawing import draw_box
from horus.ui.screen import Screen
from horus.ui.screen_manager import ScreenManager
from horus.ui.screens.settings_screen import SettingOption

key = pyglet.window.key

MAX_SHOWN_CORES = 8
CORE_SPRITE_FRAMES = 8  # core_0.png .. core_7.png, see scripts/generate_core_sprites.py

# Grid space one core takes in the cores box: the sprite (32x32 px = 4x2
# cells at the base 8x16 glyph size -- sprites scale along with the glyph
# size, see Renderer._sprite_scale) plus a 1-col gap, and a spacer row below.
_CORE_ICON_COLS = 5
_CORE_ROWS = 3

LAMP_COLORS = {
    CoreState.WORKING: NAMED_COLORS["cyan"],
    CoreState.DISABLED: NAMED_COLORS["amber"],
    CoreState.STANDBY: NAMED_COLORS["green"],
}
_LAMP = "■"  # ■ -- exists in the CP437 VGA font
_DISABLED_MARK = "-"  # a column where the core was mostly disabled; never-working columns stay blank
# One chart column can span several samples (see TIMESCALES) -- how much of
# that time the core was working picks the shade, up to fully filled.
_SHADES = ("░", "▒", "▓", "█")  # ░ ▒ ▓ █

# (label, seconds) the activity chart can span, cycled with Left/Right on
# the option below it -- the first one is the default.
TIMESCALES = [("20 s", 20), ("1 min", 60), ("3 min", 180)]


@dataclass(frozen=True)
class CoreView:
    """What the CPU screen shows for one core: its label (e.g. "Core 1"),
    its state, and -- while working -- the process it's working on."""
    label: str
    state: CoreState
    process: str | None = None
    history: tuple[CoreState, ...] = ()  # past states, oldest first (see CpuCore.history)


class CpuScreen(Screen):
    """CPU detail view: `info_fn`'s lines top left, an activity chart top
    right (one row per core with its status lamp -- cyan = working, amber
    = disabled, green = standby -- then filled wherever it was working over
    the selected timescale, see _render_history), and along the bottom every core (up to
    MAX_SHOWN_CORES) in rows of two -- its sprite, which spins while the core
    is working and stands still otherwise, what it's doing, and an
    enable/disable toggle right next to it -- with CPU-wide `options` (e.g.
    overclocking all cores) in their own box on the far right.

    Up/Down walk through every selectable item (the chart's timescale, each
    core's toggle, then each option -- starting on the first core);
    Left/Right or Enter flips the selected core's toggle via
    `on_toggle_core(index)`, Left/Right steps the timescale or the selected
    option. Escape goes back. `info_fn`/`cores_fn` are re-read every
    `refresh_interval` seconds; the sprites animate on their own faster
    `animation_interval`. `sample_interval` is how many seconds apart the
    samples in CoreView.history are (the CpuScheduler's tick)."""

    def __init__(self, buffer: ScreenBuffer, screens: ScreenManager, title: str,
                 info_fn: Callable[[], list[str]], cores_fn: Callable[[], list[CoreView]],
                 on_toggle_core: Callable[[int], None], options: list[SettingOption] | None = None,
                 refresh_interval: float = 0.5, animation_interval: float = 0.1,
                 sample_interval: float = 0.5) -> None:
        self._buffer = buffer
        self._screens = screens
        self._title = title
        self._info_fn = info_fn
        self._cores_fn = cores_fn
        self._on_toggle_core = on_toggle_core
        self._options = options or []
        self._refresh_interval = refresh_interval
        self._animation_interval = animation_interval
        self._info = info_fn()
        self._cores = cores_fn()[:MAX_SHOWN_CORES]
        self._sample_interval = sample_interval
        self._timescale = 0  # index into TIMESCALES
        self._selected = 1 if self._cores else 0  # item 0 is the timescale, cores start at 1
        self._frame = 0
        self._sprite_anchors: dict[int, tuple[int, int]] = {}  # core index -> where its sprite was placed
        self._saved_screen: dict | None = None

    # --- lifecycle ---

    def on_push(self) -> None:
        self._saved_screen = self._buffer.snapshot()
        self._buffer.cursor_enabled = False
        self._render()
        pyglet.clock.schedule_interval(self._tick, self._refresh_interval)
        pyglet.clock.schedule_interval(self._animate, self._animation_interval)

    def on_pop(self) -> None:
        pyglet.clock.unschedule(self._tick)
        pyglet.clock.unschedule(self._animate)
        self._buffer.restore(self._saved_screen)

    def _tick(self, dt: float) -> None:
        """Guarded like HardwareScreen._tick -- something pushed on top from
        outside (e.g. a CrashScreen) must not get drawn over."""
        if self._screens.active is not self:
            return
        self._refresh()
        self._render()

    def _animate(self, dt: float) -> None:
        """Advances the spinning sprites of working cores by one frame --
        only re-places those sprites, no full re-render."""
        if self._screens.active is not self:
            return
        self._frame = (self._frame + 1) % CORE_SPRITE_FRAMES
        for index, anchor in self._sprite_anchors.items():
            if self._cores[index].state == CoreState.WORKING:
                self._buffer.place_sprite(*anchor, f"core_{self._frame}")

    def _refresh(self) -> None:
        self._info = self._info_fn()
        self._cores = self._cores_fn()[:MAX_SHOWN_CORES]
        self._selected = min(self._selected, max(0, self._item_count() - 1))

    # --- layout ---

    # selectable items, in Up/Down order: 0 = timescale, then one per core,
    # then one per option

    def _item_count(self) -> int:
        return 1 + len(self._cores) + len(self._options)

    def _core_item(self, index: int) -> int:
        return 1 + index

    def _option_item(self, index: int) -> int:
        return 1 + len(self._cores) + index

    def _render(self) -> None:
        # clear() also resets _writes and sprites -- everything is re-placed below
        self._buffer.clear()
        self._sprite_anchors = {}
        cols, rows = self._buffer.cols, self._buffer.rows

        core_rows = -(-len(self._cores) // 2)
        # borders + top padding + every core row, minus the last one's spacer row
        bottom_height = min(max(0, rows - 6), 2 + core_rows * _CORE_ROWS)
        top_height = rows - bottom_height
        info_width = cols // 2
        options_width = max(24, cols // 4)
        cores_width = cols - options_width

        draw_box(self._buffer, 0, 0, info_width, top_height, self._title, self._info)
        self._render_history(info_width, 0, cols - info_width, top_height)
        self._render_cores(0, top_height, cores_width, bottom_height)
        self._render_options(cores_width, top_height, options_width, bottom_height)

    def _render_history(self, x: int, y: int, width: int, height: int) -> None:
        """Activity chart: one row per core -- its current-state lamp and
        label, then its history over the selected timescale (see TIMESCALES),
        spread across the full chart width, newest on the right ("now").
        Each column covers its share of that time span: shaded by how much
        of it the core was working (░ ▒ ▓ up to a solid █), a dim amber dash
        where it was mostly disabled, blank where it was idle -- or where
        there's no history that far back yet. The timescale option sits in
        the box's bottom border, right under the chart."""
        draw_box(self._buffer, x, y, width, height, "Core Activity History")
        self._render_timescale_option(x, y + height - 1, width)

        label_width = max((len(core.label) for core in self._cores), default=0)
        chart_x = x + 2 + 2 + label_width + 1              # lamp, space, label, space
        chart_width = max(0, (x + width - 2) - chart_x)
        window = max(1, round(TIMESCALES[self._timescale][1] / self._sample_interval))
        for i, core in enumerate(self._cores):
            row = y + 1 + i
            if row >= y + height - 1:
                break
            self._buffer.write_string(x + 2, row, _LAMP, fg=LAMP_COLORS[core.state])
            self._buffer.write_string(x + 4, row, core.label)
            for column, bucket in enumerate(self._buckets(core.history, window, chart_width)):
                cell = self._chart_cell(bucket)
                if cell is not None:
                    self._buffer.write_string(chart_x + column, row, cell[0], fg=cell[1])

    def _render_timescale_option(self, x: int, row: int, width: int) -> None:
        """" Timescale: < 20 s > " on the left of the chart's bottom border
        (value highlighted while selected), " now " on its right."""
        now = " now "
        if width > len(now) + 4:
            self._buffer.write_string(x + width - len(now) - 2, row, now)
        prefix = " Timescale: "
        value = f"< {TIMESCALES[self._timescale][0]} >"
        if width < len(prefix) + len(value) + len(now) + 6:
            return
        self._buffer.write_string(x + 2, row, prefix)
        if self._selected == 0:
            self._buffer.write_string(x + 2 + len(prefix), row, value, fg=self._buffer.default_bg, bg=self._buffer.default_fg)
        else:
            self._buffer.write_string(x + 2 + len(prefix), row, value)
        self._buffer.write_string(x + 2 + len(prefix) + len(value), row, " ")

    @staticmethod
    def _buckets(history: tuple[CoreState, ...], window: int, columns: int) -> list[list[CoreState]]:
        """Splits the last `window` samples of `history` into `columns`
        consecutive buckets (oldest first, newest last) -- as evenly as they
        divide; with fewer samples than columns, one sample shows in several
        columns. Samples older than what history holds come out as empty
        buckets on the left."""
        if columns <= 0:
            return []
        samples = list(history)[-window:]
        missing = window - len(samples)
        buckets = []
        for column in range(columns):
            lo = column * window // columns
            hi = max(lo + 1, (column + 1) * window // columns)
            buckets.append([samples[i - missing] for i in range(lo, hi) if i >= missing])
        return buckets

    @staticmethod
    def _chart_cell(bucket: list[CoreState]) -> tuple[str, tuple[int, int, int]] | None:
        if not bucket:
            return None
        working = sum(state == CoreState.WORKING for state in bucket) / len(bucket)
        disabled = sum(state == CoreState.DISABLED for state in bucket) / len(bucket)
        if disabled > 0.5:
            return _DISABLED_MARK, LAMP_COLORS[CoreState.DISABLED]
        if working <= 0:
            return None
        shade = _SHADES[min(len(_SHADES) - 1, max(0, math.ceil(working * len(_SHADES)) - 1))]
        return shade, LAMP_COLORS[CoreState.WORKING]

    def _render_cores(self, x: int, y: int, width: int, height: int) -> None:
        """Two cores per row: sprite, then "Core N  < Enabled >" (the toggle,
        highlighted while selected) and below it what the core is doing."""
        draw_box(self._buffer, x, y, width, height, "Core Activity")
        cell_width = max(1, (width - 4) // 2)
        for i, core in enumerate(self._cores):
            col, row = i % 2, i // 2
            cx, cy = x + 2 + col * cell_width, y + 2 + row * _CORE_ROWS
            if cy + 2 > y + height - 1:
                break
            frame = self._frame if core.state == CoreState.WORKING else 0
            self._buffer.place_sprite(cx, cy, f"core_{frame}")
            self._sprite_anchors[i] = (cx, cy)

            text_x = cx + _CORE_ICON_COLS
            text_width = max(0, cell_width - _CORE_ICON_COLS - 1)
            toggle = "< Enabled >" if core.state != CoreState.DISABLED else "< Disabled >"
            self._buffer.write_string(text_x, cy, f"{core.label}  "[:text_width])
            toggle_x = text_x + len(core.label) + 2
            toggle_room = max(0, text_width - len(core.label) - 2)
            if self._core_item(i) == self._selected:
                self._buffer.write_string(toggle_x, cy, toggle[:toggle_room],
                                          fg=self._buffer.default_bg, bg=self._buffer.default_fg)
            else:
                self._buffer.write_string(toggle_x, cy, toggle[:toggle_room])
            self._buffer.write_string(text_x, cy + 1, self._activity(core)[:text_width],
                                      fg=LAMP_COLORS[core.state])

    @staticmethod
    def _activity(core: CoreView) -> str:
        if core.state == CoreState.WORKING and core.process:
            return f"Working: {core.process}"
        return core.state.value

    def _render_options(self, x: int, y: int, width: int, height: int) -> None:
        draw_box(self._buffer, x, y, width, height, "Options")
        interior_width = max(0, width - 4)
        for i, option in enumerate(self._options):
            row = y + 2 + i * 2
            if row >= y + height - 1:
                break
            selected = self._option_item(i) == self._selected
            self._buffer.write_string(x + 2, row, option.label[:interior_width])
            value = f"< {option.get_value()} >"[:interior_width] if option.get_value else ""
            if selected:
                self._buffer.write_string(x + 2, row + 1, value, fg=self._buffer.default_bg, bg=self._buffer.default_fg)
            else:
                self._buffer.write_string(x + 2, row + 1, value)

    # --- input ---

    def _activate(self, direction: int) -> None:
        """Steps the timescale, toggles the selected core, or steps the
        selected option left (-1) / right (+1) -- then re-reads state so
        the change shows immediately."""
        if self._selected == 0:
            self._timescale = (self._timescale + direction) % len(TIMESCALES)
        elif self._selected <= len(self._cores):
            self._on_toggle_core(self._selected - 1)
        else:
            option = self._options[self._selected - 1 - len(self._cores)]
            handler = option.on_left if direction < 0 else option.on_right
            if handler is not None:
                handler()
        self._refresh()
        self._render()

    def handle_text(self, text: str) -> None:
        pass

    def handle_motion(self, motion: int) -> None:
        count = self._item_count()
        if count == 0:
            return
        if motion == key.MOTION_UP:
            self._selected = (self._selected - 1) % count
            self._render()
        elif motion == key.MOTION_DOWN:
            self._selected = (self._selected + 1) % count
            self._render()
        elif motion == key.MOTION_LEFT:
            self._activate(-1)
        elif motion == key.MOTION_RIGHT:
            self._activate(1)

    def handle_enter(self) -> None:
        if self._selected <= len(self._cores):   # timescale or a core toggle
            self._activate(1)
        else:
            option = self._options[self._selected - 1 - len(self._cores)]
            if option.on_select is not None:
                option.on_select()
                self._refresh()
                self._render()

    def handle_key(self, symbol: int, modifiers: int) -> None:
        if symbol == key.ESCAPE:
            self._screens.pop()
