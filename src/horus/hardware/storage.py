class Storage:
    def __init__(self, name: str, size: int, manufacturer: str, power_usage_watts: int):
        self.name = name
        self.size = size
        self.data = bytearray(size)
        self.manufacturer = manufacturer
        self.power_usage_watts = power_usage_watts

    def to_dict(self) -> dict:
        """Persists the spec only -- data (bytearray of simulated storage
        content) is excluded."""
        return {
            "name": self.name,
            "size": self.size,
            "manufacturer": self.manufacturer,
            "power_usage_watts": self.power_usage_watts,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Storage":
        return cls(**data)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Storage) and self.to_dict() == other.to_dict()
