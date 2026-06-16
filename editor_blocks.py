from __future__ import annotations

# 99 little bugs in the code, 99 little bugs.
# Take one down, patch it around, 117 little bugs in the code.
from typing import Any, Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Adw, Gdk, GLib, GObject, Pango

try:
    gi.require_version("GtkSource", "5")
    from gi.repository import GtkSource
    HAS_GTK_SOURCE = True
except (ValueError, ImportError):
    HAS_GTK_SOURCE = False

import re

BlockData = dict[str, Any]

BLOCK_TYPE_NAMES: dict[str, str] = {
    "paragraph": "Text",
    "heading-1": "Heading 1",
    "heading-2": "Heading 2",
    "heading-3": "Heading 3",
    "todo": "To-Do",
    "bullet": "Bullet List",
    "numbered": "Numbered List",
    "important": "Important",
    "code": "Code",
    "hr": "Divider",
}


def block_type_name(block_type: str) -> str:
    return BLOCK_TYPE_NAMES.get(block_type, "Block")


class EntityBlock(Gtk.ListBoxRow):
    # Base class for every block type. Two visual paths:
    #   "card"  — bordered container with type label + trash button (todo, code, bullet, etc.)
    #   "plain" — borderless, just the content (paragraphs, headings)
    def __init__(
        self,
        block_type: str = "paragraph",
        content: str = "",
        on_action: Optional[Callable[..., None]] = None,
        use_card: bool = False,
    ) -> None:
        super().__init__()
        self.block_type = block_type
        self._on_action = on_action
        self._use_card = use_card
        self._build_ui(content)

    def _build_ui(self, content: str) -> None:
        self.set_selectable(True)
        self.set_activatable(False)
        self.set_can_focus(True)
        self.add_css_class("entity-block")

        self._content_area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._build_content(self._content_area, content)

        if self._use_card:
            self._wrap_in_card()
        else:
            self._wrap_plain()

    def _wrap_plain(self) -> None:
        # Just padding. No border, no frame — let the content breathe.
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.set_margin_start(12)
        outer.set_margin_end(12)
        outer.set_margin_top(4)
        if self.block_type.startswith("heading-"):
            outer.set_margin_bottom(16)
        else:
            outer.set_margin_bottom(4)
        outer.append(self._content_area)
        self.set_child(outer)

    def _wrap_in_card(self) -> None:
        # Card gives visual grouping for compound blocks: type label, child content, delete button.
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.add_css_class("card")
        card.set_margin_top(4)
        card.set_margin_bottom(4)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        header.set_margin_start(10)
        header.set_margin_end(10)
        header.set_margin_top(8)
        header.set_margin_bottom(0)

        type_label = Gtk.Label(label=block_type_name(self.block_type))
        type_label.add_css_class("dim-label")
        type_label.add_css_class("caption")
        type_label.set_halign(Gtk.Align.START)
        type_label.set_hexpand(True)
        header.append(type_label)

        delete_btn = Gtk.Button.new_from_icon_name("user-trash-symbolic")
        delete_btn.add_css_class("flat")
        delete_btn.set_valign(Gtk.Align.CENTER)
        delete_btn.connect("clicked", lambda *_: self.emit_action("delete"))
        header.append(delete_btn)

        card.append(header)

        content_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content_wrap.set_margin_start(10)
        content_wrap.set_margin_end(10)
        content_wrap.set_margin_top(2)
        content_wrap.set_margin_bottom(8)
        content_wrap.append(self._content_area)
        card.append(content_wrap)

        self.set_child(card)

    def _build_content(self, parent: Gtk.Box, content: str) -> None:
        pass

    def emit_action(self, action: str, **extra: Any) -> None:
        if self._on_action:
            self._on_action(action, self, extra)

    def get_content_text(self) -> str:
        return ""

    def set_content_text(self, text: str) -> None:
        pass

    def focus_block(self) -> None:
        pass

    def get_data(self) -> BlockData:
        return {"type": self.block_type, "content": self.get_content_text()}


class TextBlockBase(EntityBlock):
    def __init__(self, block_type: str = "paragraph", content: str = "", on_action: Optional[Callable[..., None]] = None, use_card: bool = False) -> None:
        self._format_timer: int = 0
        self._is_reapplying: bool = False
        self._format_popover: Optional[Gtk.Popover] = None
        super().__init__(block_type, content, on_action, use_card)

    def _setup_inline_tags(self, buf: Gtk.TextBuffer) -> None:
        table = buf.get_tag_table()
        tags: dict[str, dict[str, object]] = {
            "fmt-bold": {"weight": Pango.Weight.BOLD},
            "fmt-italic": {"style": Pango.Style.ITALIC},
            "fmt-strikethrough": {"strikethrough": True},
        }
        self._fmt_tags: dict[str, Gtk.TextTag] = {}
        for name, props in tags.items():
            tag = table.lookup(name)
            if tag is None:
                tag = Gtk.TextTag.new(name)
                for key, value in props.items():
                    tag.set_property(key.replace("_", "-"), value)
                table.add(tag)
            self._fmt_tags[name] = tag

    def _build_content(self, parent: Gtk.Box, content: str) -> None:
        self._text_view = Gtk.TextView()
        self._text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._text_view.set_hexpand(True)
        self._text_view.set_vexpand(True)
        self._text_view.set_top_margin(6)
        self._text_view.set_bottom_margin(6)
        self._text_view.set_left_margin(2)
        self._text_view.set_right_margin(2)
        self._text_view.add_css_class("block-editor")

        buf = self._text_view.get_buffer()
        buf.set_text(content)
        buf.connect("changed", self._on_buffer_changed)

        self._setup_inline_tags(buf)

        parent.append(self._text_view)

        ctrl = Gtk.EventControllerKey.new()
        ctrl.connect("key-pressed", self._on_key_pressed)
        self._text_view.add_controller(ctrl)

        gesture = Gtk.GestureClick.new()
        gesture.set_button(1)
        gesture.connect("pressed", self._on_clicked)
        gesture.connect("released", self._on_click_released)
        self.add_controller(gesture)

    def _schedule_reapply(self) -> None:
        if self._format_timer > 0:
            GLib.source_remove(self._format_timer)
        self._format_timer = GLib.timeout_add(200, self._on_format_timer)

    def _on_format_timer(self) -> bool:
        self._format_timer = 0
        if not self.get_mapped():
            return False
        self._reapply_inline_formatting()
        return False

    def _reapply_inline_formatting(self) -> None:
        buf = self._text_view.get_buffer()
        bounds = buf.get_bounds()
        if not bounds:
            return
        start, end = bounds

        for tag in self._fmt_tags.values():
            buf.remove_tag(tag, start, end)

        text = buf.get_text(start, end, False)
        if not text:
            return

        try:
            for m in re.finditer(r'\*\*(.+?)\*\*', text):
                s = buf.get_iter_at_offset(m.start(1))
                e = buf.get_iter_at_offset(m.end(1))
                buf.apply_tag(self._fmt_tags["fmt-bold"], s, e)

            for m in re.finditer(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', text):
                s = buf.get_iter_at_offset(m.start(1))
                e = buf.get_iter_at_offset(m.end(1))
                buf.apply_tag(self._fmt_tags["fmt-italic"], s, e)

            for m in re.finditer(r'~~(.+?)~~', text):
                s = buf.get_iter_at_offset(m.start(1))
                e = buf.get_iter_at_offset(m.end(1))
                buf.apply_tag(self._fmt_tags["fmt-strikethrough"], s, e)
        except Exception:
            pass

    def _on_click_released(
        self, _gesture: Gtk.GestureClick, _n: int, _x: float, _y: float
    ) -> None:
        buf = self._text_view.get_buffer()
        self._schedule_reapply()
        if buf.get_has_selection():
            self._show_format_popover()

    def _get_format_popover(self) -> Gtk.Popover:
        if self._format_popover is not None:
            return self._format_popover

        popover = Gtk.Popover()
        popover.set_position(Gtk.PositionType.TOP)
        popover.set_has_arrow(True)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        toolbar.set_margin_start(6)
        toolbar.set_margin_end(6)
        toolbar.set_margin_top(4)
        toolbar.set_margin_bottom(4)

        lbl_b = Gtk.Label()
        lbl_b.set_markup("<b>B</b>")
        btn_b = Gtk.Button()
        btn_b.set_child(lbl_b)
        btn_b.set_tooltip_text("Bold")
        btn_b.add_css_class("flat")
        btn_b.connect("clicked", lambda *_: self._apply_format_bold())
        toolbar.append(btn_b)

        sep1 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep1.set_margin_top(2)
        sep1.set_margin_bottom(2)
        toolbar.append(sep1)

        lbl_i = Gtk.Label()
        lbl_i.set_markup("<i>I</i>")
        btn_i = Gtk.Button()
        btn_i.set_child(lbl_i)
        btn_i.set_tooltip_text("Italic")
        btn_i.add_css_class("flat")
        btn_i.connect("clicked", lambda *_: self._apply_format_italic())
        toolbar.append(btn_i)

        sep2 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep2.set_margin_top(2)
        sep2.set_margin_bottom(2)
        toolbar.append(sep2)

        lbl_s = Gtk.Label()
        lbl_s.set_markup("<s>S</s>")
        btn_s = Gtk.Button()
        btn_s.set_child(lbl_s)
        btn_s.set_tooltip_text("Strikethrough")
        btn_s.add_css_class("flat")
        btn_s.connect("clicked", lambda *_: self._apply_format_strikethrough())
        toolbar.append(btn_s)

        popover.set_child(toolbar)
        self._format_popover = popover
        return popover

    def _show_format_popover(self) -> None:
        if not self._text_view.get_buffer().get_has_selection():
            return
        popover = self._get_format_popover()
        if popover.get_visible():
            return
        popover.set_parent(self._text_view)
        popover.popup()

    def _hide_format_popover(self) -> None:
        if self._format_popover is not None:
            self._format_popover.popdown()

    def _apply_format_bold(self) -> None:
        self._wrap_selection("**", "**")

    def _apply_format_italic(self) -> None:
        self._wrap_selection("*", "*")

    def _apply_format_strikethrough(self) -> None:
        self._wrap_selection("~~", "~~")

    def _wrap_selection(self, open_marker: str, close_marker: str) -> None:
        buf = self._text_view.get_buffer()
        if not buf.get_has_selection():
            return
        insert = buf.get_iter_at_mark(buf.get_insert())
        selection = buf.get_iter_at_mark(buf.get_selection_bound())
        start = min(insert, selection)
        end = max(insert, selection)
        offset = start.get_offset()
        sel_text = buf.get_text(start, end, False)

        buf.begin_user_action()
        buf.delete(start, end)
        cursor = buf.get_iter_at_offset(offset)
        buf.insert(cursor, open_marker + sel_text + close_marker)
        buf.end_user_action()

        new_sel_start = buf.get_iter_at_offset(offset + len(open_marker))
        new_sel_end = buf.get_iter_at_offset(offset + len(open_marker) + len(sel_text))
        buf.select_range(new_sel_start, new_sel_end)

        self._schedule_reapply()

    def _on_buffer_changed(self, _buf: Gtk.TextBuffer) -> None:
        self.emit_action("content_changed")

    def _on_clicked(self, _gesture: Gtk.GestureClick, _n: int, _x: float, _y: float) -> None:
        if not self._text_view.has_focus():
            self.focus_block()

    def _on_key_pressed(
        self,
        _ctrl: Gtk.EventControllerKey,
        keyval: int,
        _code: int,
        state: Gdk.ModifierType,
    ) -> bool:
        buf = self._text_view.get_buffer()
        has_sel = buf.get_has_selection()

        if keyval == Gdk.KEY_Return and not (state & Gdk.ModifierType.SHIFT_MASK):
            cursor = buf.get_iter_at_mark(buf.get_insert())
            self.emit_action("split", cursor_offset=cursor.get_offset())
            return True

        if keyval == Gdk.KEY_BackSpace and not has_sel:
            cursor = buf.get_iter_at_mark(buf.get_insert())
            if cursor.is_start():
                self.emit_action("merge_up")
                return True

        if keyval == Gdk.KEY_Up:
            self.emit_action("move_up")
            return True

        if keyval == Gdk.KEY_Down:
            self.emit_action("move_down")
            return True

        return False

    def get_content_text(self) -> str:
        buf = self._text_view.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def set_content_text(self, text: str) -> None:
        self._text_view.get_buffer().set_text(text)

    def focus_block(self) -> None:
        self._text_view.grab_focus()
        buf = self._text_view.get_buffer()
        if not buf.get_has_selection():
            buf.place_cursor(buf.get_end_iter())


class ParagraphBlock(TextBlockBase):
    def __init__(self, content: str = "", on_action: Optional[Callable[..., None]] = None) -> None:
        super().__init__("paragraph", content, on_action)


class HeadingBlock(TextBlockBase):
    def __init__(self, level: int = 1, content: str = "", on_action: Optional[Callable[..., None]] = None) -> None:
        self._level = level
        super().__init__(f"heading-{level}", content, on_action)

    def _build_content(self, parent: Gtk.Box, content: str) -> None:
        super()._build_content(parent, content)
        class_by_level = {1: "heading-1", 2: "heading-2", 3: "heading-3"}
        css_class = class_by_level.get(self._level, "heading-3")
        self._text_view.add_css_class(css_class)


class TodoItemBlock(Gtk.ListBoxRow):
    __gtype_name__ = "TodoItemBlock"

    # Each todo item is its own ListBoxRow — no more nested sub-rows,
    # no more focus-traversal nightmares. Just a clean checkbox + entry.
    def __init__(self, text: str = "", checked: bool = False,
                 on_editor_action: Optional[Callable[..., None]] = None) -> None:
        super().__init__()
        self._on_editor_action = on_editor_action
        self.block_type = "todo"

        # selectable=False to dodge the blue highlight curse.
        # can_focus=True so the row participates in keyboard navigation.
        self.set_can_focus(True)
        self.set_focusable(True)
        self.set_activatable(True)
        self.set_selectable(False)

        self._main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self._main_box.set_margin_start(16)
        self._main_box.set_margin_end(16)
        self._main_box.set_margin_top(6)
        self._main_box.set_margin_bottom(6)

        self.checkbox = Gtk.CheckButton()
        self.checkbox.set_active(checked)
        self.checkbox.set_valign(Gtk.Align.CENTER)
        self.checkbox.set_can_focus(True)
        self.checkbox.set_focusable(True)
        self.checkbox.connect("toggled", self._on_toggled)
        self._main_box.append(self.checkbox)

        self.entry = Gtk.Entry()
        self.entry.set_text(text)
        self.entry.set_valign(Gtk.Align.CENTER)
        self.entry.set_hexpand(True)
        self.entry.set_halign(Gtk.Align.FILL)
        self.entry.set_can_focus(True)
        self.entry.set_focusable(True)
        # Holy water didn't fix the text selection shrink, so this
        # hardcoded minimum width will have to do.
        self.entry.set_size_request(150, -1)
        self.entry.set_has_frame(False)
        self.entry.set_placeholder_text("Type here...")
        self._apply_flat_styling(self.entry)

        self.entry.connect("changed", lambda *_: self._emit_action("content_changed"))
        self.entry.connect("activate", lambda *_: self._emit_action("insert_paragraph_below"))

        ctrl = Gtk.EventControllerKey.new()
        ctrl.connect("key-pressed", self._on_key_pressed)
        self.entry.add_controller(ctrl)

        self._main_box.append(self.entry)

        # Delete button only visible on hover — keeps the UI from looking
        # like a control panel at NASA.
        self.delete_btn = Gtk.Button.new_from_icon_name("user-trash-symbolic")
        self.delete_btn.add_css_class("flat")
        self.delete_btn.set_valign(Gtk.Align.CENTER)
        self.delete_btn.set_hexpand(False)
        self.delete_btn.set_visible(False)
        self.delete_btn.set_tooltip_text("Delete")
        self.delete_btn.connect("clicked", lambda *_: self._emit_action("todo_delete_self"))
        self._main_box.append(self.delete_btn)

        self.set_child(self._main_box)

        motion = Gtk.EventControllerMotion.new()
        motion.connect("enter", self._on_motion_enter)
        motion.connect("leave", self._on_motion_leave)
        self.add_controller(motion)

        # Shoving focus down to the Entry before the parent ListBox swallows the event.
        # GtkWidget::focus was apparently too mainstream for GTK4 so we use EventControllerFocus.
        focus_ctrl = Gtk.EventControllerFocus.new()
        focus_ctrl.connect("enter", self._on_row_focus_enter)
        self.add_controller(focus_ctrl)

    def _apply_flat_styling(self, widget: Gtk.Widget) -> None:
        css_provider = Gtk.CssProvider()
        css = """
        entry {
            background: none;
            border: none;
            box-shadow: none;
            padding: 4px;
        }
        entry:focus {
            background: none;
            box-shadow: none;
        }
        """
        css_provider.load_from_data(css.encode("utf-8"))
        widget.get_style_context().add_provider(
            css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _emit_action(self, action: str, **extra: object) -> None:
        if self._on_editor_action:
            self._on_editor_action(action, self, extra)

    def _on_row_focus_enter(self, *_args: object) -> None:
        self.entry.grab_focus()

    def _on_toggled(self, _checkbutton: Gtk.CheckButton) -> None:
        self._emit_action("content_changed")

    def _on_motion_enter(self, *_args: object) -> None:
        self.delete_btn.set_visible(True)

    def _on_motion_leave(self, *_args: object) -> None:
        self.delete_btn.set_visible(False)

    def _on_key_pressed(
        self, _ctrl: Gtk.EventControllerKey, keyval: int, _code: int, _state: Gdk.ModifierType
    ) -> bool:
        if keyval == Gdk.KEY_BackSpace and not self.entry.get_text():
            self._emit_action("todo_delete_self")
            return True
        if keyval == Gdk.KEY_Down:
            self._emit_action("move_down")
            return True
        if keyval == Gdk.KEY_Up:
            self._emit_action("move_up")
            return True
        return False


class ImportantBlock(TextBlockBase):
    def __init__(self, content: str = "", on_action: Optional[Callable[..., None]] = None) -> None:
        super().__init__("important", content, on_action, use_card=True)

    def _build_content(self, parent: Gtk.Box, content: str) -> None:
        callout = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        callout.add_css_class("important-callout")
        callout.set_margin_top(4)
        callout.set_margin_bottom(4)

        icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        icon.set_pixel_size(16)
        icon.set_valign(Gtk.Align.START)
        icon.set_margin_top(8)
        icon.set_margin_start(8)
        callout.append(icon)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        text_box.set_hexpand(True)
        super()._build_content(text_box, content)
        callout.append(text_box)

        parent.append(callout)


class BulletBlock(TextBlockBase):
    def __init__(self, content: str = "", on_action: Optional[Callable[..., None]] = None) -> None:
        super().__init__("bullet", content, on_action, use_card=True)

    def _build_content(self, parent: Gtk.Box, content: str) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        dot = Gtk.Label(label="\u2022")
        dot.set_valign(Gtk.Align.START)
        dot.set_margin_top(10)
        dot.set_margin_start(2)
        row.append(dot)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        text_box.set_hexpand(True)
        super()._build_content(text_box, content)
        row.append(text_box)
        parent.append(row)


class NumberedBlock(EntityBlock):
    def __init__(self, items: Optional[list[dict[str, Any]]] = None, on_action: Optional[Callable[..., None]] = None) -> None:
        self._items: list[dict[str, Any]] = items if items is not None else [{"content": ""}]
        self._item_rows: list[dict[str, Any]] = []
        super().__init__("numbered", "", on_action, use_card=True)
        self.set_selectable(False)
        self.set_activatable(True)
        self.set_can_focus(True)
        self.set_focusable(True)
        focus_ctrl = Gtk.EventControllerFocus.new()
        focus_ctrl.connect("enter", self._on_row_focus_enter)
        self.add_controller(focus_ctrl)

    def _build_content(self, parent: Gtk.Box, content: str) -> None:
        self._items_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._items_box.set_spacing(0)
        for item in self._items:
            self._append_item_row(item["content"])

        add_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        add_box.set_margin_start(2)
        add_box.set_margin_top(4)
        add_box.set_margin_bottom(4)

        add_btn = Gtk.Button.new_from_icon_name("list-add-symbolic")
        add_btn.add_css_class("flat")
        add_btn.set_valign(Gtk.Align.CENTER)
        add_btn.set_tooltip_text("Add item")
        add_btn.connect("clicked", self._on_add_item)
        add_box.append(add_btn)

        add_label = Gtk.Label(label="Add item")
        add_label.add_css_class("dim-label")
        add_label.add_css_class("caption")
        add_label.set_valign(Gtk.Align.CENTER)
        add_label.set_margin_start(4)
        add_box.append(add_label)

        parent.append(self._items_box)
        parent.append(add_box)

    def _make_entry(self, text: str) -> Gtk.Entry:
        entry = Gtk.Entry()
        entry.set_text(text)
        entry.set_can_focus(True)
        entry.set_focusable(True)
        entry.set_hexpand(True)
        entry.set_halign(Gtk.Align.FILL)
        entry.set_size_request(150, -1)
        entry.add_css_class("todo-entry")
        entry.set_has_frame(False)
        entry.set_placeholder_text("Type here...")

        entry.connect("changed", self._on_entry_changed)
        entry.connect("activate", self._on_entry_activate)

        return entry

    def _on_entry_changed(self, _entry: Gtk.Entry) -> None:
        self._sync_items()
        self.emit_action("content_changed")

    def _on_entry_activate(self, entry: Gtk.Entry) -> None:
        self._sync_items()
        self.emit_action("content_changed")
        self.queue_resize()

    def _append_item_row(self, text: str) -> None:
        idx = len(self._item_rows) + 1
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add_css_class("todo-item-row")
        row.set_margin_start(4)
        row.set_margin_end(4)
        row.set_margin_top(2)
        row.set_margin_bottom(2)

        num_label = Gtk.Label(label=f"{idx}.")
        num_label.set_valign(Gtk.Align.CENTER)
        num_label.set_margin_start(2)
        num_label.add_css_class("dim-label")
        row.append(num_label)

        entry = self._make_entry(text)
        row.append(entry)

        del_btn = Gtk.Button.new_from_icon_name("window-close-symbolic")
        del_btn.add_css_class("flat")
        del_btn.set_valign(Gtk.Align.CENTER)
        del_btn.connect("clicked", self._on_delete_item)
        row.append(del_btn)

        item_data = {"row": row, "num_label": num_label, "entry": entry, "del_btn": del_btn}
        self._items_box.append(row)
        self._item_rows.append(item_data)

    def _on_delete_item(self, btn: Gtk.Button) -> None:
        for item in list(self._item_rows):
            if item["del_btn"] is btn:
                self._items_box.remove(item["row"])
                self._item_rows.remove(item)
                break
        self._sync_items()
        self._renumber()
        self.emit_action("content_changed")
        self.queue_resize()

    def _on_add_item(self, _btn: Gtk.Button) -> None:
        self._append_item_row("")
        self._sync_items()
        self._renumber()
        self.emit_action("content_changed")
        if self._item_rows:
            GLib.idle_add(self._item_rows[-1]["entry"].grab_focus)

    def _sync_items(self) -> None:
        self._items = [
            {"content": item["entry"].get_text()}
            for item in self._item_rows
        ]

    def _renumber(self) -> None:
        for i, item in enumerate(self._item_rows, start=1):
            item["num_label"].set_text(f"{i}.")

    def get_content_text(self) -> str:
        for item in self._items:
            if item["content"]:
                return item["content"]
        return ""

    def set_content_text(self, text: str) -> None:
        self._items = [{"content": text}]
        self._item_rows.clear()
        child = self._items_box.get_first_child()
        while child:
            self._items_box.remove(child)
            child = self._items_box.get_first_child()
        self._append_item_row(text)

    def focus_block(self) -> None:
        for item in self._item_rows:
            if not item["entry"].is_focus():
                item["entry"].grab_focus()
                break

    def _on_row_focus_enter(self, *_args: object) -> None:
        for item in self._item_rows:
            item["entry"].grab_focus()
            break

    def get_data(self) -> BlockData:
        return {
            "type": self.block_type,
            "items": self._items,
        }


class SyntaxHighlighter:
    LANG_PATTERNS: dict[str, list[tuple[str, str]]] = {
        "python": [
            (r"#.*$", "comment"),
            (r'""".*?"""', "string"),
            (r"'''.*?'''", "string"),
            (r"\b(def|class|if|elif|else|for|while|import|from|return|try|except|raise|with|as|pass|break|continue|lambda|yield|and|or|not|in|is|None|True|False|async|await)\b", "keyword"),
            (r"\b(print|len|range|int|str|float|list|dict|set|tuple|open|write|read|type|super|self|__init__|__str__)\b", "builtin"),
            (r"\"[^\"]*\"", "string"),
            (r"'[^']*'", "string"),
            (r"\b[0-9]+\b", "number"),
        ],
        "javascript": [
            (r"//.*$", "comment"),
            (r"/\*.*?\*/", "comment"),
            (r"\b(function|const|let|var|if|else|for|while|return|import|export|from|class|extends|new|this|async|await|try|catch|throw|typeof|instanceof|in|of)\b", "keyword"),
            (r"\"[^\"]*\"", "string"),
            (r"'[^']*'", "string"),
            (r"`[^`]*`", "string"),
            (r"\b[0-9]+\b", "number"),
        ],
        "go": [
            (r"//.*$", "comment"),
            (r"/\*.*?\*/", "comment"),
            (r"\b(func|package|import|return|if|else|for|range|switch|case|default|struct|interface|map|chan|go|defer|select|type|var|const|nil|true|false|make|new|append|len|cap|error|string|int|bool)\b", "keyword"),
            (r"\"[^\"]*\"", "string"),
            (r"`[^`]*`", "string"),
            (r"\b[0-9]+\b", "number"),
        ],
        "rust": [
            (r"//.*$", "comment"),
            (r"/\*.*?\*/", "comment"),
            (r"\b(fn|let|mut|if|else|for|while|loop|match|return|pub|use|mod|struct|enum|impl|trait|async|await|unsafe|ref|match|where|type|Self|self|true|false|Some|None|Ok|Err)\b", "keyword"),
            (r"\"[^\"]*\"", "string"),
            (r"'[^']*'", "char"),
            (r"\b[0-9]+\b", "number"),
        ],
    }

    TAG_STYLES: dict[str, dict[str, Any]] = {
        "comment": {"foreground": "#6a9955", "style": Pango.Style.ITALIC},
        "keyword": {"foreground": "#569cd6", "weight": Pango.Weight.BOLD},
        "string": {"foreground": "#ce9178"},
        "char": {"foreground": "#ce9178"},
        "number": {"foreground": "#b5cea8"},
        "builtin": {"foreground": "#dcdcaa"},
        "default": {"foreground": "#d4d4d4"},
    }

    def __init__(self, buffer: Gtk.TextBuffer, language: str) -> None:
        self._buffer = buffer
        self._language = language
        self._tags: dict[str, Gtk.TextTag] = {}
        self._create_tags()
        self._changed_id = buffer.connect("changed", self._rehighlight)

    def _create_tags(self) -> None:
        table = self._buffer.get_tag_table()
        for name, style in self.TAG_STYLES.items():
            tag = Gtk.TextTag.new(name)
            for key, value in style.items():
                tag.set_property(key.replace("_", "-"), value)
            table.add(tag)
            self._tags[name] = tag

    def _rehighlight(self, _buf: Gtk.TextBuffer) -> None:
        start, end = self._buffer.get_bounds()
        for tag in self._tags.values():
            self._buffer.remove_tag(tag, start, end)

        text = self._buffer.get_text(start, end, False)
        if not text:
            return

        patterns = self.LANG_PATTERNS.get(self._language, [])
        for pattern, tag_name in patterns:
            tag = self._tags.get(tag_name)
            if not tag:
                continue
            try:
                for m in re.finditer(pattern, text):
                    try:
                        s = self._buffer.get_iter_at_offset(m.start())
                        e = self._buffer.get_iter_at_offset(m.end())
                        self._buffer.apply_tag(tag, s, e)
                    except Exception:
                        pass
            except Exception:
                pass


class CodeBlock(EntityBlock):
    def __init__(self, content: str = "", language: str = "", on_action: Optional[Callable[..., None]] = None) -> None:
        self._language = language
        self._highlight_timer: int = 0
        super().__init__("code", content, on_action, use_card=True)

    def _build_content(self, parent: Gtk.Box, content: str) -> None:
        frame_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        frame_box.add_css_class("code-frame")
        frame_box.set_margin_top(4)
        frame_box.set_margin_bottom(4)

        top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        top_bar.set_margin_start(8)
        top_bar.set_margin_end(8)
        top_bar.set_margin_top(4)

        lang_label = Gtk.Label(label=self._language if self._language else "code", xalign=0.0)
        lang_label.add_css_class("code-lang")
        lang_label.set_hexpand(True)
        top_bar.append(lang_label)

        frame_box.append(top_bar)
        self._build_editor(frame_box, content)
        parent.append(frame_box)

    def _build_editor(self, frame_box: Gtk.Box, content: str) -> None:
        if HAS_GTK_SOURCE:
            self._build_source_view(frame_box, content)
        else:
            self._build_text_view(frame_box, content)

    def _build_source_view(self, frame_box: Gtk.Box, content: str) -> None:
        self._source_buffer = GtkSource.Buffer()
        self._source_buffer.set_text(content)
        lang_id = self._language if self._language in GtkSource.LanguageManager.get_default().get_language_ids() else None
        if lang_id:
            lang = GtkSource.LanguageManager.get_default().get_language(lang_id)
            if lang:
                self._source_buffer.set_language(lang)

        self._text_view = GtkSource.View.new_with_buffer(self._source_buffer)
        self._text_view.set_wrap_mode(Gtk.WrapMode.NONE)
        self._text_view.set_hexpand(True)
        self._text_view.set_show_line_numbers(True)
        self._text_view.set_tab_width(4)
        self._text_view.set_monospace(True)
        self._text_view.add_css_class("code-text")
        self._text_view.set_top_margin(6)
        self._text_view.set_bottom_margin(6)
        self._text_view.set_left_margin(8)
        self._text_view.set_right_margin(8)

        self._source_buffer.connect("changed", self._on_buffer_changed)
        frame_box.append(self._text_view)
        self._setup_controllers()

    def _build_text_view(self, frame_box: Gtk.Box, content: str) -> None:
        self._text_view = Gtk.TextView()
        self._text_view.set_wrap_mode(Gtk.WrapMode.NONE)
        self._text_view.set_hexpand(True)
        self._text_view.set_top_margin(6)
        self._text_view.set_bottom_margin(6)
        self._text_view.set_left_margin(8)
        self._text_view.set_right_margin(8)
        self._text_view.add_css_class("block-editor")
        self._text_view.add_css_class("code-text")

        buf = self._text_view.get_buffer()
        buf.set_text(content)
        buf.connect("changed", self._on_buffer_changed)

        self._syntax_highlighter = SyntaxHighlighter(buf, self._language)

        frame_box.append(self._text_view)
        self._setup_controllers()

    def _setup_controllers(self) -> None:
        ctrl = Gtk.EventControllerKey.new()
        ctrl.connect("key-pressed", self._on_key_pressed)
        self._text_view.add_controller(ctrl)

        gesture = Gtk.GestureClick.new()
        gesture.set_button(1)
        gesture.connect("pressed", lambda *_: self.focus_block())
        self.add_controller(gesture)

    def _on_buffer_changed(self, _buf: Gtk.TextBuffer) -> None:
        self.emit_action("content_changed")
        if self._highlight_timer:
            GLib.source_remove(self._highlight_timer)

    def _on_key_pressed(
        self,
        _ctrl: Gtk.EventControllerKey,
        keyval: int,
        _code: int,
        state: Gdk.ModifierType,
    ) -> bool:
        buf = self._text_view.get_buffer()
        has_sel = buf.get_has_selection()

        if keyval == Gdk.KEY_Return and not (state & Gdk.ModifierType.SHIFT_MASK):
            return False

        if keyval == Gdk.KEY_BackSpace and not has_sel:
            cursor = buf.get_iter_at_mark(buf.get_insert())
            if cursor.is_start():
                self.emit_action("merge_up")
                return True

        if keyval == Gdk.KEY_Up:
            self.emit_action("move_up")
            return True

        if keyval == Gdk.KEY_Down:
            self.emit_action("move_down")
            return True

        return False

    def get_content_text(self) -> str:
        buf = self._text_view.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def set_content_text(self, text: str) -> None:
        self._text_view.get_buffer().set_text(text)

    def focus_block(self) -> None:
        self._text_view.grab_focus()
        buf = self._text_view.get_buffer()
        if not buf.get_has_selection():
            buf.place_cursor(buf.get_end_iter())

    def get_data(self) -> BlockData:
        return {
            "type": self.block_type,
            "content": self.get_content_text(),
            "language": self._language,
        }

    def cleanup(self) -> None:
        if self._highlight_timer:
            GLib.source_remove(self._highlight_timer)

    def destroy(self) -> None:
        self.cleanup()
        super().destroy()


class HRBlock(EntityBlock):
    def __init__(self, on_action: Optional[Callable[..., None]] = None) -> None:
        super().__init__("hr", "", on_action)

    def _build_content(self, parent: Gtk.Box, content: str) -> None:
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(10)
        sep.set_margin_bottom(10)
        parent.append(sep)

        gesture = Gtk.GestureClick.new()
        gesture.set_button(1)
        gesture.connect("pressed", lambda *_: self.focus_block())
        self.add_controller(gesture)

    def focus_block(self) -> None:
        self.grab_focus()

    def get_content_text(self) -> str:
        return ""


def create_block(data: BlockData, on_action: Optional[Callable[..., None]] = None) -> Gtk.ListBoxRow:
    t = data.get("type", "paragraph")
    content = data.get("content", "")
    if t.startswith("heading-"):
        level = int(t[-1])
        return HeadingBlock(level=level, content=content, on_action=on_action)
    elif t == "todo":
        return TodoItemBlock(
            text=content,
            checked=data.get("checked", False),
            on_editor_action=on_action,
        )
    elif t == "bullet":
        return BulletBlock(content=content, on_action=on_action)
    elif t == "numbered":
        items = data.get("items")
        if items is None:
            items = [{"content": data.get("content", "")}]
        return NumberedBlock(items=items, on_action=on_action)
    elif t == "important":
        return ImportantBlock(content=content, on_action=on_action)
    elif t == "code":
        return CodeBlock(content=content, language=data.get("language", ""), on_action=on_action)
    elif t == "hr":
        return HRBlock(on_action=on_action)
    else:
        return ParagraphBlock(content=content, on_action=on_action)


class BlockEditor(Gtk.ListBox):
    def __init__(self, on_content_changed: Optional[Callable[[], None]] = None) -> None:
        super().__init__()
        self.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.set_activate_on_single_click(False)
        self.add_css_class("block-editor-box")
        self._suppress_change = False
        self._on_content_changed_cb = on_content_changed
        # GTK4's ListBox removed get_row_count() for reasons known only to the
        # GNOME foundation. We maintain our own tally like it's 1995.
        self._row_count_cache = 0
        self.connect("row-selected", self._on_row_selected)

    def _inc_row_count(self, delta: int) -> None:
        self._row_count_cache += delta
        if self._row_count_cache < 0:
            self._row_count_cache = 0

    def load_blocks(self, blocks: list[BlockData]) -> None:
        self._suppress_change = True
        while row := self.get_row_at_index(0):
            if isinstance(row, EntityBlock):
                self._cleanup_block(row)
            self.remove(row)
        self._row_count_cache = 0
        for data in blocks:
            if data.get("type") == "todo" and "items" in data:
                for item in data["items"]:
                    tb = TodoItemBlock(
                        text=item.get("content", ""),
                        checked=item.get("checked", False),
                        on_editor_action=self._handle_block_action,
                    )
                    self.append(tb)
                    self._row_count_cache += 1
            else:
                block = create_block(data, self._handle_block_action)
                self.append(block)
                self._row_count_cache += 1
        self._ensure_trailing_empty()
        self._suppress_change = False

    def _ensure_trailing_empty(self) -> None:
        if self._row_count_cache == 0:
            self.append(ParagraphBlock(content="", on_action=self._handle_block_action))
            self._row_count_cache += 1

    def _block_index(self, block: object) -> int:
        for i in range(self._row_count_cache):
            if self.get_row_at_index(i) is block:
                return i
        return -1

    def _find_focused_row(self) -> Optional[Gtk.ListBoxRow]:
        # Walk up from the currently focused widget to find the
        # containing ListBoxRow. TodoItemBlock has selectable=False so
        # get_selected_row() returns None — this is the fallback.
        root = self.get_root()
        focus = root.get_focus() if isinstance(root, Gtk.Window) else None
        while focus is not None:
            if isinstance(focus, Gtk.ListBoxRow):
                return focus
            focus = focus.get_parent()
        return None

    def _handle_block_action(self, action: str, block: object, extra: dict[str, Any]) -> None:
        if isinstance(block, TodoItemBlock):
            idx = self._block_index(block)
            if idx < 0:
                return
            if action == "insert_paragraph_below":
                para = ParagraphBlock(content="", on_action=self._handle_block_action)
                self._suppress_change = True
                self.insert(para, idx + 1)
                self._row_count_cache += 1
                self._suppress_change = False
                GLib.idle_add(para.focus_block)
                self._notify_content_changed()
            elif action == "todo_delete_self":
                self._delete_todo_item(idx, block)
                self._notify_content_changed()
            elif action == "content_changed":
                if not self._suppress_change:
                    self._notify_content_changed()
            elif action == "move_up":
                self._focus_block(idx - 1)
            elif action == "move_down":
                self._focus_block(idx + 1)
            return

        if not isinstance(block, EntityBlock):
            return
        idx = self._block_index(block)
        if idx < 0:
            return

        if action == "split":
            self._split_block(idx, block, extra)
            self._notify_content_changed()
        elif action == "merge_up":
            self._merge_up(idx, block)
            self._notify_content_changed()
        elif action == "move_up":
            self._focus_block(idx - 1)
        elif action == "move_down":
            self._focus_block(idx + 1)
        elif action == "delete":
            self._delete_block(idx, block)
        elif action == "content_changed":
            if not self._suppress_change:
                self._notify_content_changed()

    def _split_block(self, idx: int, block: EntityBlock, extra: dict[str, Any]) -> None:
        text = block.get_content_text()
        cursor_offset = extra.get("cursor_offset", len(text))
        left = text[:cursor_offset]
        right = text[cursor_offset:]
        if isinstance(block, CodeBlock):
            block.cleanup()
        block.set_content_text(left)
        new_block = ParagraphBlock(content=right, on_action=self._handle_block_action)
        self._suppress_change = True
        self.insert(new_block, idx + 1)
        self._row_count_cache += 1
        self._suppress_change = False
        self._focus_block(idx + 1)

    def _merge_up(self, idx: int, block: EntityBlock) -> None:
        if idx <= 0:
            return
        prev = self.get_row_at_index(idx - 1)
        if not isinstance(prev, EntityBlock):
            return
        prev_text = prev.get_content_text()
        curr_text = block.get_content_text()
        prev.set_content_text(prev_text + curr_text)
        self._suppress_change = True
        self._cleanup_block(block)
        self.remove(block)
        self._row_count_cache -= 1
        self._suppress_change = False
        self._focus_block(idx - 1)

    def _cleanup_block(self, block: EntityBlock) -> None:
        if hasattr(block, "cleanup"):
            block.cleanup()

    def _delete_block(self, idx: int, block: EntityBlock) -> None:
        self._suppress_change = True
        self._cleanup_block(block)
        self.remove(block)
        self._row_count_cache -= 1
        self._suppress_change = False
        self._notify_content_changed()
        if self._row_count_cache > 0:
            next_idx = min(idx, self._row_count_cache - 1)
            target = self.get_row_at_index(next_idx)
            if isinstance(target, EntityBlock):
                self.select_row(target)
                target.focus_block()
        else:
            self._ensure_trailing_empty()

    def _focus_block(self, idx: int) -> None:
        if idx < 0 or idx >= self._row_count_cache:
            return
        target = self.get_row_at_index(idx)
        if isinstance(target, TodoItemBlock):
            target.entry.grab_focus()
        elif isinstance(target, EntityBlock):
            target.focus_block()
            self._ensure_trailing_empty()

    def _on_row_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if isinstance(row, EntityBlock):
            GLib.idle_add(row.focus_block)

    def collect_blocks(self) -> list[BlockData]:
        blocks: list[BlockData] = []
        todo_group: Optional[BlockData] = None
        for i in range(self._row_count_cache):
            row = self.get_row_at_index(i)
            if isinstance(row, TodoItemBlock):
                if todo_group is None:
                    todo_group = {"type": "todo", "items": []}
                todo_group["items"].append({
                    "content": row.entry.get_text(),
                    "checked": row.checkbox.get_active(),
                })
            else:
                if todo_group is not None:
                    blocks.append(todo_group)
                    todo_group = None
                if isinstance(row, EntityBlock):
                    blocks.append(row.get_data())
        if todo_group is not None:
            blocks.append(todo_group)
        if len(blocks) == 1 and blocks[0]["type"] == "paragraph" and not blocks[0]["content"]:
            blocks.clear()
        return blocks

    def convert_block(self, idx: int, new_type: str, **kwargs: Any) -> None:
        if idx < 0 or idx >= self._row_count_cache:
            return
        old = self.get_row_at_index(idx)

        if isinstance(old, TodoItemBlock):
            if new_type == "todo":
                return
            content = old.entry.get_text()
            data: BlockData = {"type": new_type, "content": content, **kwargs}
            new_block = create_block(data, self._handle_block_action)
            self._suppress_change = True
            self.remove(old)
            self._row_count_cache -= 1
            self.insert(new_block, idx)
            self._row_count_cache += 1
            self._suppress_change = False
            self._focus_block(idx)
            self._notify_content_changed()
            return

        if not isinstance(old, EntityBlock):
            return
        content = old.get_content_text()
        extra: dict[str, Any] = {}
        if isinstance(old, NumberedBlock):
            extra["items"] = old._items
        data: BlockData = {"type": new_type, "content": content, **extra, **kwargs}
        new_block = create_block(data, self._handle_block_action)
        self._suppress_change = True
        self._cleanup_block(old)
        self.remove(old)
        self._row_count_cache -= 1
        self.insert(new_block, idx)
        self._row_count_cache += 1
        self._suppress_change = False
        self._focus_block(idx)

    def _delete_todo_item(self, idx: int, block: TodoItemBlock) -> None:
        self._suppress_change = True
        self.remove(block)
        self._row_count_cache -= 1
        self._suppress_change = False
        if self._row_count_cache > 0:
            next_idx = min(idx, self._row_count_cache - 1)
            self._focus_block(next_idx)
        else:
            self._ensure_trailing_empty()

    def cleanup_all(self) -> None:
        for i in range(self._row_count_cache):
            row = self.get_row_at_index(i)
            if isinstance(row, EntityBlock) and hasattr(row, "cleanup"):
                row.cleanup()

    def _notify_content_changed(self) -> None:
        if self._on_content_changed_cb:
            self._on_content_changed_cb()
