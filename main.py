#!/usr/bin/env python3
# eNote — high-velocity notes & to-do app for Linux (GTK4 + Adwaita)
# If it breaks, you get to keep both pieces.
from __future__ import annotations

import sys
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Gio

from storage import Storage
from scheduler import Scheduler
from window import NoteWindow


class Application(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id="com.enote.app",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.storage = Storage()
        self.scheduler = Scheduler()
        self._window: Optional[NoteWindow] = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)

        self.scheduler.start_timer(30000, self._check_reminders)

        self.create_action("quit", self._on_quit, ["<Ctrl>q", "<Ctrl>w"])

    def do_shutdown(self) -> None:
        self.scheduler.stop()
        self._window = None
        Adw.Application.do_shutdown(self)

    def do_activate(self) -> None:
        win = self.props.active_window
        if not win:
            win = NoteWindow(
                storage=self.storage,
                scheduler=self.scheduler,
                application=self,
            )
            self._window = win
        win.present()

    def _check_reminders(self) -> bool:
        notes = self.storage.get_all()
        self.scheduler.check(notes)
        return True

    def _on_quit(self, *args) -> None:
        if self._window:
            self._window.save_current()
        self.quit()

    def create_action(
        self, name: str, callback: callable, shortcuts: Optional[list[str]] = None
    ) -> Gio.SimpleAction:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f"app.{name}", shortcuts)
        return action


def main() -> int:
    app = Application()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
