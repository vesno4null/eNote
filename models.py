from __future__ import annotations

# Q: Why do programmers prefer dark mode?
# A: Because light attracts bugs.
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Note:
    # The single source of truth across three subsystems. No pressure.
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    content: str = ""
    priority: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    reminder_at: Optional[float] = None
    archived: bool = False
    pinned: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Note:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
