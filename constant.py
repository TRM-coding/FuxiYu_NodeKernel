from enum import Enum

class MachineStatus(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    MAINTENANCE = "maintenance"


class MachineTypes(Enum):
    GPU = "GPU"
    CPU = "CPU"


class ContainerStatus(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    BUILDING = "building"
    CREATING = "creating"
    STARTING = "starting"
    RESTARTING = "restarting"
    STOPPING = "stopping"
    FAILED = "failed"
    PAUSED = "paused"
    UNKNOWN = "unknown"


class ROLE(Enum):
    ADMIN="admin"
    COLLABORATOR="collaborator"
    ROOT = "root"
