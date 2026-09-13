class NetworkInterface:
    def __init__(self, name: str, mac_address: str, ip_address: str, manufacturer: str, power_usage_watts: int):
        self.name = name
        self.mac_address = mac_address
        self.ip_address = ip_address
        self.manufacturer = manufacturer
        self.power_usage_watts = power_usage_watts

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "mac_address": self.mac_address,
            "ip_address": self.ip_address,
            "manufacturer": self.manufacturer,
            "power_usage_watts": self.power_usage_watts,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NetworkInterface":
        return cls(**data)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, NetworkInterface) and self.to_dict() == other.to_dict()
