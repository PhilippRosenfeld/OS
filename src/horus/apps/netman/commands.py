from horus.kernel.registry import Registry, command

netman_commands = Registry()

@command("status", help_text="Show the network interfaces", target=netman_commands)
def status(ctx, argv):
    for iface in ctx.hardware.motherboard.network_interfaces:
        ctx.write_line(f"{iface.name}  {iface.ip_address}  {'UP' if iface.enabled else 'DOWN'}")
