"""Binary codec for AutomationDirect CLICK PLC ladder clipboard format."""

from .encode import encode_rung
from .encode_multi import encode_multi_rung

__all__ = [
    "encode_rung",
    "encode_multi_rung",
]
