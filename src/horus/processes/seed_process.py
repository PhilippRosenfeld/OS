from horus.processes.process import process
from horus.processes.processTable import ProcessTable


def seed_processes(process_table: ProcessTable) -> None:
    """Seed the process table with some initial processes."""
    # init barely moves -- a stable system process. bash fluctuates
    # noticeably more, like an interactive shell session would.
    # memory_strings show up in 'memdump' -- placeholders for now, the hook
    # for story clues that only ever live in a running process's memory
    process1 = process(name="init", pid=0, owner="root", cpu_mhz=80.0, mem_kb=1024, volatility=0.2, critical=True,
                       memory_strings=["/sbin/init", "runlevel=3", "console=tty0"])
    process2 = process(name="bash", pid=0, owner="user1", cpu_mhz=20.0, mem_kb=2048, volatility=1.0,
                       memory_strings=["HOME=/system/root", "SHELL=/bin/bash", "TERM=horus-vt220"])
    process_table.add_process(process1)
    process_table.add_process(process2)