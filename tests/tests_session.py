from horus.display.screen_buffer import ScreenBuffer
from horus.session.context import Context


def make(cols=20, rows=5):
    buffer = ScreenBuffer(cols, rows)
    ctx = Context(session_id="s", user="root", cwd="/", screen=buffer)
    return ctx, buffer


def row_text(buffer, row):
    return "".join(buffer.get_cell(c, row).char for c in range(buffer.cols))


def test_write_line_writes_at_column_zero_and_advances_to_fresh_row():
    ctx, buffer = make()
    ctx.write_line("hello")
    assert row_text(buffer, 0).startswith("hello")
    assert buffer.cursor_row == 1
    assert buffer.cursor_col == 0
    assert row_text(buffer, 1).strip() == ""


def test_write_line_splits_on_newlines():
    ctx, buffer = make()
    ctx.write_line("first\nsecond")
    assert row_text(buffer, 0).startswith("first")
    assert row_text(buffer, 1).startswith("second")
    assert buffer.cursor_row == 2


def test_write_line_wraps_long_text_across_rows():
    ctx, buffer = make(cols=5)
    ctx.write_line("ABCDEFG")  # 7 chars, 5 cols -> 2 rows
    assert row_text(buffer, 0) == "ABCDE"
    assert row_text(buffer, 1).startswith("FG")
    assert buffer.cursor_row == 2


def test_cursor_never_shares_a_row_with_written_output():
    ctx, buffer = make(rows=3)
    for i in range(6):
        ctx.write_line(f"line{i}")
        assert row_text(buffer, buffer.cursor_row).strip() == ""


def test_cursor_row_never_exceeds_last_valid_row():
    ctx, buffer = make(rows=3)
    for i in range(10):
        ctx.write_line(f"line{i}")
        assert 0 <= buffer.cursor_row <= buffer.rows - 1


def test_write_at_last_row_scrolls_to_free_a_new_row():
    ctx, buffer = make(rows=5)
    buffer.cursor_row = 4
    ctx.write_line("hello")
    assert buffer.cursor_row == 4
    assert row_text(buffer, 4).strip() == ""
    assert row_text(buffer, 3).startswith("hello")


def test_write_line_passes_through_colors():
    ctx, buffer = make()
    ctx.write_line("hi", fg=(1, 2, 3), bg=(4, 5, 6))
    cell = buffer.get_cell(0, 0)
    assert cell.fg_color == (1, 2, 3)
    assert cell.bg_color == (4, 5, 6)


def test_single_write_taller_than_screen_does_not_crash_or_go_negative():
    ctx, buffer = make(cols=5, rows=3)
    ctx.write_line("x" * 40)  # needs 8 rows on a 3-row screen
    assert 0 <= buffer.cursor_row <= buffer.rows - 1
