from enum import Enum


class CoolantType(Enum):
    WATER = "Water"
    OIL = "Oil"
    AIR = "Air"
    LIQUID_NITROGEN = "Liquid Nitrogen"


# How effectively each coolant carries heat away, relative to water (1.0).
_COOLANT_MULTIPLIERS = {
    CoolantType.WATER: 1.0,
    CoolantType.OIL: 1.6,
    CoolantType.AIR: 0.6,
    CoolantType.LIQUID_NITROGEN: 2.4,
}


class CoolingSystem:
    def __init__(self, name: str, manufacturer: str, power_usage_watts_max: int,
                 coolant_type: CoolantType = CoolantType.WATER, coolant_amount: int = 100,
                 temperature_celsius: float = 25.0, base_cooling_modifier: float = 1.0):
        self.name = name
        self.manufacturer = manufacturer
        self.power_usage_watts_max = power_usage_watts_max
        self.coolant_type = coolant_type
        self.coolant_amount = coolant_amount
        self.temperature_celsius = temperature_celsius
        self.base_cooling_modifier = base_cooling_modifier
        self._cooling_power = self._calculate_cooling_power()

    def update_temperature(self, new_temperature: float) -> None:
        """Update the temperature of the cooling system."""
        self.temperature_celsius = new_temperature
        self._cooling_power = self._calculate_cooling_power()

    def _calculate_cooling_power(self) -> float:
        """How much cooling this unit currently delivers: scales with the
        coolant's effectiveness (type) and unit quality (base_cooling_modifier),
        but always in proportion to how much coolant is actually left --
        at coolant_amount == 0 this is 0 regardless of type or modifier, i.e.
        an empty unit can't cool anything."""
        multiplier = _COOLANT_MULTIPLIERS[self.coolant_type]
        return self.base_cooling_modifier * self.power_usage_watts_max * multiplier * (self.coolant_amount / 100)

    def calc_current_power_usage(self) -> float:
        """Actual electrical draw: scales directly with how much cooling is
        currently being produced (see _calculate_cooling_power) -- a
        stronger coolant type or a higher base_cooling_modifier draws more
        power, not less, capped at power_usage_watts_max since that's this
        unit's rated limit. No coolant left means no cooling, hence no draw.
        Computed fresh each call (not from the cached _cooling_power) so it
        can never go stale after coolant_amount changes directly."""
        return min(self.power_usage_watts_max, self._calculate_cooling_power())

    def to_dict(self) -> dict:
        """Persists the spec only -- _cooling_power is derived (recomputed
        from these fields on load), not config."""
        return {
            "name": self.name,
            "manufacturer": self.manufacturer,
            "power_usage_watts_max": self.power_usage_watts_max,
            "coolant_type": self.coolant_type.value,
            "coolant_amount": self.coolant_amount,
            "temperature_celsius": self.temperature_celsius,
            "base_cooling_modifier": self.base_cooling_modifier,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CoolingSystem":
        return cls(**{**data, "coolant_type": CoolantType(data["coolant_type"])})

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CoolingSystem) and self.to_dict() == other.to_dict()
