"""Experimental Productivity project archive and ladder XML support.

This namespace does not change laddercodec's CLICK clipboard API.
Generated projects have not yet been validated by reopening them in Productivity.
"""

from .model import Element, Instruction, Program, Rung, TagReference
from .program import decode_program
from .project import Project, ProjectEntry, decode_project, encode_project

__all__ = [
    "Element",
    "Instruction",
    "Program",
    "Project",
    "ProjectEntry",
    "Rung",
    "TagReference",
    "decode_program",
    "decode_project",
    "encode_project",
]
