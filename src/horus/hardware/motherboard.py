from horus.hardware.cooling_system import CoolingSystem
from horus.hardware.cpu import Cpu
from horus.hardware.network_interface import NetworkInterface
from horus.hardware.ram import Ram
from horus.hardware.storage import Storage


class CpuSocket:
    def __init__(self, name: str, supported_cpus: list[Cpu]):
        self.name = name
        self.supported_cpus = supported_cpus

    def to_dict(self) -> dict:
        return {"name": self.name, "supported_cpus": [cpu.to_dict() for cpu in self.supported_cpus]}

    @classmethod
    def from_dict(cls, data: dict) -> "CpuSocket":
        return cls(name=data["name"], supported_cpus=[Cpu.from_dict(cpu) for cpu in data["supported_cpus"]])

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CpuSocket) and self.to_dict() == other.to_dict()


class RamSlots:
    def __init__(self, name: str, supported_ram_types: list[Ram]):
        self.name = name
        self.supported_ram_types = supported_ram_types

    def to_dict(self) -> dict:
        return {"name": self.name, "supported_ram_types": [ram.to_dict() for ram in self.supported_ram_types]}

    @classmethod
    def from_dict(cls, data: dict) -> "RamSlots":
        return cls(name=data["name"], supported_ram_types=[Ram.from_dict(ram) for ram in data["supported_ram_types"]])

    def __eq__(self, other: object) -> bool:
        return isinstance(other, RamSlots) and self.to_dict() == other.to_dict()


class StorageSlots:
    def __init__(self, name: str, supported_storage_types: list[Storage]):
        self.name = name
        self.supported_storage_types = supported_storage_types

    def to_dict(self) -> dict:
        return {"name": self.name, "supported_storage_types": [storage.to_dict() for storage in self.supported_storage_types]}

    @classmethod
    def from_dict(cls, data: dict) -> "StorageSlots":
        return cls(name=data["name"], supported_storage_types=[Storage.from_dict(s) for s in data["supported_storage_types"]])

    def __eq__(self, other: object) -> bool:
        return isinstance(other, StorageSlots) and self.to_dict() == other.to_dict()


class Motherboard:
    def __init__(self,
                 name: str,
                 manufacturer: str,
                 power_usage_watts: int,
                 cpu_sockets: list[CpuSocket],
                 ram_slots: list[RamSlots],
                 storage_slots: list[StorageSlots],
                 network_interfaces: list[NetworkInterface],
                 cooling_system: CoolingSystem,
                 ):
        self.name = name
        self.manufacturer = manufacturer
        self.power_usage_watts = power_usage_watts
        self.cpu_sockets = cpu_sockets
        self.ram_slots = ram_slots
        self.storage_slots = storage_slots
        self.network_interfaces = network_interfaces
        self.cooling_system = cooling_system

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "manufacturer": self.manufacturer,
            "power_usage_watts": self.power_usage_watts,
            "cpu_sockets": [socket.to_dict() for socket in self.cpu_sockets],
            "ram_slots": [slot.to_dict() for slot in self.ram_slots],
            "storage_slots": [slot.to_dict() for slot in self.storage_slots],
            "network_interfaces": [iface.to_dict() for iface in self.network_interfaces],
            "cooling_system": self.cooling_system.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Motherboard":
        return cls(
            name=data["name"],
            manufacturer=data["manufacturer"],
            power_usage_watts=data["power_usage_watts"],
            cpu_sockets=[CpuSocket.from_dict(s) for s in data["cpu_sockets"]],
            ram_slots=[RamSlots.from_dict(s) for s in data["ram_slots"]],
            storage_slots=[StorageSlots.from_dict(s) for s in data["storage_slots"]],
            network_interfaces=[NetworkInterface.from_dict(i) for i in data["network_interfaces"]],
            cooling_system=CoolingSystem.from_dict(data["cooling_system"]),
        )

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Motherboard) and self.to_dict() == other.to_dict()
