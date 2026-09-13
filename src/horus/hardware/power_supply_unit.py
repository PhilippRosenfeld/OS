class PowerSupplyUnit:
    def __init__(self, name: str, manufacturer: str, power_output_watts: int):
        self.name = name
        self.manufacturer = manufacturer
        self.power_output_watts = power_output_watts

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "manufacturer": self.manufacturer,
            "power_output_watts": self.power_output_watts,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PowerSupplyUnit":
        return cls(**data)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, PowerSupplyUnit) and self.to_dict() == other.to_dict()
