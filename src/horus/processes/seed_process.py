from horus.processes.process import process
from horus.processes.processTable import ProcessTable


def seed_processes(process_table: ProcessTable) -> None:
    """Seed the process table with some initial processes."""
    # init barely moves -- a stable system process. bash fluctuates
    # noticeably more, like an interactive shell session would.
    process1 = process(name="init", pid=0, owner="root", cpu_percent=0.1, mem_kb=1024, volatility=0.2)
    process2 = process(name="bash", pid=0, owner="user1", cpu_percent=0.5, mem_kb=2048, volatility=1.5)
    process_table.add_process(process1)
    process_table.add_process(process2)