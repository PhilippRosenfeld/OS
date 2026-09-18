from horus.display.screen_buffer import ScreenBuffer


def draw_box(buffer: ScreenBuffer, x: int, y: int, width: int, height: int, label: str,
             lines: list[str] = (), selected: bool = False) -> None:
    """Draws a bordered box from (x, y) spanning width x height, with `label`
    embedded in the top border and `lines` inside. Shared by HardwareScreen
    (small tiles) and HardwareDetailScreen (one box filling the screen) so
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
