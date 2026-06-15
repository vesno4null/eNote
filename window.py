from __future__ import annotations

# There are only two hard things in computer science:
# cache invalidation, naming things, and off-by-one errors.
import time
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Adw, Gdk, Gio, GLib

from models import Note
from storage import Storage
from scheduler import Scheduler
from parser import to_blocks, from_blocks
from editor_blocks import BlockEditor, EntityBlock, TodoItemBlock


class NoteRow(Gtk.ListBoxRow):
    def __init__(self, note: Note) -> None:
        super().__init__()
        self.note_id = note.id
        self.set_activatable(True)

        row = Adw.ActionRow()
        row.set_title(self._extract_title(note.content))
        row.set_subtitle(self._extract_snippet(note.content))
        row.set_title_lines(1)
        row.set_subtitle_lines(1)

        if note.priority > 0:
            icon_name = (
                "starred-symbolic" if note.priority == 1 else "dialog-error-symbolic"
            )
            icon = Gtk.Image.new_from_icon_name(icon_name)
            icon.set_pixel_size(12)
            row.add_prefix(icon)

        if note.reminder_at is not None:
            bell = Gtk.Image.new_from_icon_name("alarm-symbolic")
            bell.set_pixel_size(10)
            row.add_suffix(bell)

        self.set_child(row)

    @staticmethod
    def _extract_title(content: str) -> str:
        for line in content.strip().split("\n"):
            cleaned = line.lstrip("# ").strip()
            if cleaned:
                return cleaned[:60]
        return "Untitled"

    @staticmethod
    def _extract_snippet(content: str) -> str:
        lines = content.strip().split("\n")
        for line in lines[1:]:
            cleaned = line.strip()
            if cleaned:
                return cleaned[:80]
        return "Empty note"


class ReminderPopover(Gtk.Popover):
    def __init__(self, storage: Storage, note_id: str) -> None:
        super().__init__()
        self._storage = storage
        self._note_id = note_id
        self.set_position(Gtk.PositionType.BOTTOM)
        self.set_has_arrow(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        label = Gtk.Label(label="Set Reminder")
        label.add_css_class("heading")
        box.append(label)

        flow = Gtk.FlowBox()
        flow.set_max_children_per_line(3)
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_homogeneous(True)
        presets = [
            ("30 min", 1800),
            ("1 hour", 3600),
            ("2 hours", 7200),
            ("4 hours", 14400),
            ("Tomorrow", 86400),
            ("Next week", 604800),
        ]
        for label_text, seconds in presets:
            btn = Gtk.Button(label=label_text)
            btn.add_css_class("flat")
            btn.connect("clicked", self._on_preset, seconds)
            flow.append(btn)
        box.append(flow)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(8)
        sep.set_margin_bottom(8)
        box.append(sep)

        self._calendar = Gtk.Calendar()
        box.append(self._calendar)

        time_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        time_box.set_margin_top(6)
        time_box.set_halign(Gtk.Align.CENTER)

        self._hour_spin = Gtk.SpinButton.new_with_range(0, 23, 1)
        self._hour_spin.set_value(9)
        self._hour_spin.set_width_chars(3)

        self._min_spin = Gtk.SpinButton.new_with_range(0, 59, 1)
        self._min_spin.set_value(0)
        self._min_spin.set_width_chars(3)

        time_box.append(Gtk.Label(label="Hour:"))
        time_box.append(self._hour_spin)
        time_box.append(Gtk.Label(label=":"))
        time_box.append(self._min_spin)
        box.append(time_box)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_box.set_margin_top(8)
        btn_box.set_halign(Gtk.Align.END)

        clear_btn = Gtk.Button(label="Clear")
        clear_btn.add_css_class("destructive-action")
        clear_btn.connect("clicked", self._on_clear)
        btn_box.append(clear_btn)

        set_btn = Gtk.Button(label="Set")
        set_btn.add_css_class("suggested-action")
        set_btn.connect("clicked", self._on_set)
        btn_box.append(set_btn)

        box.append(btn_box)

        self.set_child(box)

    def _on_preset(self, _btn: Gtk.Button, seconds: int) -> None:
        if not self._note_id:
            return
        ts = time.time() + seconds
        note = self._storage.get(self._note_id)
        if note:
            note.reminder_at = ts
            self._storage.update(note)
        self.popdown()

    def _on_set(self, _btn: Gtk.Button) -> None:
        if not self._note_id:
            return
        year, month, day = self._calendar.get_date()
        hour = int(self._hour_spin.get_value())
        minute = int(self._min_spin.get_value())
        dt = GLib.DateTime.new_local(year, month, day, hour, minute, 0)
        ts = dt.to_unix()
        note = self._storage.get(self._note_id)
        if note:
            note.reminder_at = ts
            self._storage.update(note)
        self.popdown()

    def _on_clear(self, _btn: Gtk.Button) -> None:
        if not self._note_id:
            return
        note = self._storage.get(self._note_id)
        if note:
            note.reminder_at = None
            self._storage.update(note)
        self.popdown()


class NoteWindow(Adw.ApplicationWindow):
    def __init__(self, storage: Storage, scheduler: Scheduler, **kwargs) -> None:
        super().__init__(**kwargs)
        self._storage = storage
        self._scheduler = scheduler

        self._current_note_id: Optional[str] = None
        self._save_timer_id: int = 0
        self._content_modified = False
        self._handler_id: int = 0

        self.set_default_size(900, 600)
        self.set_size_request(480, 360)
        self.set_title("eNote")

        self._build_ui()
        self._setup_actions()
        self._connect_events()
        self.connect("close-request", self._on_close_request)
        self.connect("destroy", self._on_destroy)
        self._show_welcome()

        # Global CSS for the whole app. If this fails we just print and move on —
        # the widgets have sensible enough defaults to not look like a crime scene.
        css_provider = Gtk.CssProvider()
        try:
            css_provider.load_from_string(
                """
.format-toolbar { background: alpha(@window_bg_color, 0.5); border-bottom: 1px solid @borders; }
.format-toolbar button { min-width: 28px; min-height: 24px; padding: 2px 6px; font-weight: bold; }
.format-toolbar button:active { background: @accent_bg_color; color: @accent_fg_color; }
.block-editor-box { background: transparent; }
.block-editor-box > row { background: transparent; border: none; }
.block-editor-box > row:selected { background: alpha(@accent_bg_color, 0.08); }
.block-editor { background: transparent; padding: 0; font-size: 14px; }
.block-editor:focus { background: transparent; }
.entity-block { padding: 0 8px; border-left: 2px solid transparent; }
.important-callout { background: alpha(#ff7800, 0.08); border-left: 3px solid #ff7800; border-radius: 4px; }
.code-frame { background: alpha(@window_fg_color, 0.04); border: 1px solid @borders; border-radius: 4px; }
.code-lang { font-size: 10px; color: alpha(@window_fg_color, 0.5); }
.code-text { font-family: monospace; font-size: 12px; }
.heading-1 { font-size: 22pt; font-weight: bold; }
.heading-2 { font-size: 18pt; font-weight: bold; }
.heading-3 { font-size: 16pt; font-weight: bold; }
.block-editor { min-height: 48px; caret-color: @accent_bg_color; }
.block-editor-box > row { min-height: 32px; }
.diagnostics-panel { margin: 0 8px; border-radius: 4px; background: alpha(@warning_bg_color, 0.1); }
.diag-error { color: @error_color; font-size: 11px; }
.diag-warning { color: @warning_color; font-size: 11px; }
.diag-info { color: @accent_color; font-size: 11px; }
"""
            )
            display = self.get_display()
            if display:
                Gtk.StyleContext.add_provider_for_display(
                    display,
                    css_provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
                )
        except Exception as e:
            print(f"CSS load failed: {e}")

    def _build_ui(self) -> None:
        toast_overlay = Adw.ToastOverlay()
        self.set_content(toast_overlay)
        self._toast_overlay = toast_overlay

        self._split_view = Adw.NavigationSplitView()
        self._split_view.set_min_sidebar_width(240)
        self._split_view.set_max_sidebar_width(360)
        self._split_view.set_hexpand(True)
        self._split_view.set_vexpand(True)
        toast_overlay.set_child(self._split_view)

        self._build_sidebar()
        self._build_editor()

    def _build_sidebar(self) -> None:
        sidebar_tv = Adw.ToolbarView()
        sidebar_tv.set_size_request(240, -1)

        sidebar_header = Adw.HeaderBar()
        sidebar_header.set_title_widget(Gtk.Label(label="Notes"))
        new_btn = Gtk.Button.new_from_icon_name("list-add-symbolic")
        new_btn.set_tooltip_text("New note (Ctrl+N)")
        new_btn.add_css_class("flat")
        new_btn.connect("clicked", lambda _: self._new_note())
        sidebar_header.pack_start(new_btn)
        sidebar_tv.add_top_bar(sidebar_header)

        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        search_box.set_margin_start(6)
        search_box.set_margin_end(6)
        search_box.set_margin_bottom(6)
        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_hexpand(True)
        self._search_entry.set_placeholder_text("Search notes (Ctrl+F)...")
        self._search_entry.connect("search-changed", self._on_search_changed)
        search_box.append(self._search_entry)
        sidebar_tv.add_top_bar(search_box)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._note_list = Gtk.ListBox()
        self._note_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._handler_id = self._note_list.connect(
            "row-selected", self._on_note_selected
        )
        self._note_list.add_css_class("navigation-sidebar")
        scrolled.set_child(self._note_list)

        sidebar_tv.set_content(scrolled)

        bottom_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        bottom_bar.set_margin_start(12)
        bottom_bar.set_margin_end(12)
        bottom_bar.set_margin_top(3)
        bottom_bar.set_margin_bottom(3)
        self._note_count_label = Gtk.Label(label="0 notes")
        self._note_count_label.add_css_class("dim-label")
        self._note_count_label.add_css_class("caption")
        bottom_bar.append(self._note_count_label)
        sidebar_tv.add_bottom_bar(bottom_bar)

        sidebar_page = Adw.NavigationPage()
        sidebar_page.set_child(sidebar_tv)
        sidebar_page.set_title("Notes")
        self._split_view.set_sidebar(sidebar_page)

    def _build_editor(self) -> None:
        content_tv = Adw.ToolbarView()

        content_header = Adw.HeaderBar()

        self._title_label = Gtk.Label(label="eNote")
        self._title_label.add_css_class("title")
        content_header.set_title_widget(self._title_label)

        self._delete_btn = Gtk.Button.new_from_icon_name("user-trash-symbolic")
        self._delete_btn.set_tooltip_text("Delete note (Ctrl+D)")
        self._delete_btn.connect("clicked", lambda _: self._delete_note())
        self._delete_btn.set_sensitive(False)
        content_header.pack_end(self._delete_btn)

        self._reminder_btn = Gtk.Button.new_from_icon_name("alarm-symbolic")
        self._reminder_btn.set_tooltip_text("Set reminder")
        self._reminder_btn.connect("clicked", self._show_reminder_popover)
        self._reminder_btn.set_sensitive(False)
        content_header.pack_end(self._reminder_btn)

        self._priority_btn = Gtk.MenuButton()
        self._priority_btn.set_icon_name("non-starred-symbolic")
        self._priority_btn.set_tooltip_text("Priority")
        self._priority_btn.set_sensitive(False)

        priority_menu = Gio.Menu()
        priority_menu.append("None", "win.set-priority::0")
        priority_menu.append("Important", "win.set-priority::1")
        priority_menu.append("Critical", "win.set-priority::2")
        self._priority_btn.set_menu_model(priority_menu)
        content_header.pack_end(self._priority_btn)

        content_tv.add_top_bar(content_header)

        editor_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        self._empty_page = Adw.StatusPage()
        self._empty_page.set_icon_name("document-edit-symbolic")
        self._empty_page.set_title("eNote")
        self._empty_page.set_description(
            "Create a note to get started\nPress Ctrl+N or click +"
        )
        editor_box.append(self._empty_page)

        self._editor_area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        editor_box.append(self._editor_area)

        self._build_formatting_toolbar()

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_has_frame(False)

        self._block_editor = BlockEditor(on_content_changed=self._on_content_changed)
        scrolled.set_child(self._block_editor)

        self._editor_area.append(scrolled)

        content_tv.set_content(editor_box)

        content_page = Adw.NavigationPage()
        content_page.set_child(content_tv)
        content_page.set_title("eNote")
        self._split_view.set_content(content_page)

    def _build_formatting_toolbar(self) -> None:
        toolbar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        toolbar_box.add_css_class("format-toolbar")
        toolbar_box.set_margin_start(4)
        toolbar_box.set_margin_end(4)

        flowbox = Gtk.FlowBox()
        flowbox.set_max_children_per_line(30)
        flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        flowbox.set_homogeneous(False)
        flowbox.set_column_spacing(1)
        flowbox.set_row_spacing(1)

        groups: list[list[tuple[str, str, str]]] = [
            [("H1", "Heading 1", "heading-1"),
             ("H2", "Heading 2", "heading-2"),
             ("H3", "Heading 3", "heading-3")],
            [("☐", "To-Do list", "todo"),
             ("•", "Bullet list", "bullet"),
             ("1.", "Numbered list", "numbered")],
            [("#!", "Important", "important"),
             ("<>", "Code block", "code"),
             ("—", "Horizontal rule", "hr")],
        ]

        action_map = {
            "heading-1": lambda _: self._convert_to_block("heading-1"),
            "heading-2": lambda _: self._convert_to_block("heading-2"),
            "heading-3": lambda _: self._convert_to_block("heading-3"),
            "todo": lambda _: self._convert_to_block("todo"),
            "bullet": lambda _: self._convert_to_block("bullet"),
            "numbered": lambda _: self._convert_to_block("numbered"),
            "important": lambda _: self._convert_to_block("important"),
            "code": lambda _: self._insert_new_block("code"),
            "hr": lambda _: self._insert_new_block("hr"),
        }

        for gidx, group in enumerate(groups):
            if gidx > 0:
                sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
                sep.set_margin_top(4)
                sep.set_margin_bottom(4)
                sep.set_margin_start(4)
                sep.set_margin_end(4)
                flowbox.append(sep)

            for label, tooltip, action in group:
                btn = Gtk.Button(label=label)
                btn.set_tooltip_text(tooltip)
                btn.add_css_class("flat")
                btn.add_css_class("toolbar-btn")
                btn.connect("clicked", action_map[action])
                flowbox.append(btn)

        toolbar_box.append(flowbox)
        self._editor_area.prepend(toolbar_box)

    def _convert_to_block(self, new_type: str) -> None:
        row = self._block_editor.get_selected_row()
        if row is None:
            row = self._block_editor._find_focused_row()
        if row is None or not isinstance(row, (EntityBlock, TodoItemBlock)):
            self._insert_new_block(new_type)
            return
        idx = self._block_editor._block_index(row)
        if idx >= 0:
            self._block_editor.convert_block(idx, new_type)
            self._on_content_changed()

    def _insert_new_block(self, block_type: str) -> None:
        from editor_blocks import create_block

        new_block = create_block({"type": block_type, "content": ""}, self._block_editor._handle_block_action)
        self._block_editor._suppress_change = True
        row = self._block_editor.get_selected_row()
        if row is None:
            row = self._block_editor._find_focused_row()
        if row is not None:
            idx = self._block_editor._block_index(row)
            if idx >= 0:
                self._block_editor.insert(new_block, idx + 1)
            else:
                self._block_editor.append(new_block)
        else:
            self._block_editor.append(new_block)
        self._block_editor._inc_row_count(1)
        self._block_editor._suppress_change = False
        if isinstance(new_block, EntityBlock):
            new_block.focus_block()
        elif isinstance(new_block, TodoItemBlock):
            new_block.entry.grab_focus()
        self._on_content_changed()

    def _setup_actions(self) -> None:
        new_action = Gio.SimpleAction.new("new-note", None)
        new_action.connect("activate", lambda *_: self._new_note())
        self.add_action(new_action)

        delete_action = Gio.SimpleAction.new("delete-note", None)
        delete_action.connect("activate", lambda *_: self._delete_note())
        self.add_action(delete_action)

        search_action = Gio.SimpleAction.new("focus-search", None)
        search_action.connect("activate", lambda *_: self._search_entry.grab_focus())
        self.add_action(search_action)

        priority_action = Gio.SimpleAction.new(
            "set-priority", GLib.VariantType.new("i")
        )
        priority_action.connect("activate", self._on_set_priority)
        self.add_action(priority_action)

        app = self.get_application()
        if app:
            app.set_accels_for_action("win.new-note", ["<Ctrl>n"])
            app.set_accels_for_action("win.focus-search", ["<Ctrl>f"])
            app.set_accels_for_action("win.delete-note", ["Delete", "<Ctrl>d"])
            app.set_accels_for_action("win.set-priority::0", ["<Ctrl>0"])
            app.set_accels_for_action("win.set-priority::1", ["<Ctrl>1"])
            app.set_accels_for_action("win.set-priority::2", ["<Ctrl>2"])

    def _connect_events(self) -> None:
        controller = Gtk.EventControllerKey.new()
        controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(controller)

    def _on_close_request(self, _win: Gtk.Window) -> bool:
        self.save_current()
        return False

    def _on_destroy(self, _obj: Gtk.Widget) -> None:
        if self._save_timer_id > 0:
            GLib.source_remove(self._save_timer_id)
            self._save_timer_id = 0
        try:
            self._block_editor.cleanup_all()
        except Exception as e:
            print(f"Block cleanup error: {e}")
        app = self.get_application()
        if app:
            app.quit()

    def _on_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        _state: Gdk.ModifierType,
    ) -> bool:
        # Escape in the editor pane goes back to the note list on mobile-ish layouts.
        if keyval == Gdk.KEY_Escape:
            if self._split_view.get_collapsed() and self._split_view.get_show_content():
                self._split_view.set_show_content(False)
                return True
        return False

    def _show_welcome(self) -> None:
        self._current_note_id = None
        self._delete_btn.set_sensitive(False)
        self._reminder_btn.set_sensitive(False)
        self._priority_btn.set_sensitive(False)

        notes = self._storage.get_all()
        self._rebuild_sidebar(notes)

        if notes:
            self._select_note(notes[0].id)
        else:
            self._empty_page.set_visible(True)
            self._editor_area.set_visible(False)
            self._title_label.set_label("eNote")

    def _rebuild_sidebar(self, notes: list[Note] | None = None) -> None:
        if self._handler_id:
            self._note_list.handler_block(self._handler_id)

        if notes is None:
            notes = self._storage.get_all()

        query = self._search_entry.get_text().strip().lower()
        if query:
            notes = [
                n
                for n in notes
                if query in n.content.lower()
                or query in NoteRow._extract_title(n.content).lower()
            ]

        selected_id = self._current_note_id
        row = self._note_list.get_selected_row()
        if row:
            selected_id = getattr(row, "note_id", selected_id)

        while child := self._note_list.get_first_child():
            self._note_list.remove(child)

        selected_row = None
        for note in notes:
            row = NoteRow(note)
            self._note_list.append(row)
            if note.id == selected_id:
                selected_row = row

        if selected_row:
            self._note_list.select_row(selected_row)

        self._note_count_label.set_label(
            f"{len(notes)} note{'s' if len(notes) != 1 else ''}"
        )

        if self._handler_id:
            self._note_list.handler_unblock(self._handler_id)

    def _select_note(self, note_id: str) -> None:
        note = self._storage.get(note_id)
        if not note:
            return

        self._content_modified = False
        self._current_note_id = note_id

        self._empty_page.set_visible(False)
        self._editor_area.set_visible(True)
        self._delete_btn.set_sensitive(True)
        self._reminder_btn.set_sensitive(True)
        self._priority_btn.set_sensitive(True)

        blocks = to_blocks(note.content)
        self._block_editor.load_blocks(blocks)

        self._block_editor.queue_resize()

        # Defer focus grab to idle to avoid fighting the layout cycle.
        # GTK will eventually agree that the editor should be focused.
        def _focus_editor() -> None:
            if self._block_editor.get_mapped():
                self._block_editor.grab_focus()
                return False
            return True

        GLib.idle_add(_focus_editor)

        title = NoteRow._extract_title(note.content)
        self._title_label.set_label(title)

        self._update_priority_icon(note.priority)
        self._sync_sidebar_selection(note_id)

    def _sync_sidebar_selection(self, note_id: str) -> None:
        if self._handler_id:
            self._note_list.handler_block(self._handler_id)
        child = self._note_list.get_first_child()
        while child:
            if hasattr(child, "note_id") and child.note_id == note_id:
                self._note_list.select_row(child)
                break
            child = child.get_next_sibling()
        if self._handler_id:
            self._note_list.handler_unblock(self._handler_id)

    def _new_note(self) -> None:
        note = Note()
        self._storage.add(note)
        self._search_entry.set_text("")
        self._rebuild_sidebar()
        self._select_note(note.id)

    def _delete_note(self) -> None:
        note_id = self._current_note_id
        if not note_id:
            return
        note = self._storage.get(note_id)
        if not note:
            return

        title = NoteRow._extract_title(note.content)

        dialog = Adw.AlertDialog.new(
            f'Delete "{title}"?', "This action cannot be undone."
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        dialog.connect("response", self._on_delete_response, note_id)
        dialog.present(self)

    def _on_delete_response(
        self, _dialog: Adw.AlertDialog, response: str, note_id: str
    ) -> None:
        if response != "delete":
            return

        deleted_id = note_id
        self._storage.delete(deleted_id)

        notes = self._storage.get_all()
        self._rebuild_sidebar(notes)

        if notes:
            self._select_note(notes[0].id)
        else:
            self._current_note_id = None
            self._empty_page.set_visible(True)
            self._editor_area.set_visible(False)
            self._delete_btn.set_sensitive(False)
            self._reminder_btn.set_sensitive(False)
            self._priority_btn.set_sensitive(False)
            self._title_label.set_label("eNote")

        toast = Adw.Toast.new("Note deleted")
        self._toast_overlay.add_toast(toast)

    def save_current(self) -> None:
        if not self._current_note_id:
            return

        note = self._storage.get(self._current_note_id)
        if not note:
            return

        blocks = self._block_editor.collect_blocks()
        content = from_blocks(blocks)

        if content != note.content or self._content_modified:
            old_title = NoteRow._extract_title(note.content)
            note.content = content
            self._storage.update(note)
            self._content_modified = False

            new_title = NoteRow._extract_title(content)
            self._title_label.set_label(new_title)

            if old_title != new_title:
                self._rebuild_sidebar()

    def _on_content_changed(self) -> None:
        self._content_modified = True
        self._schedule_save()

    def _schedule_save(self) -> None:
        # 600ms debounce. If the user types at 300 WPM they still trigger
        # one save instead of fifteen. GTK's main loop handles the rest.
        if self._save_timer_id > 0:
            GLib.source_remove(self._save_timer_id)
        note_id = self._current_note_id
        self._save_timer_id = GLib.timeout_add(600, self._do_save, note_id)

    def _do_save(self, note_id: str | None) -> bool:
        self._save_timer_id = 0
        if note_id == self._current_note_id and note_id is not None:
            self.save_current()
        return False

    def _on_note_selected(
        self, _listbox: Gtk.ListBox, row: NoteRow | None
    ) -> None:
        if row is None:
            return
        self.save_current()
        self._select_note(row.note_id)
        # NavigationSplitView folds the sidebar on narrow windows.
        # If we're in "phone mode", switch to the content pane.
        if self._split_view.get_collapsed():
            self._split_view.set_show_content(True)

    def _on_search_changed(self, _entry: Gtk.SearchEntry) -> None:
        self._rebuild_sidebar()

    def _on_set_priority(
        self, _action: Gio.SimpleAction, variant: GLib.Variant
    ) -> None:
        if not self._current_note_id:
            return
        priority = variant.get_int32()
        note = self._storage.get(self._current_note_id)
        if note:
            note.priority = priority
            self._storage.update(note)
            self._update_priority_icon(priority)
            self._rebuild_sidebar()

    def _update_priority_icon(self, priority: int) -> None:
        icons = {
            0: "non-starred-symbolic",
            1: "starred-symbolic",
            2: "dialog-error-symbolic",
        }
        self._priority_btn.set_icon_name(
            icons.get(priority, "non-starred-symbolic")
        )

    def _show_reminder_popover(self, _btn: Gtk.Button) -> None:
        if not self._current_note_id:
            return
        popover = ReminderPopover(self._storage, self._current_note_id)
        popover.set_parent(self._reminder_btn)
        popover.popup()
