from __future__ import annotations

# "The best time to set a reminder was 20 minutes ago.
#  The second best time is now." — definitely not Confucius
import time
from typing import Callable, List, Optional, Set

import gi

gi.require_version("Notify", "0.7")
from gi.repository import Notify, GLib

from models import Note


class Scheduler:
    def __init__(self, app_name: str = "eNote") -> None:
        self._callbacks: List[Callable[[Note], None]] = []
        self._fired: Set[str] = set()
        self._initialized = False
        self._timer_id: int = 0
        try:
            Notify.init(app_name)
            self._initialized = True
        except Exception as e:
            print(f"Notify init failed: {e}")

    def on_reminder(self, callback: Callable[[Note], None]) -> None:
        self._callbacks.append(callback)

    def notify(self, note: Note) -> None:
        if not self._initialized:
            return
        title = note.title.strip() if note.title else "eNote Reminder"
        body = note.content.strip()[:200] if note.content.strip() else "No content"
        try:
            n = Notify.Notification.new(title, body, "dialog-information")
            n.set_timeout(10000)
            n.show()
        except Exception as e:
            print(f"Notification failed: {e}")

        for cb in self._callbacks:
            try:
                cb(note)
            except Exception as e:
                print(f"Callback error: {e}")

    def check(self, notes: List[Note]) -> None:
        now = time.time()
        for note in notes:
            if note.id in self._fired:
                continue
            if note.reminder_at is not None and note.reminder_at <= now:
                self.notify(note)
                self._fired.add(note.id)

    def clear(self) -> None:
        self._fired.clear()

    def start_timer(self, interval_ms: int, callback: Callable[[], bool]) -> int:
        # GLib.timeout_add is the closest thing to setTimeout() in GTK land.
        # Returns an id we stash so stop() can remove it later.
        self._timer_id = GLib.timeout_add(interval_ms, callback)
        return self._timer_id

    def stop(self) -> None:
        if self._timer_id > 0:
            GLib.source_remove(self._timer_id)
            self._timer_id = 0
