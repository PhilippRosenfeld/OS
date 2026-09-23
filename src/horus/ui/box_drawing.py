from horus.display.screen_buffer import ScreenBuffer


def draw_box(buffer: ScreenBuffer, x: int, y: int, width: int, height: int, label: str,
             lines: list[str] = (), selected: bool = False) -> None:
    """Draws a bordered box from (x, y) spanning width x height, with `label`
    embedded in the top border and `lines` inside. Shared by HardwareScreen
    (small tiles) and DetailScreen (one box filling the screen) so
    the two don't drift apart.

    Every written string is clipped to the box's own width first --
    ScreenBuffer.write_string wraps at the *buffer's* width when a string
    runs past it, not at any box boundary, so an unclipped line would bleed
    into the next row instead of just being cut off."""
    if width < 2 or height < 2:
        return  # too small to even draw a border in
    fg = buffer.default_bg if selected else None
    bg = buffer.default_fg if selected else None

    border = f"+{'-' * (width - 2)}+"
    buffer.write_string(x, y, border, fg=fg, bg=bg)
    for row in range(y + 1, y + height - 1):
        buffer.write_string(x, row, "|", fg=fg, bg=bg)
        buffer.write_string(x + width - 1, row, "|", fg=fg, bg=bg)
    buffer.write_string(x, y + height - 1, border, fg=fg, bg=bg)

    label_text = f" {label} "[:max(0, width - 2)]
    if label_text:
        buffer.write_string(x + 1, y, label_text, fg=fg, bg=bg)

    interior_width = max(0, width - 4)
    for i, line in enumerate(lines):
        row = y + 2 + i
        if row >= y + height - 1:
            break
        buffer.write_string(x + 2, row, line[:interior_width])


def draw_line_graph(buffer: ScreenBuffer, x: int, y: int, width: int, height: int,
                     label: str, values: list[float], y_label: str = "Value", unit: str = "",
                     markers: list[float] | None = None) -> None:
    """Draws a bordered box exactly like draw_box, but plots `values` (oldest
    first, e.g. MetricHistory.values()) as a simple ASCII line graph filling
    its interior instead of showing them as text lines -- one '*' per sample,
    normalized between the shown samples' own min and max (extended to also
    cover every value in `markers`, if given -- see below). `y_label` runs
    down the left edge one letter per row; the x-axis is always "Time" since
    every value comes from a MetricHistory, which is always a time series.

    Right-aligned: the newest sample always lands in the very last (right
    edge) column, with older ones filling in leftward from it -- both while
    there isn't enough data yet to fill the whole width (unused columns
    stay blank on the *left*, not the right) and once there's more data
    than fits (the oldest one falls off the left edge instead of the
    window just growing). Re-sliced from scratch on every call, so this
    "always show values[-plot_width:], right-aligned" rule *is* the scroll
    -- there's no separate scrolling state, it's purely a side effect of the
    caller re-rendering on a live tick (see DetailScreen).

    `markers`, if given, draws each one as a dotted horizontal reference
    line (e.g. a warning/critical threshold) labeled with its own value,
    UNDER the data points -- also stretching the y-axis scale to include
    them even if no sample has reached that value yet, so e.g. a "90"
    threshold line is visible well before the plotted series ever gets
    that high.

    Whenever there's at least one sample, the latest one (values[-1] --
    MetricHistory.values() is oldest first) is also written into the top
    border just after `label`, suffixed with `unit` (e.g. "C" or "W"), so
    the current reading is visible at a glance without having to read it
    off the plot itself."""
    draw_box(buffer, x, y, width, height, label)
    if values:
        label_text = f" {label} "[:max(0, width - 2)]
        start_col = x + 1 + len(label_text)
        max_len = max(0, (x + width - 1) - start_col)
        if max_len > 0:
            buffer.write_string(start_col, y, f"|{values[-1]:.1f}{unit}|"[:max_len])

    interior_width = width - 4
    interior_height = height - 3
    if interior_width < 3 or interior_height < 3:
        return  # too small for a y-axis label column + gap + x-axis label row + at least one plot cell

    label_col = x + 2
    x_axis_row = y + 2 + interior_height - 1
    for i, ch in enumerate(y_label):
        row = y + 2 + i
        if row >= x_axis_row:
            break
        buffer.write_string(label_col, row, ch)

    # label_col + 1 is left blank -- a one-column gap between the y-axis
    # label and the plot area/marker lines, so they don't run into it.
    plot_x, plot_y = label_col + 2, y + 2
    plot_width, plot_height = interior_width - 2, interior_height - 1

    x_label = "Time"[:plot_width]
    buffer.write_string(plot_x + max(0, (plot_width - len(x_label)) // 2), x_axis_row, x_label)

    shown = values[-plot_width:] if values else []
    scale_values = list(shown) + list(markers or [])
    if not scale_values:
        buffer.write_string(plot_x, plot_y, "No data yet"[:plot_width])
        return

    min_v, max_v = min(scale_values), max(scale_values)
    span = max_v - min_v

    def _row_for(value: float) -> int:
        frac = 0.5 if span == 0 else (value - min_v) / span
        return round((1 - frac) * (plot_height - 1)) if plot_height > 1 else 0

    for marker in (markers or []):
        marker_line = (f"{marker:g}" + "." * plot_width)[:plot_width]
        buffer.write_string(plot_x, plot_y + _row_for(marker), marker_line)

    offset = plot_width - len(shown)  # right-align: the newest sample (last in `shown`) always
                                       # ends up at column plot_width - 1, the rightmost one
    for i, value in enumerate(shown):
        buffer.write_string(plot_x + offset + i, plot_y + _row_for(value), "*")


def draw_bar_chart(buffer: ScreenBuffer, x: int, y: int, width: int, height: int,
                    bars: list[tuple[str, float]]) -> None:
    """Draws a simple ASCII vertical bar chart filling the given rectangle --
    no border of its own, unlike draw_line_graph; meant to sit inside a
    region the caller already bordered (e.g. one half of a draw_box'd
    panel). One column-group per (label, value) pair in `bars`, its height
    proportional to its value relative to the largest one shown (an
    all-zero chart draws no bars, not a row of full-height ones); the
    bottom row holds each bar's own label, truncated/centered to its
    column's width."""
    if not bars or width < len(bars) or height < 2:
        return
    col_width = max(1, width // len(bars))
    plot_height = height - 1  # bottom row reserved for labels
    if plot_height < 1:
        return
    max_value = max(value for _, value in bars)
    for i, (label, value) in enumerate(bars):
        bar_x = x + i * col_width
        bar_width = max(1, col_width - 1)  # 1-column gap between bars
        frac = (value / max_value) if max_value > 0 else 0.0
        bar_height = round(frac * plot_height)
        for row_offset in range(bar_height):
            row = y + plot_height - 1 - row_offset
            buffer.write_string(bar_x, row, "#" * bar_width)
        buffer.write_string(bar_x, y + height - 1, label[:bar_width].center(bar_width))
