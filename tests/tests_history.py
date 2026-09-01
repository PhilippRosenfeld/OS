from horus.session.history import CommandHistory


def test_add_ignores_blank_lines():
    h = CommandHistory()
    h.add("")
    h.add("   ")
    assert h.all() == []


def test_add_ignores_consecutive_duplicates():
    h = CommandHistory()
    h.add("ls")
    h.add("ls")
    assert h.all() == ["ls"]


def test_add_allows_the_same_command_again_after_something_else():
    h = CommandHistory()
    h.add("ls")
    h.add("cd /home")
    h.add("ls")
    assert h.all() == ["ls", "cd /home", "ls"]


def test_add_beyond_max_size_evicts_the_oldest_entry():
    """Regression test: add() used to pop() the entry it had just appended
    (list.pop() with no index removes the *last* item), so once history hit
    max_size, every subsequent command was silently discarded and the
    history became permanently frozen instead of sliding forward."""
    h = CommandHistory(max_size=3)
    h.add("one")
    h.add("two")
    h.add("three")
    h.add("four")
    assert h.all() == ["two", "three", "four"]


def test_add_beyond_max_size_keeps_sliding_forward():
    h = CommandHistory(max_size=2)
    for cmd in ["a", "b", "c", "d", "e"]:
        h.add(cmd)
    assert h.all() == ["d", "e"]


def test_previous_walks_back_through_history_oldest_last():
    h = CommandHistory()
    h.add("one")
    h.add("two")
    h.add("three")
    assert h.previous("") == "three"
    assert h.previous("") == "two"
    assert h.previous("") == "one"


def test_previous_stops_at_the_oldest_entry():
    h = CommandHistory()
    h.add("only")
    assert h.previous("") == "only"
    assert h.previous("") is None  # no further back to go
    assert h.previous("") is None  # still nothing, not an error


def test_previous_on_empty_history_returns_none():
    h = CommandHistory()
    assert h.previous("draft") is None


def test_next_without_browsing_returns_none():
    h = CommandHistory()
    h.add("one")
    assert h.next() is None  # previous() was never called -- not currently browsing


def test_next_walks_forward_and_restores_the_draft_past_the_newest():
    h = CommandHistory()
    h.add("one")
    h.add("two")
    h.previous("my draft")  # -> "two"
    h.previous("my draft")  # -> "one"
    assert h.next() == "two"
    assert h.next() == "my draft"  # walked past the newest entry -> saved draft
    assert h.next() is None  # no longer browsing


def test_previous_after_reaching_the_draft_starts_a_fresh_walk():
    h = CommandHistory()
    h.add("one")
    h.add("two")
    h.previous("draft")  # -> "two"
    h.next()  # -> "draft", stops browsing
    assert h.previous("draft again") == "two"  # starts over from the newest


def test_add_resets_any_in_progress_browsing():
    h = CommandHistory()
    h.add("one")
    h.previous("draft")  # now browsing
    h.add("two")  # submitting a new command should reset browsing state
    assert h.next() is None  # not browsing anymore


def test_all_returns_oldest_first_and_is_a_copy():
    h = CommandHistory()
    h.add("one")
    h.add("two")
    result = h.all()
    assert result == ["one", "two"]
    result.append("mutated")
    assert h.all() == ["one", "two"]  # caller's mutation doesn't leak back in
