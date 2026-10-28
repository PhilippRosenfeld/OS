"""IP address helpers -- no imports from the rest of horus.network, so netd,
hosts and the port table can all use them without importing each other."""


def is_valid_ip(ip):
    octets = ip.split('.')
    return len(octets) == 4 and all(o.isdigit() and 0 <= int(o) <= 255 for o in octets)
