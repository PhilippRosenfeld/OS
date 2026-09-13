class CoolingSystem:
    def __init__(self, name: str, manufacturer: str, power_usage_watts: int,
                 coolant_type: str = "Water", coolant_amount: int = 100):
        self.name = name
        self.manufacturer = manufacturer
        self.power_usage_watts = power_usage_watts
        self.coolant_type = coolant_type
        self.coolant_amount = coolant_amount

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "manufacturer": self.manufacturer,
            "power_usage_watts": self.power_usage_watts,
            "coolant_type": self.coolant_type,
            "coolant_amount": self.coolant_amount,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CoolingSystem":
        return cls(**data)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CoolingSystem) and self.to_dict() == other.to_dict()
