from enum import StrEnum


class AssetCategory(StrEnum):
    LAPTOP = "laptop"
    MONITOR = "monitor"
    PHONE = "phone"
    PERIPHERAL = "peripheral"


class AssetStatus(StrEnum):
    AVAILABLE = "available"
    ASSIGNED = "assigned"
    IN_REPAIR = "in_repair"
    RETIRED = "retired"


class Role(StrEnum):
    ADMIN = "admin"
    STAFF = "staff"
