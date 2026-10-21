from typing import Optional


class NetworkInterface:
    def __init__(self, 
                 name: str, 
                 mac_address: str, 
                 ip_address: str,
                 manufacturer: str, 
                 power_usage_watts: int, 
                 ports: list[int] | None = None,
                 link_speed_up_mbps: Optional[int] = 1,
                 link_speed_down_mbps: Optional[int] = 10,
                 packet_loss_percentage: Optional[float] = 0.0,
                 enabled: Optional[bool] = True,
                 latency_ms: Optional[float] = 0.0,
                 load_down: Optional[float] = 0.0,
                 load_up: Optional[float] = 0.0,
                 ):
        
        self.name = name
        self.mac_address = mac_address
        self.ip_address = ip_address
        self.manufacturer = manufacturer
        self.power_usage_watts = power_usage_watts
        self.ports = ports
        self.link_speed_up_mbps = link_speed_up_mbps
        self.link_speed_down_mbps = link_speed_down_mbps
        self.packet_loss_percentage = packet_loss_percentage
        self.enabled = enabled
        self.latency_ms = latency_ms
        self.load_down = load_down
        self.load_up = load_up
        

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "mac_address": self.mac_address,
            "ip_address": self.ip_address,
            "manufacturer": self.manufacturer,
            "power_usage_watts": self.power_usage_watts,
            "ports": self.ports,
            "link_speed_up_mbps": self.link_speed_up_mbps,
            "link_speed_down_mbps": self.link_speed_down_mbps,
            "packet_loss_percentage": self.packet_loss_percentage,
            "enabled": self.enabled,
            "latency_ms": self.latency_ms,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NetworkInterface":
        return cls(**data)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, NetworkInterface) and self.to_dict() == other.to_dict()
