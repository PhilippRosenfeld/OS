import math
from collections import Counter
from dataclasses import dataclass
from typing import Callable

import pyglet

from horus.display.colors import NAMED_COLORS
from horus.display.screen_buffer import ScreenBuffer
from horus.processes.memory import DISABLED
from horus.ui.box_drawing import draw_box, draw_line_graph
from horus.ui.screen import Screen
from horus.ui.screen_manager import ScreenManager
from horus.ui.screens.settings_screen import SettingOption

key = pyglet.window.key

_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_PROCESS_COLORS = (NAMED_COLORS["cyan"], NAMED_COLORS["magenta"], NAMED_COLORS["white"])
_FREE = "."
_OFF = "x"
_MODULE_ICON_COLS = 5  # ram.png: 32x16 px = 4x1 cells at the base glyph size, plus a gap


@dataclass(frozen=True)
class ModuleView:
    """One RAM module on the RAM screen: slot label (e.g. "DIMM A"), size,
    whether it's on, and how full it is."""
    label: str
    size_kb: int
    enabled: bool
    used_percent: float


class RamScreen(Screen):
    """RAM detail view: `info_fn`'s lines top left, RAM usage over time
    (`history_fn`, in %) as a line graph top right, the memory map along the
    bottom left -- one cell per page (see MemoryManager.page_map), lettered
    and colored per process, '.' for free and 'x' for pages on a disabled
    module, with a legend below (and, from `swapped_fn`, which processes
    have memory in swap -- a fully swapped one has no cell at all) -- and
    on the right the modules (sprite,
    enable/disable toggle, size and fill) above the `options` (memory clock,
    timings, ...).

    Up/Down walk through every module toggle, then every option; Left/Right
    or Enter flips the selected module via `on_toggle_module(index)`,
    Left/Right steps the selected option. Escape goes back. Everything is
    re-read every `refresh_interval` seconds."""

    def __init__(self, buffer: ScreenBuffer, screens: ScreenManager, title: str,
                 info_fn: Callable[[], list[str]], history_fn: Callable[[], list[float]],
                 map_fn: Callable[[], list], names_fn: Callable[[], dict[int, str]],
                 modules_fn: Callable[[], list[ModuleView]], on_toggle_module: Callable[[int], None],
                 options: list[SettingOption] | None = None, refresh_interval: float = 0.5,
                 swapped_fn: Callable[[], list[tuple[str, int]]] | None = None) -> None:
        self._buffer = buffer
        self._screens = screens
        self._title = title
        self._info_fn = info_fn
        self._history_fn = history_fn
        self._map_fn = map_fn
        self._names_fn = names_fn
        self._modules_fn = modules_fn
        self._on_toggle_module = on_toggle_module
        self._swapped_fn = swapped_fn
        self._options = options or []
        self._refresh_interval = refresh_interval
        self._selected = 0
        self._saved_screen: dict | None = None
        self._refresh()

    # --- lifecycle ---

    def on_push(self) -> None:
        self._saved_screen = self._buffer.snapshot()
        self._buffer.cursor_enabled = False
        self._render()
        pyglet.clock.schedule_interval(self._tick, self._refresh_interval)

    def on_pop(self) -> None:
        pyglet.clock.unschedule(self._tick)
        self._buffer.restore(self._saved_screen)

    def _tick(self, dt: float) -> None:
        """Guarded like HardwareScreen._tick."""
        if self._screens.active is not self:
            return
        self._refresh()
        self._render()

    def _refresh(self) -> None:
        self._info = self._info_fn()
        self._history = self._history_fn()
        self._map = self._map_fn()
        self._names = self._names_fn()
        self._modules = self._modules_fn()
        self._swapped = self._swapped_fn() if self._swapped_fn is not None else []
        self._selected = min(self._selected, max(0, self._item_count() - 1))

    def _item_count(self) -> int:
        return len(self._modules) + len(self._options)

    # --- layout ---

    def _render(self) -> None:
        self._buffer.clear()
        cols, rows = self._buffer.cols, self._buffer.rows
        top_height = rows // 2
        bottom_height = rows - top_height
        info_width = max(30, cols * 2 // 5)
        side_width = max(30, cols * 2 // 5)  # wide enough for "DIMM A  < Disabled >" next to the sprite
        map_width = cols - side_width
        modules_height = min(max(0, bottom_height - 4), 3 + 2 * len(self._modules))

        draw_box(self._buffer, 0, 0, info_width, top_height, self._title, self._info)
        draw_line_graph(self._buffer, info_width, 0, cols - info_width, top_height, "Memory Usage",
                        self._history, y_label="RAM", unit="%", markers=[0.0, 100.0])
        self._render_map(0, top_height, map_width, bottom_height)
        self._render_modules(map_width, top_height, side_width, modules_height)
        self._render_options(map_width, top_height + modules_height, side_width, bottom_height - modules_height)

    def _letters(self) -> dict[int, tuple[str, tuple[int, int, int]]]:
        """A letter and color per process present in the map, in PID order."""
        pids = sorted({owner for owner in self._map if isinstance(owner, int)})
        return {pid: (_LETTERS[i % len(_LETTERS)], _PROCESS_COLORS[i % len(_PROCESS_COLORS)])
                for i, pid in enumerate(pids)}

    def _render_map(self, x: int, y: int, width: int, height: int) -> None:
        """One cell per page, or -- if the map doesn't fit -- per group of
        pages, showing whichever owner holds most of the group."""
        per_row = max(0, width - 4)
        letters = self._letters()
        legend = self._legend_lines(letters, per_row)
        legend_rows = len(legend) + (1 if self._swapped else 0)
        grid_rows = max(0, height - 3 - legend_rows)  # border, padding row, and the legend rows
        group = max(1, math.ceil(len(self._map) / (per_row * grid_rows))) if per_row and grid_rows else 1
        draw_box(self._buffer, x, y, width, height, "Memory Map" + (f" (1 cell = {group} pages)" if group > 1 else ""))
        if not per_row or not grid_rows or not self._map:
            return
        cells = [Counter(self._map[i:i + group]).most_common(1)[0][0] for i in range(0, len(self._map), group)]
        for index, owner in enumerate(cells):
            row, col = divmod(index, per_row)
            if row >= grid_rows:
                break
            if owner == DISABLED:
                char, color = _OFF, NAMED_COLORS["amber"]
            elif owner is None:
                char, color = _FREE, None
            else:
                char, color = letters.get(owner, ("?", None))
            self._buffer.write_string(x + 2 + col, y + 2 + row, char, fg=color)

        first_legend_row = y + height - 1 - legend_rows
        for line_index, line in enumerate(legend):
            column = x + 2
            for letter, color, text in line:
                self._buffer.write_string(column, first_legend_row + line_index, letter, fg=color)
                self._buffer.write_string(column + 1, first_legend_row + line_index, text)
                column += 1 + len(text)
        if self._swapped:
            swap_line = "In swap: " + ", ".join(f"{name} {kb} KB" for name, kb in self._swapped)
            self._buffer.write_string(x + 2, y + height - 2, swap_line[:per_row], fg=NAMED_COLORS["amber"])

    def _legend_lines(self, letters: dict, width: int) -> list[list[tuple[str, tuple | None, str]]]:
        """The legend entries ("A init", ..., ". free", "x off"), wrapped
        onto as many lines as the map's width needs -- each entry a
        (letter, its color, rest of the text incl. trailing gap)."""
        entries = [(letter, color, f" {self._names.get(pid, pid)}  ") for pid, (letter, color) in letters.items()]
        entries += [(_FREE, None, " free  "), (_OFF, NAMED_COLORS["amber"], " off")]
        lines, line, used = [], [], 0
        for entry in entries:
            length = 1 + len(entry[2])
            if line and used + length > width:
                lines.append(line)
                line, used = [], 0
            line.append(entry)
            used += length
        if line:
            lines.append(line)
        return lines

    def _render_modules(self, x: int, y: int, width: int, height: int) -> None:
        draw_box(self._buffer, x, y, width, height, "Modules")
        text_x = x + 2 + _MODULE_ICON_COLS
        text_width = max(0, x + width - 2 - text_x)
        for i, module in enumerate(self._modules):
            row = y + 2 + i * 2
            if row + 1 >= y + height - 1:
                break
            self._buffer.place_sprite(x + 2, row, "ram")
            toggle = "< Enabled >" if module.enabled else "< Disabled >"
            self._buffer.write_string(text_x, row, f"{module.label}  "[:text_width])
            toggle_x = text_x + len(module.label) + 2
            room = max(0, text_width - len(module.label) - 2)
            if i == self._selected:
                self._buffer.write_string(toggle_x, row, toggle[:room], fg=self._buffer.default_bg, bg=self._buffer.default_fg)
            else:
                self._buffer.write_string(toggle_x, row, toggle[:room])
            detail = (f"{module.size_kb // 1024} MB  {module.used_percent:.0f}% used" if module.enabled
                      else f"{module.size_kb // 1024} MB  off")
            self._buffer.write_string(text_x, row + 1, detail[:text_width],
                                      fg=None if module.enabled else NAMED_COLORS["amber"])

    def _render_options(self, x: int, y: int, width: int, height: int) -> None:
        draw_box(self._buffer, x, y, width, height, "Options")
        interior = max(0, width - 4)
        for i, option in enumerate(self._options):
            row = y + 2 + i
            if row >= y + height - 1:
                break
            label = f"{option.label}: "
            value = f"< {option.get_value()} >" if option.get_value else ""
            self._buffer.write_string(x + 2, row, label[:interior])
            room = max(0, interior - len(label))
            if len(self._modules) + i == self._selected:
                self._buffer.write_string(x + 2 + len(label), row, value[:room], fg=self._buffer.default_bg, bg=self._buffer.default_fg)
            else:
                self._buffer.write_string(x + 2 + len(label), row, value[:room])

    # --- input ---

    def _activate(self, direction: int) -> None:
        if self._selected < len(self._modules):
            self._on_toggle_module(self._selected)
        elif self._options:
            option = self._options[self._selected - len(self._modules)]
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
        if self._selected < len(self._modules):
            self._activate(1)

    def handle_key(self, symbol: int, modifiers: int) -> None:
        if symbol == key.ESCAPE:
            self._screens.pop()
