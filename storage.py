from __future__ import annotations

# "I don't always persist data, but when I do, I use YAML front-matter.
#  Stay durable, my friends." — The Most Interesting Storage Engine
import os
import re
import time
import uuid
from pathlib import Path
from threading import Lock
from typing import List, Optional

import yaml

from models import Note

DATA_DIR = Path.home() / ".local" / "share" / "enote"
NOTES_DIR = DATA_DIR / "notes"
EASYNOTE_EXT = ".easynote"


class Storage:
    def __init__(self) -> None:
        self._notes: List[Note] = []
        self._lock = Lock()
        self._ensure_dirs()
        self._load()

    def _ensure_dirs(self) -> None:
        try:
            NOTES_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            print(f"Failed to create data directory {NOTES_DIR}: {e}")

    def _load(self) -> None:
        self._notes = []
        if not NOTES_DIR.exists():
            return
        try:
            for fpath in sorted(NOTES_DIR.iterdir()):
                if fpath.suffix != EASYNOTE_EXT:
                    continue
                note = self._parse_file(fpath)
                if note:
                    self._notes.append(note)
        except OSError as e:
            print(f"Failed to load notes: {e}")

    def _parse_file(self, fpath: Path) -> Optional[Note]:
        try:
            text = fpath.read_text(encoding="utf-8")
        except (OSError, IOError) as e:
            print(f"Failed to read {fpath}: {e}")
            return None

        match = re.match(r"^---\n(.*?)\n---\n\n(.*)", text, re.DOTALL)
        if not match:
            return self._parse_legacy_format(text, fpath)

        front_raw = match.group(1)
        body = match.group(2)

        try:
            meta = yaml.safe_load(front_raw)
        except yaml.YAMLError as e:
            print(f"Failed to parse YAML in {fpath}: {e}")
            return None

        if not isinstance(meta, dict):
            return None

        note = Note.from_dict(meta)
        note.content = body
        return note

    def _parse_legacy_format(self, text: str, fpath: Path) -> Optional[Note]:
        print(f"Legacy format detected for {fpath.name}, migrating...")
        note_id = fpath.stem
        lines = text.split("\n")
        content = text
        title = ""
        priority = 0
        reminder_at: Optional[float] = None
        for line in lines:
            if line.startswith("# "):
                title = line[2:].strip()
                break

        note = Note(
            id=note_id,
            title=title,
            content=content,
            priority=priority,
            reminder_at=reminder_at,
        )
        return note

    def _file_path(self, note_id: str) -> Path:
        return NOTES_DIR / f"{note_id}{EASYNOTE_EXT}"

    def save(self) -> None:
        with self._lock:
            for note in self._notes:
                self._write_note_file(note)

    def _write_note_file(self, note: Note) -> None:
        # Write to a .tmp file first, then atomically replace. Keeps corruption
        # from power-loss at bay — roughly the same odds as losing a coin toss.
        meta = {k: v for k, v in note.to_dict().items() if k != "content"}
        front = yaml.dump(meta, default_flow_style=False, allow_unicode=True).strip()
        body = note.content
        text = f"---\n{front}\n---\n\n{body}"

        fpath = self._file_path(note.id)
        try:
            tmp = fpath.with_suffix(f"{EASYNOTE_EXT}.tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(fpath)
        except (OSError, IOError) as e:
            print(f"Failed to write {fpath}: {e}")

    def get_all(self) -> List[Note]:
        with self._lock:
            return sorted(
                self._notes,
                key=lambda n: (not n.pinned, -n.updated_at),
            )

    def get(self, note_id: str) -> Optional[Note]:
        with self._lock:
            for note in self._notes:
                if note.id == note_id:
                    return note
            return None

    def add(self, note: Note) -> None:
        self._ensure_dirs()
        with self._lock:
            self._notes.append(note)
        self._write_note_file(note)

    def update(self, note: Note) -> None:
        with self._lock:
            note.updated_at = time.time()
            for i, n in enumerate(self._notes):
                if n.id == note.id:
                    self._notes[i] = note
                    break
        self._write_note_file(note)

    def delete(self, note_id: str) -> None:
        with self._lock:
            self._notes = [n for n in self._notes if n.id != note_id]
        fpath = self._file_path(note_id)
        try:
            if fpath.exists():
                fpath.unlink()
        except OSError as e:
            print(f"Failed to delete {fpath}: {e}")

    def get_pending_reminders(self) -> List[Note]:
        now = time.time()
        with self._lock:
            return [
                n
                for n in self._notes
                if n.reminder_at is not None and n.reminder_at <= now and not n.archived
            ]

    @staticmethod
    def get_file_filter() -> Gtk.FileFilter:
        from gi.repository import Gtk
        f = Gtk.FileFilter()
        f.set_name("eNote files (*.easynote)")
        f.add_pattern("*" + EASYNOTE_EXT)
        f.add_mime_type("text/plain")
        return f

    def import_file(self, fpath: Path) -> Optional[Note]:
        note = self._parse_file(fpath)
        if note:
            note.id = str(uuid.uuid4())
            self.add(note)
        return note

    def export_note(self, note_id: str, fpath: Path) -> bool:
        note = self.get(note_id)
        if not note:
            return False
        try:
            fpath.write_text(self._format_export(note), encoding="utf-8")
            return True
        except OSError:
            return False

    def _format_export(self, note: Note) -> str:
        # Same write format but without the .tmp dance — the caller
        # can deal with the consequences if the disk is full.
        meta = {k: v for k, v in note.to_dict().items() if k != "content"}
        front = yaml.dump(meta, default_flow_style=False, allow_unicode=True).strip()
        return f"---\n{front}\n---\n\n{note.content}"
