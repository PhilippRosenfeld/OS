import struct

import moderngl
import pytest

from horus.display.font_atlas import FontAtlas, FontRegistry
from horus.display.renderer import Renderer
from horus.display.screen_buffer import Cell, ScreenBuffer
from horus.display.window import DisplayWindow

FONT = "Px437_IBM_VGA_8x16.ttf"


def make_atlas(char_width=8, char_height=16):
    return FontAtlas(FONT, char_width, char_height)


def make_renderer(cols=10, rows=5, char_width=8, char_height=16):
    buffer = ScreenBuffer(cols, rows)
    atlas = make_atlas(char_width, char_height)
    ctx = moderngl.create_context(standalone=True)
    return Renderer(buffer, atlas, ctx), buffer, atlas


def test_display_window_initialization():
    window = DisplayWindow(font_path=FONT, cols=80, rows=25, title="Test Window", char_width=8, char_height=16, width=640, height=400)
    try:
        assert window.buffer.cols == 80
        assert window.buffer.rows == 25
        assert window._char_width == 8
        assert window._char_height == 16
        assert window._window.width == 640
        assert window._window.height == 400
        assert window._window.caption == "Test Window"
    finally:
        window._window.close()


def test_display_window_auto_computes_cols_rows_with_margin():
    window = DisplayWindow(font_path=FONT, char_width=8, char_height=16, width=640, height=400, margin=16)
    try:
        assert window.buffer.cols == (640 - 32) // 8
        assert window.buffer.rows == (400 - 32) // 16
    finally:
        window._window.close()


def test_on_resize_recomputes_grid_size():
    window = DisplayWindow(font_path=FONT, char_width=8, char_height=16, width=640, height=400, margin=0)
    try:
        window._on_resize(320, 160)
        assert window.buffer.cols == 40
        assert window.buffer.rows == 10
    finally:
        window._window.close()


def test_set_char_size_rebuilds_atlas_and_refits_grid():
    window = DisplayWindow(font_path=FONT, char_width=8, char_height=16, width=320, height=160, margin=0)
    try:
        window.set_char_size(16, 32)
        assert window.char_width == 16
        assert window.char_height == 32
        assert window._renderer.font_atlas.char_width == 16
        assert window._renderer.font_atlas.char_height == 32
        assert window.buffer.cols == 320 // 16
        assert window.buffer.rows == 160 // 32
    finally:
        window._window.close()


def test_set_font_swaps_atlas_without_changing_grid_size():
    window = DisplayWindow(font_path=FONT, char_width=8, char_height=16, width=320, height=160, margin=0)
    try:
        cols_before, rows_before = window.buffer.cols, window.buffer.rows
        window.set_font("Terminus (TTF) 500.ttf")
        assert window.font_path == "Terminus (TTF) 500.ttf"
        assert window._renderer.font_atlas.font_path.name == "Terminus (TTF) 500.ttf"
        assert window.buffer.cols == cols_before
        assert window.buffer.rows == rows_before
    finally:
        window._window.close()


def test_set_window_size_resizes_window_and_refits_grid():
    window = DisplayWindow(font_path=FONT, char_width=8, char_height=16, width=320, height=160, margin=0)
    try:
        window.set_window_size(640, 320)
        assert window.window_size == (640, 320)
        assert window.buffer.cols == 640 // 8
        assert window.buffer.rows == 320 // 16
    finally:
        window._window.close()


def test_close_closes_the_underlying_window():
    """Regression test: DisplayWindow.close() didn't exist at all, so any
    caller (e.g. an 'Exit' menu option) crashed with AttributeError."""
    window = DisplayWindow(font_path=FONT, char_width=8, char_height=16, width=320, height=160, margin=0)
    window.close()  # should not raise
    assert window._window.context is None  # pyglet clears this on close


# --- ScreenBuffer ---

def test_screen_buffer_starts_blank_and_dirty():
    buffer = ScreenBuffer(5, 2)
    assert buffer.dirty is True
    assert buffer.get_cell(0, 0) == Cell(fg_color=buffer.default_fg, bg_color=buffer.default_bg)


def test_write_string_fills_cells():
    buffer = ScreenBuffer(5, 2)
    buffer.write_string(0, 0, "abc", fg=(1, 2, 3), bg=(4, 5, 6))
    assert buffer.get_cell(0, 0).char == "a"
    assert buffer.get_cell(1, 0).char == "b"
    assert buffer.get_cell(2, 0).char == "c"
    assert buffer.get_cell(2, 0).fg_color == (1, 2, 3)
    assert buffer.get_cell(2, 0).bg_color == (4, 5, 6)
    assert buffer.get_cell(3, 0).char == " "


def test_write_string_marks_dirty():
    buffer = ScreenBuffer(5, 2)
    buffer.dirty = False
    buffer.write_string(0, 0, "x")
    assert buffer.dirty is True


def test_write_string_wraps_to_next_row_instead_of_truncating():
    buffer = ScreenBuffer(3, 2)
    buffer.write_string(0, 0, "ABCDEF")
    assert "".join(buffer.get_cell(c, 0).char for c in range(3)) == "ABC"
    assert "".join(buffer.get_cell(c, 1).char for c in range(3)) == "DEF"


def test_write_string_drops_overflow_beyond_available_rows():
    buffer = ScreenBuffer(3, 1)
    buffer.write_string(0, 0, "ABCDEF")
    assert "".join(buffer.get_cell(c, 0).char for c in range(3)) == "ABC"


def test_resize_rewraps_content_without_losing_it():
    buffer = ScreenBuffer(30, 1)
    buffer.write_string(0, 0, "ABCDEFGHIJKLMNOPQRSTUVWXYZ1234")

    buffer.resize(10, 3)
    assert "".join(buffer.get_cell(c, 0).char for c in range(10)) == "ABCDEFGHIJ"
    assert "".join(buffer.get_cell(c, 2).char for c in range(10)) == "UVWXYZ1234"

    buffer.resize(30, 1)
    assert "".join(buffer.get_cell(c, 0).char for c in range(30)) == "ABCDEFGHIJKLMNOPQRSTUVWXYZ1234"


def test_resize_survives_temporarily_too_small_grid():
    buffer = ScreenBuffer(30, 1)
    buffer.write_string(0, 0, "ABCDEFGHIJKLMNOPQRSTUVWXYZ1234")

    buffer.resize(10, 1)  # only "ABCDEFGHIJ" fits, rest has nowhere to wrap to
    buffer.resize(30, 1)
    assert "".join(buffer.get_cell(c, 0).char for c in range(30)) == "ABCDEFGHIJKLMNOPQRSTUVWXYZ1234"


def test_resize_marks_dirty():
    buffer = ScreenBuffer(5, 2)
    buffer.dirty = False
    buffer.resize(6, 2)
    assert buffer.dirty is True


def test_scroll_up_shifts_rows():
    buffer = ScreenBuffer(3, 2)
    buffer.write_string(0, 0, "AAA")
    buffer.write_string(0, 1, "BBB")
    buffer.scroll("u", 1)
    assert "".join(buffer.get_cell(c, 0).char for c in range(3)) == "BBB"
    assert "".join(buffer.get_cell(c, 1).char for c in range(3)) == "   "


def test_scroll_invalid_direction_raises():
    buffer = ScreenBuffer(3, 2)
    with pytest.raises(ValueError):
        buffer.scroll("x", 1)


def test_clear_resets_cells_and_write_history():
    buffer = ScreenBuffer(3, 2)
    buffer.write_string(0, 0, "AAA")
    buffer.clear()
    assert buffer.get_cell(0, 0).char == " "
    buffer.resize(3, 2)  # replays write history; should stay blank since it was cleared
    assert buffer.get_cell(0, 0).char == " "


# --- ScreenBuffer: scrollback / colors ---

def test_scroll_up_moves_pushed_rows_into_scrollback():
    buffer = ScreenBuffer(3, 2)
    buffer.write_string(0, 0, "AAA")
    buffer.write_string(0, 1, "BBB")
    buffer.scroll("u", 1)
    assert len(buffer._scrollback) == 1
    assert "".join(c.char for c in buffer._scrollback[0]) == "AAA"


def test_get_cell_reads_from_scrollback_when_view_offset_set():
    buffer = ScreenBuffer(3, 2)
    buffer.write_string(0, 0, "AAA")
    buffer.write_string(0, 1, "BBB")
    buffer.scroll("u", 1)  # "AAA" -> scrollback, live becomes ["BBB", blank]
    buffer.scroll_view(1)
    assert "".join(buffer.get_cell(c, 0).char for c in range(3)) == "AAA"
    assert "".join(buffer.get_cell(c, 1).char for c in range(3)) == "BBB"


def test_scroll_view_clamps_to_available_history():
    buffer = ScreenBuffer(3, 2)
    buffer.write_string(0, 0, "AAA")
    buffer.scroll("u", 1)
    buffer.scroll_view(100)
    assert buffer.view_offset == len(buffer._scrollback)
    buffer.scroll_view(-100)
    assert buffer.view_offset == 0


def test_write_string_resets_view_offset_to_live():
    buffer = ScreenBuffer(3, 2)
    buffer.write_string(0, 0, "AAA")
    buffer.scroll("u", 1)
    buffer.scroll_view(1)
    assert buffer.view_offset != 0
    buffer.write_string(0, 0, "X")
    assert buffer.view_offset == 0


def test_resize_clears_scrollback():
    buffer = ScreenBuffer(3, 2)
    buffer.write_string(0, 0, "AAA")
    buffer.scroll("u", 1)
    assert len(buffer._scrollback) == 1
    buffer.resize(3, 2)
    assert buffer._scrollback == []


def test_clear_resets_scrollback_and_view_offset():
    buffer = ScreenBuffer(3, 2)
    buffer.write_string(0, 0, "AAA")
    buffer.scroll("u", 1)
    buffer.scroll_view(1)
    buffer.clear()
    assert buffer._scrollback == []
    assert buffer.view_offset == 0


def test_snapshot_restore_round_trip_at_same_size():
    buffer = ScreenBuffer(5, 2)
    buffer.write_string(0, 0, "hi")
    buffer.cursor_col, buffer.cursor_row = 2, 0
    snap = buffer.snapshot()
    buffer.clear()
    buffer.restore(snap)
    assert "".join(buffer.get_cell(c, 0).char for c in range(5)) == "hi   "
    assert (buffer.cursor_col, buffer.cursor_row) == (2, 0)


def test_restore_after_grid_grew_pads_with_blank_cells():
    buffer = ScreenBuffer(3, 2)
    buffer.write_string(0, 0, "AB")
    snap = buffer.snapshot()
    buffer.resize(5, 3)  # grid changed size while the snapshot was held elsewhere
    buffer.restore(snap)
    assert "".join(buffer.get_cell(c, 0).char for c in range(5)) == "AB   "
    assert buffer.get_cell(0, 2).char == " "  # new row beyond the old grid is blank, not an IndexError


def test_restore_after_grid_shrank_clips_and_clamps_cursor():
    buffer = ScreenBuffer(5, 3)
    buffer.write_string(0, 0, "ABCDE")
    buffer.cursor_col, buffer.cursor_row = 4, 2
    snap = buffer.snapshot()
    buffer.resize(3, 1)
    buffer.restore(snap)  # should not raise despite the smaller grid
    assert "".join(buffer.get_cell(c, 0).char for c in range(3)) == "ABC"
    assert buffer.cursor_col <= 2
    assert buffer.cursor_row <= 0


def test_snapshot_restore_round_trips_cursor_enabled():
    buffer = ScreenBuffer(5, 2)
    buffer.cursor_enabled = False
    snap = buffer.snapshot()
    buffer.cursor_enabled = True
    buffer.restore(snap)
    assert buffer.cursor_enabled is False


def test_restore_also_restores_the_write_history_for_future_resizes():
    """Regression test: a menu overlay clear()s the buffer (which wipes _writes)
    before rendering itself, then restore() brings the underlying content back.
    Without restoring _writes too, a resize() after that point would replay the
    overlay's stale writes on top of whatever the restored screen rendered next,
    corrupting the display (this is exactly what happened when dragging the
    window bigger while the settings menu was open)."""
    buffer = ScreenBuffer(20, 5)
    buffer.write_string(0, 0, "Menu")
    buffer.write_string(0, 2, "> Back to Shell")
    snap = buffer.snapshot()

    buffer.clear()  # simulates a submenu's on_push()
    buffer.write_string(0, 0, "Settings")
    buffer.write_string(0, 2, "> Window Size: < 2560x1440 >")

    buffer.restore(snap)  # simulates the submenu's on_pop()
    buffer.write_string(0, 2, "> Back to Shell")  # simulates a re-render after restore (e.g. arrow key)

    buffer.resize(20, 6)  # simulates dragging the window bigger
    assert "".join(buffer.get_cell(c, 0).char for c in range(20)).rstrip() == "Menu"
    assert "".join(buffer.get_cell(c, 2).char for c in range(20)).rstrip() == "> Back to Shell"


def test_set_default_color_changes_future_writes():
    buffer = ScreenBuffer(5, 2)
    buffer.set_default_color(fg=(9, 9, 9))
    buffer.write_string(0, 0, "x")
    assert buffer.get_cell(0, 0).fg_color == (9, 9, 9)


def test_set_default_bg_repaints_from_cursor_onward_only():
    buffer = ScreenBuffer(5, 2)
    buffer.write_string(0, 0, "x")  # cell at (0,0), before the cursor
    buffer.cursor_row, buffer.cursor_col = 0, 1
    buffer.set_default_color(bg=(7, 7, 7))
    assert buffer.get_cell(0, 0).bg_color != (7, 7, 7)
    assert buffer.get_cell(1, 0).bg_color == (7, 7, 7)
    assert buffer.get_cell(0, 1).bg_color == (7, 7, 7)


def test_recolor_all_updates_live_and_scrollback_cells():
    buffer = ScreenBuffer(5, 2)
    buffer.write_string(0, 0, "x")
    buffer.scroll("u", 1)
    buffer.recolor_all(fg=(1, 1, 1), bg=(2, 2, 2))
    assert buffer._scrollback[0][0].fg_color == (1, 1, 1)
    assert buffer._scrollback[0][0].bg_color == (2, 2, 2)
    assert buffer.get_cell(0, 0).fg_color == (1, 1, 1)


# --- FontAtlas / FontRegistry ---

def test_font_atlas_rasterizes_printable_ascii():
    atlas = make_atlas()
    assert set(atlas.glyphs.keys()) == {chr(c) for c in range(32, 127)}
    assert atlas.get_glyph("A").shape == (16, 8)


def test_font_atlas_resolves_bare_filename_against_fonts_dir():
    atlas = make_atlas()
    assert atlas.font_path.name == FONT
    assert atlas.font_path.is_file()


def test_font_atlas_missing_font_raises():
    with pytest.raises(FileNotFoundError):
        FontAtlas("does-not-exist.ttf", 8, 16)


def test_get_glyph_missing_char_raises():
    atlas = make_atlas()
    atlas.glyphs.pop("A")
    with pytest.raises(ValueError):
        atlas.get_glyph("A")


def test_font_registry_first_registered_becomes_active():
    registry = FontRegistry()
    atlas = make_atlas()
    registry.register("vga", atlas)
    assert registry.active() is atlas


def test_font_registry_set_active_switches():
    registry = FontRegistry()
    a, b = make_atlas(), make_atlas()
    registry.register("a", a)
    registry.register("b", b)
    registry.set_active("b")
    assert registry.active() is b
    assert registry.get("a") is a


def test_font_registry_set_active_unknown_raises():
    registry = FontRegistry()
    registry.register("a", make_atlas())
    with pytest.raises(ValueError):
        registry.set_active("missing")


def test_font_registry_get_unknown_raises():
    registry = FontRegistry()
    with pytest.raises(ValueError):
        registry.get("missing")


def test_font_registry_active_without_registration_raises():
    registry = FontRegistry()
    with pytest.raises(ValueError):
        registry.active()


# --- Renderer ---

def test_renderer_pixel_buffer_matches_grid_size():
    renderer, buffer, atlas = make_renderer(cols=10, rows=5)
    assert renderer._pixel_buffer.shape == (5 * atlas.char_height, 10 * atlas.char_width, 3)


def test_renderer_block_cache_reuses_identical_combo():
    renderer, buffer, atlas = make_renderer()
    block1 = renderer._get_block("A", (1, 2, 3), (4, 5, 6))
    block2 = renderer._get_block("A", (1, 2, 3), (4, 5, 6))
    assert block1 is block2
    assert len(renderer._block_cache) == 1


def test_renderer_skips_rebuild_when_not_dirty():
    renderer, buffer, atlas = make_renderer()
    calls = []
    original = renderer._build_pixel_buffer
    def counting():
        calls.append(1)
        original()
    renderer._build_pixel_buffer = counting

    renderer.render(200, 100)
    assert len(calls) == 1

    renderer.render(200, 100)
    assert len(calls) == 1  # nothing changed, should be skipped

    buffer.write_string(0, 0, "x")
    renderer.render(200, 100)
    assert len(calls) == 2


def test_renderer_set_font_atlas_swaps_atlas_and_clears_block_cache():
    renderer, buffer, atlas = make_renderer(cols=10, rows=5)
    renderer._get_block("A", (1, 2, 3), (4, 5, 6))
    assert len(renderer._block_cache) == 1

    new_atlas = make_atlas(char_width=16, char_height=32)
    renderer.set_font_atlas(new_atlas)
    assert renderer.font_atlas is new_atlas
    assert renderer._block_cache == {}
    assert buffer.dirty is True


def test_renderer_rebuilds_pixel_buffer_when_screen_buffer_resizes():
    renderer, buffer, atlas = make_renderer(cols=10, rows=5)
    buffer.resize(20, 8)
    renderer.render(200, 100)
    assert renderer._pixel_buffer.shape == (8 * atlas.char_height, 20 * atlas.char_width, 3)


def test_renderer_quad_geometry_insets_by_margin():
    renderer, buffer, atlas = make_renderer(cols=10, rows=5)  # content = 80x80 px, square
    window_width, window_height, margin = 100, 100, 10
    renderer._update_quad_geometry(window_width, window_height, margin)

    raw = renderer._quad_vbo.read()
    left, bottom, _, _, right, bottom2, _, _, left2, top, _, _, right2, top2, _, _ = struct.unpack("16f", raw)

    expected_inset = margin / (window_width / 2) - 1.0
    assert left == pytest.approx(expected_inset)
    assert top == pytest.approx(-expected_inset)
    assert right < 1.0
    assert bottom > -1.0
