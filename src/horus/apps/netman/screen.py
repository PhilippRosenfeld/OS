from horus.apps.netman.commands import netman_commands
from horus.apps.shell_window import ShellWindow


class NetmanWindow(ShellWindow):
    def __init__(self, ctx):
        # keep_running: 'exit' only hides the window -- netman keeps running in
        # the background and 'netman' brings it back as it was ('quit' ends it)
        super().__init__(ctx, "Connection Manager", commands=netman_commands,
                         process_name="netman", keep_running=True,
                         welcome=["Type 'help' for commands.", ""])

    def prompt(self):
        return "net> "
