"""Physical memory, swap and memory faults -- what happens to processes
once they want more RAM than the machine has, and what goes wrong when
the memory is overclocked or runs hot."""

import math
import random
import string
from collections import Counter
from typing import TYPE_CHECKING

import pyglet

from horus.events.types import MemoryCheckedEvent, MemoryErrorEvent
from horus.filesystem.node import NodeType
from horus.hardware.metric_history import MetricHistory
from horus.session.user import UserRole

if TYPE_CHECKING:
    from horus.events.bus import EventBus
    from horus.filesystem.vfs import VFS
    from horus.hardware.spec import HardwareSpec
    from horus.processes.processTable import ProcessTable

PAGE_KB = 256                 # granularity RAM is handed out in -- one cell of the RAM screen's memory map
DEFAULT_SWAP_KB = 64 * 1024   # swap space on the system drive
HISTORY_LENGTH = 360          # RAM usage samples kept -- 3 minutes at the default 0.5s tick
MIN_RESIDENT_SPEED = 0.1      # a fully swapped-out process still crawls along at this share of its speed
PAGING_RATE = 0.05            # share of its swapped memory a process pages back and forth per second at full core load
SWAP_ACTIVITY_DECAY = 0.6     # per tick -- a paging burst fades out over a few ticks instead of vanishing at once

_SETTINGS_ERROR_RATE = 0.02   # memory error chance per second per unit of Ram.instability
_HEAT_ERROR_RATE = 0.06       # ... per second at critical temperature (rising from 0 at the warning one)
_ERROR_KINDS = (("corrected", 70), ("crash", 20), ("corruption", 10))

DISABLED = "disabled"         # page_map() marker for a page on a switched-off module


class MemoryManager:
    """Every tick:

    1. frees the pages of processes that are gone, and evicts processes from
       the pages of disabled modules;
    2. resizes every process's share of RAM to its current mem_kb, in PID
       order -- older processes keep their RAM, a newcomer that doesn't fit
       gets the rest of its memory paged out to swap (process.swapped_kb).
       Growing processes extend their existing block when the pages after it
       are free, otherwise take the first free run -- so the map fragments
       over time the way real memory does;
    3. runs the OOM killer while RAM + swap can't hold everything: the
       process using the most memory is killed (even a critical one, which
       takes the system down with it);
    4. turns the paging traffic into load on the system drive (which is what
       makes it grind -- see HardwareSpec.swap_activity);
    5. rolls for a memory error -- only possible with overclocked/tight
       memory settings or above the warning temperature (see
       _check_for_errors);
    6. records RAM usage history and publishes a MemoryCheckedEvent."""

    def __init__(self, process_table: "ProcessTable", hardware: "HardwareSpec", events: "EventBus | None" = None,
                 fs: "VFS | None" = None, swap_kb: int = DEFAULT_SWAP_KB, page_kb: int = PAGE_KB,
                 interval: float = 0.5, rng: random.Random | None = None) -> None:
        self._table = process_table
        self._hardware = hardware
        self._events = events
        self._fs = fs
        self.swap_kb = swap_kb
        self.page_kb = page_kb
        self._interval = interval
        self._rng = rng if rng is not None else random.Random()
        self.pages: list[int | None] = []  # owner PID per page, across every installed module
        self.history = MetricHistory(maxlen=HISTORY_LENGTH)  # RAM usage in %
        self.error_count = 0
        self.oom_kills = 0
        process_table.enforce_memory_cap = False
        hardware.memory_managed = True
        self._layout_pages()

    def start(self) -> None:
        self.tick(0.0)
        pyglet.clock.schedule_interval(self.tick, self._interval)

    def stop(self) -> None:
        pyglet.clock.unschedule(self.tick)

    # --- layout ---

    def module_pages(self) -> list[tuple[object, int, int]]:
        """(module, first page, end page) for every installed RAM module, in
        slot order -- each module owns a fixed stretch of the page list."""
        ranges, start = [], 0
        for ram in self._hardware.installed_ram():
            count = ram.size // self.page_kb
            ranges.append((ram, start, start + count))
            start += count
        return ranges

    def _layout_pages(self) -> None:
        total = sum(end - start for _, start, end in self.module_pages())
        if len(self.pages) != total:
            self.pages = [None] * total

    def _usable_pages(self) -> list[bool]:
        usable = [False] * len(self.pages)
        for ram, start, end in self.module_pages():
            for i in range(start, end):
                usable[i] = ram.enabled
        return usable

    # --- state ---

    @property
    def total_kb(self) -> int:
        return self._hardware.total_memory_kb()

    @property
    def used_kb(self) -> int:
        return sum(owner is not None for owner in self.pages) * self.page_kb

    @property
    def free_kb(self) -> int:
        return max(0, self.total_kb - self.used_kb)

    @property
    def swap_used_kb(self) -> int:
        return sum(proc.swapped_kb for proc in self._table.list_processes())

    def page_map(self) -> list[int | str | None]:
        """Per page: the owning PID, None if free, or DISABLED."""
        usable = self._usable_pages()
        return [owner if usable[i] else DISABLED for i, owner in enumerate(self.pages)]

    def module_set_enabled(self, index: int, enabled: bool) -> bool:
        """Switches one RAM module on/off. The last enabled one stays on --
        nothing runs without memory. Its processes move elsewhere (or to
        swap) right away."""
        modules = self._hardware.installed_ram()
        if not 0 <= index < len(modules):
            return False
        if not enabled and modules[index].enabled and sum(ram.enabled for ram in modules) <= 1:
            return False
        modules[index].enabled = enabled
        self.tick(0.0)
        return True

    # --- tick ---

    def tick(self, dt: float) -> None:
        self._layout_pages()
        usable = self._usable_pages()
        live = self._table_processes()
        swapped_before = {pid: proc.swapped_kb for pid, proc in live.items()}

        for i, owner in enumerate(self.pages):
            if owner is not None and (owner not in live or not usable[i]):
                self.pages[i] = None

        self._fit_processes(usable)
        self._run_oom_killer(usable)

        paged_kb = sum(abs(proc.swapped_kb - swapped_before.get(pid, 0))
                       for pid, proc in self._table_processes().items())
        self._update_hardware(paged_kb, dt)
        self._table.total_memory_kb = self.total_kb
        if dt > 0:
            self.history.record(self.used_kb / self.total_kb * 100 if self.total_kb else 0.0)
            self._check_for_errors(dt)
        if self._events is not None:
            self._events.publish(MemoryCheckedEvent(used_kb=self.used_kb, total_kb=self.total_kb,
                                                    swap_used_kb=self.swap_used_kb, swap_total_kb=self.swap_kb))

    def _fit_processes(self, usable: list[bool]) -> None:
        """Resizes every process's RAM share to its mem_kb, oldest PID
        first; whatever doesn't fit goes to swap (process.swapped_kb)."""
        held = Counter(owner for owner in self.pages if owner is not None)
        for proc in sorted(self._table.list_processes(), key=lambda p: p.pid):
            need = math.ceil(max(0, proc.mem_kb) / self.page_kb)
            have = held[proc.pid]
            if have > need:
                self._release(proc.pid, have - need)
                have = need
            elif have < need:
                have += self._allocate(proc.pid, need - have, usable)
            proc.swapped_kb = max(0, proc.mem_kb - have * self.page_kb)

    def _table_processes(self) -> dict:
        return {proc.pid: proc for proc in self._table.list_processes()}

    def _release(self, pid: int, count: int) -> None:
        """Frees `count` of pid's pages, from its highest page down."""
        for i in range(len(self.pages) - 1, -1, -1):
            if count == 0:
                return
            if self.pages[i] == pid:
                self.pages[i] = None
                count -= 1

    def _allocate(self, pid: int, count: int, usable: list[bool]) -> int:
        """Gives pid up to `count` more pages -- right after its last page if
        those are free, else the first free run long enough, else whatever
        free pages are left. Returns how many it got."""
        def free(i: int) -> bool:
            return usable[i] and self.pages[i] is None

        chosen = []
        mine = [i for i, owner in enumerate(self.pages) if owner == pid]
        if mine:
            i = mine[-1] + 1
            while len(chosen) < count and i < len(self.pages) and free(i):
                chosen.append(i)
                i += 1
        remaining = count - len(chosen)
        if remaining:
            run_start = self._first_free_run(remaining, free)
            if run_start is not None:
                chosen.extend(range(run_start, run_start + remaining))
            else:
                chosen.extend([i for i in range(len(self.pages)) if free(i) and i not in chosen][:remaining])
        for i in chosen:
            self.pages[i] = pid
        return len(chosen)

    def _first_free_run(self, length: int, free) -> int | None:
        run = 0
        for i in range(len(self.pages)):
            run = run + 1 if free(i) else 0
            if run == length:
                return i - length + 1
        return None

    def _run_oom_killer(self, usable: list[bool]) -> None:
        """Kills the biggest process for as long as RAM + swap still can't
        hold everything -- re-fitting the rest after every kill, so the RAM
        it freed goes to whoever was swapped out before anyone else dies."""
        while self.swap_used_kb > self.swap_kb:
            processes = self._table.list_processes()
            if not processes:
                return
            victim = max(processes, key=lambda proc: (proc.mem_kb, proc.pid))
            self.oom_kills += 1
            self._publish_error("oom", f"Out of memory: killed '{victim.name}' (PID {victim.pid}, "
                                       f"{victim.mem_kb} KB) to free RAM and swap")
            self._free_process(victim.pid)
            self._table.remove_process(victim.pid, user="oom-killer", role=UserRole.ROOT)
            self._fit_processes(usable)

    def _free_process(self, pid: int) -> None:
        for i, owner in enumerate(self.pages):
            if owner == pid:
                self.pages[i] = None

    def _thrashing_kb_per_second(self) -> float:
        """Ongoing paging: a process with memory in swap keeps touching it,
        the more the busier it is -- PAGING_RATE of its swapped memory per
        second while using a whole core."""
        total = 0.0
        for proc in self._table.list_processes():
            if proc.swapped_kb:
                core_mhz = self._table.core_capacity_mhz.get(proc.core) or max(1, self._hardware.cpu_mhz)
                total += proc.swapped_kb * min(1.0, proc.cpu_mhz / core_mhz) * PAGING_RATE
        return total

    def _update_hardware(self, paged_kb: int, dt: float) -> None:
        """Paging traffic -- pages moved this tick plus ongoing thrashing --
        loads the system drive (see HardwareSpec.swap_activity), decaying
        over a few ticks so the slower hardware tick still sees a burst.
        Each module's load is how full it is."""
        drive = self._hardware.system_drive()
        if dt > 0:
            speed = drive.write_speed_kbps if drive is not None else 800
            activity = min(1.0, (paged_kb / dt + self._thrashing_kb_per_second()) / speed) if speed else 0.0
            self._hardware.swap_activity = max(activity, self._hardware.swap_activity * SWAP_ACTIVITY_DECAY)
        for ram, start, end in self.module_pages():
            pages = end - start
            ram.load = (sum(self.pages[i] is not None for i in range(start, end)) / pages
                        if pages and ram.enabled else 0.0)

    # --- memory errors ---

    def error_chance_per_second(self) -> float:
        """Odds of a memory error per second: from overclocked/tight
        settings (Ram.instability), plus heat once the system is past its
        warning temperature -- 0 at stock settings and normal temperature."""
        hardware = self._hardware
        chance = hardware.memory_instability() * _SETTINGS_ERROR_RATE
        span = hardware.critical_temperature - hardware.warning_temperature
        if span > 0 and hardware.temperature_celsius > hardware.warning_temperature:
            chance += min(1.0, (hardware.temperature_celsius - hardware.warning_temperature) / span) * _HEAT_ERROR_RATE
        return chance

    def _check_for_errors(self, dt: float) -> None:
        if self._rng.random() < self.error_chance_per_second() * dt:
            self.trigger_error()

    def trigger_error(self, kind: str | None = None) -> None:
        """One memory error -- usually corrected harmlessly, sometimes
        crashing the process whose memory got hit (init included, which
        crashes the system), sometimes corrupting a file it was holding."""
        kinds, weights = zip(*_ERROR_KINDS)
        kind = kind or self._rng.choices(kinds, weights=weights)[0]
        address = f"0x{self._rng.randrange(max(1, len(self.pages)) * self.page_kb * 1024):08X}"
        self.error_count += 1
        if kind == "crash" and self._crash_a_process(address):
            return
        if kind == "corruption" and self._corrupt_a_file(address):
            return
        self._publish_error("corrected", f"Memory error at {address} corrected")

    def _crash_a_process(self, address: str) -> bool:
        owners = [owner for owner in self.pages if owner is not None]
        if not owners:
            return False
        proc = self._table.get_process(self._rng.choice(owners))  # weighted by how much RAM each holds
        if proc is None:
            return False
        self._publish_error("crash", f"Memory error at {address} crashed '{proc.name}' (PID {proc.pid})")
        self._free_process(proc.pid)
        self._table.remove_process(proc.pid, user="memory-error", role=UserRole.ROOT)
        return True

    def _corrupt_a_file(self, address: str) -> bool:
        """Flips a few characters of a random ordinary file -- as if a bad
        bit made it into the data on its way to disk."""
        if self._fs is None:
            return False
        candidates = [path for path, node in _walk_files(self._fs, "/")
                      if node.size > 0 and not node.protected and not node.immutable and not node.name.endswith(".crypt")]
        if not candidates:
            return False
        path = self._rng.choice(candidates)
        try:
            content = list(self._fs.read_file(path, user="root"))
            for _ in range(self._rng.randint(1, 3)):
                content[self._rng.randrange(len(content))] = self._rng.choice(string.ascii_letters + string.punctuation)
            self._fs.write_file(path, "".join(content), user="root")
        except Exception:
            return False
        self._publish_error("corruption", f"Memory error at {address} corrupted {path}")
        return True

    def _publish_error(self, kind: str, detail: str) -> None:
        if self._events is not None:
            self._events.publish(MemoryErrorEvent(kind=kind, detail=detail))


def _walk_files(fs: "VFS", directory: str):
    """(path, node) for every file under `directory`, hidden ones included."""
    for node in fs.list_dir(directory, show_all=True):
        path = directory.rstrip("/") + "/" + node.name
        if node.type == NodeType.DIRECTORY:
            yield from _walk_files(fs, path)
        else:
            yield path, node


# --- memory contents (memdump) ---

def process_memory(proc, offset: int, length: int) -> bytes:
    """`length` bytes of `proc`'s simulated memory starting at `offset`:
    deterministic per process (same PID + name -> same bytes every time),
    mostly zeroed or noisy binary, with readable strings in it -- the
    process's name and environment, and its memory_strings (e.g. story
    clues only ever held in RAM)."""
    size = max(0, proc.mem_kb) * 1024
    end = min(size, offset + length)
    if offset >= end:
        return b""
    rng = random.Random(f"{proc.pid}:{proc.name}")
    strings = [f"{proc.name}\0", f"PID={proc.pid}\0", f"USER={proc.owner}\0", *[f"{s}\0" for s in proc.memory_strings]]
    placed: dict[int, bytes] = {}
    position = 64
    for text in strings:
        placed[position] = text.encode("ascii", "replace")
        position += len(placed[position]) + rng.randrange(16, 256)
    out = bytearray()
    for address in range(offset, end):
        out.append(_byte_at(proc, address, placed))
    return bytes(out)


def _byte_at(proc, address: int, placed: dict[int, bytes]) -> int:
    for start, data in placed.items():
        if start <= address < start + len(data):
            return data[address - start]
    block = random.Random(f"{proc.pid}:{proc.name}:{address // 64}")
    if block.random() < 0.6:
        return 0  # most memory is zeroed
    return random.Random(f"{proc.pid}:{address}").randrange(256)
