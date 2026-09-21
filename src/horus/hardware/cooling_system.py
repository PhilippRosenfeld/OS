from enum import Enum


class CoolantType(Enum):
    WATER = "Water"
    OIL = "Oil"
    AIR = "Air"
    LIQUID_NITROGEN = "Liquid Nitrogen"


# How effectively each coolant carries heat away, relative to water (1.0).
_COOLANT_MULTIPLIERS = {
    CoolantType.AIR: 0.6,
    CoolantType.WATER: 1.0,
    CoolantType.OIL: 1.6,
    CoolantType.LIQUID_NITROGEN: 2.4,
}

# env_temperature_celsius at which cooling power is neither boosted nor
# penalized -- matches HardwareSpec's own room-temperature default.
_NEUTRAL_ENV_TEMPERATURE_CELSIUS = 25.0
# How many degC above/below neutral shift cooling power by 1% -- a hotter
# environment gives the system less of a heat gradient to dump heat into,
# a colder one gives it more.
_ENV_TEMP_SCALE = 0.01

# temperature_celsius at/above which the unit runs flat out (its full rated
# power_usage_watts_max) -- duplicated locally rather than imported from
# HardwareSpec.critical_temperature (like _NEUTRAL_ENV_TEMPERATURE_CELSIUS
# above) to avoid a circular import back to spec.py.
_MAX_COOLING_TEMPERATURE_CELSIUS = 75.0


class CoolingSystem:
    def __init__(self, name: str, manufacturer: str, power_usage_watts_max: int,
                 coolant_type: CoolantType = CoolantType.WATER, coolant_amount: int = 100,
                 temperature_celsius: float = 25.0, env_temperature_celsius: float = 25.0, base_cooling_modifier: float = 1.0):
        self.name = name
        self.manufacturer = manufacturer
        self.power_usage_watts_max = power_usage_watts_max
        self.coolant_type = coolant_type
        self.coolant_amount = coolant_amount
        self.temperature_celsius = temperature_celsius
        self.env_temperature_celsius = env_temperature_celsius
        self.base_cooling_modifier = base_cooling_modifier
        self._cooling_power = self.calculate_cooling_power()

    def update_temperature(self, new_temperature: float) -> None:
        """Update the temperature of the cooling system."""
        self.temperature_celsius = new_temperature
        self._cooling_power = self.calculate_cooling_power()

    def calculate_cooling_power(self) -> float:
        """How much cooling this unit currently delivers: scales with the
        coolant's effectiveness (type) and unit quality (base_cooling_modifier),
        but always in proportion to how much coolant is actually left --
        at coolant_amount == 0 this is 0 regardless of type or modifier, i.e.
        an empty unit can't cool anything. Also scales a little with how hot
        the environment itself is (env_temperature_celsius) -- a hotter room
        leaves less of a gradient to dump heat into, so cooling is weaker;
        a colder one makes it stronger. Floored so a very hot environment
        can't push this negative.

        On top of that, the unit doesn't just run at its rated power all the
        time -- like a real fan/pump curve, it throttles with how hot the
        system currently is (see _temperature_factor): idling at power_usage_
        watts_max=0 output when the system is no hotter than its environment,
        ramping up to the full rated power_usage_watts_max once it's as hot
        as _MAX_COOLING_TEMPERATURE_CELSIUS."""
        multiplier = _COOLANT_MULTIPLIERS[self.coolant_type]
        env_factor = max(0.1, 1.0 - (self.env_temperature_celsius - _NEUTRAL_ENV_TEMPERATURE_CELSIUS) * _ENV_TEMP_SCALE)
        return (self.base_cooling_modifier * self.power_usage_watts_max * multiplier
                * (self.coolant_amount / 100) * env_factor * self._temperature_factor())

    def _temperature_factor(self) -> float:
        """How hard the unit is currently working, from 0 (the system is no
        hotter than the environment -- nothing to cool) to 1 (the system is
        at/above _MAX_COOLING_TEMPERATURE_CELSIUS -- running flat out)."""
        span = _MAX_COOLING_TEMPERATURE_CELSIUS - self.env_temperature_celsius
        if span <= 0:
            return 1.0
        return min(1.0, max(0.0, (self.temperature_celsius - self.env_temperature_celsius) / span))

    def calc_current_power_usage(self) -> float:
        """Actual electrical draw: scales directly with how much cooling is
        currently being produced (see calculate_cooling_power) -- a
        stronger coolant type or a higher base_cooling_modifier draws more
        power, not less, capped at power_usage_watts_max since that's this
        unit's rated limit. No coolant left means no cooling, hence no draw.
        Computed fresh each call (not from the cached _cooling_power) so it
        can never go stale after coolant_amount changes directly."""
        return min(self.power_usage_watts_max, self.calculate_cooling_power())

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
            "env_temperature_celsius": self.env_temperature_celsius,
            "base_cooling_modifier": self.base_cooling_modifier,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CoolingSystem":
        return cls(**{**data, "coolant_type": CoolantType(data["coolant_type"])})

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CoolingSystem) and self.to_dict() == other.to_dict()
