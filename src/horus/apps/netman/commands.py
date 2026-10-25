from horus.kernel.registry import Registry, command

netman_commands = Registry()

@command("status", help_text="Show the network interfaces", target=netman_commands)
def status(ctx, argv):
    for iface in ctx.hardware.motherboard.network_interfaces:
        ctx.write_line(f"{iface.name}  {iface.ip_address}  {'UP' if iface.enabled else 'DOWN'}")

@command("iface", help_text="Show the network interface details", target=netman_commands)
def iface(ctx, argv):
    if len(argv) < 1:
        ctx.write_line("Usage: iface <interface_name>")
        return

    iface_name = argv[0]
    iface = next((i for i in ctx.hardware.motherboard.network_interfaces if i.name == iface_name), None)

    if iface is None:
        ctx.write_line(f"Interface '{iface_name}' not found.")
        return

    ctx.write_line(f"Interface: {iface.name}")
    ctx.write_line(f"IP Address: {iface.ip_address}")
    ctx.write_line(f"Status: {'UP' if iface.enabled else 'DOWN'}")
    
@command("up", help_text="Bring up the specified network interface", target=netman_commands)
def up(ctx, argv):
    if len(argv) < 1:
        ctx.write_line("Usage: up <interface_name>")
        return

    iface_name = argv[0]
    iface = next((i for i in ctx.hardware.motherboard.network_interfaces if i.name == iface_name), None)

    if iface is None:
        ctx.write_line(f"Interface '{iface_name}' not found.")
        return

    iface.enabled = True
    ctx.write_line(f"Interface '{iface.name}' is now UP.")
    
@command("down", help_text="Bring down the specified network interface", target=netman_commands)
def down(ctx, argv):
    if len(argv) < 1:
        ctx.write_line("Usage: down <interface_name>")
        return

    iface_name = argv[0]
    iface = next((i for i in ctx.hardware.motherboard.network_interfaces if i.name == iface_name), None)

    if iface is None:
        ctx.write_line(f"Interface '{iface_name}' not found.")
        return

    iface.enabled = False
    ctx.write_line(f"Interface '{iface.name}' is now DOWN.")
    
@command("set-ip", help_text="Set the IP address of the specified network interface", target=netman_commands)
def set_ip(ctx, argv):
    if len(argv) < 2:
        ctx.write_line("Usage: set-ip <interface_name> <ip_address>")
        return
    
    check_ip = argv[1]
    octets = check_ip.split('.')
    if len(octets) != 4 or not all(o.isdigit() and 0 <= int(o) <= 255 for o in octets):
        ctx.write_line(f"Invalid IP address: {check_ip}")
        return

    iface_name = argv[0]
    new_ip = argv[1]
    iface = next((i for i in ctx.hardware.motherboard.network_interfaces if i.name == iface_name), None)

    if iface is None:
        ctx.write_line(f"Interface '{iface_name}' not found.")
        return

    iface.ip_address = new_ip
    ctx.write_line(f"Interface '{iface.name}' IP address set to {new_ip}.")

@command("speed", help_text="Set the speed of the specified network interface", target=netman_commands)
def speed(ctx, argv):
    if len(argv) < 3:
        ctx.write_line("Usage: speed <interface_name> <down_mbps> <up_mbps>")
        return

    try:
        down_mbps, up_mbps = int(argv[1]), int(argv[2])
    except ValueError:
        ctx.write_line("Usage: speed <interface_name> <down_mbps> <up_mbps>")
        return
    if down_mbps < 0 or up_mbps < 0:
        ctx.write_line("Speeds must not be negative.")
        return

    iface_name = argv[0]
    iface = next((i for i in ctx.hardware.motherboard.network_interfaces if i.name == iface_name), None)

    if iface is None:
        ctx.write_line(f"Interface '{iface_name}' not found.")
        return

    iface.link_speed_down_mbps = down_mbps
    iface.link_speed_up_mbps = up_mbps
    ctx.write_line(f"Interface '{iface.name}' speed set to {down_mbps}/{up_mbps} Mbps (down/up).")