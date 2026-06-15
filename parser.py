from __future__ import annotations

# Some people, when confronted with a parsing problem, think
# "I know, I'll use regular expressions." Now they have two problems.
import re
from typing import Any

BlockData = dict[str, Any]


def to_blocks(markdown: str) -> list[BlockData]:
    blocks: list[BlockData] = []
    lines = markdown.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("```"):
            lang = line[3:].strip()
            code_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            blocks.append({
                "type": "code",
                "content": "\n".join(code_lines),
                "language": lang,
            })
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            blocks.append({"type": f"heading-{level}", "content": m.group(2)})
            i += 1
            continue

        m = re.match(r"^-\s+\[([ x])\]\s+(.*)$", line)
        if m:
            items: list[dict[str, Any]] = []
            while i < len(lines):
                m2 = re.match(r"^-\s+\[([ x])\]\s+(.*)$", lines[i])
                if not m2:
                    break
                items.append({
                    "content": m2.group(2),
                    "checked": m2.group(1) == "x",
                })
                i += 1
            blocks.append({"type": "todo", "items": items})
            continue

        m = re.match(r"^!!!\s*(.*)$", line)
        if m:
            blocks.append({"type": "important", "content": m.group(1)})
            i += 1
            continue

        m = re.match(r"^-\s+(.+)$", line)
        if m:
            blocks.append({"type": "bullet", "content": m.group(1)})
            i += 1
            continue

        m = re.match(r"^\d+\.\s+(.+)$", line)
        if m:
            items: list[dict[str, Any]] = []
            while i < len(lines):
                m2 = re.match(r"^\d+\.\s+(.+)$", lines[i])
                if not m2:
                    break
                items.append({"content": m2.group(1)})
                i += 1
            blocks.append({"type": "numbered", "items": items})
            continue

        if re.match(r"^-{3,}$", line):
            blocks.append({"type": "hr", "content": ""})
            i += 1
            continue

        blocks.append({"type": "paragraph", "content": line})
        i += 1

    return blocks


def from_blocks(blocks: list[BlockData]) -> str:
    lines: list[str] = []
    for block in blocks:
        t = block.get("type", "paragraph")
        content = block.get("content", "")

        if t.startswith("heading-"):
            level = int(t[-1])
            lines.append(f"{'#' * level} {content}")
        elif t == "todo":
            items = block.get("items", [])
            if not items:
                checked = "x" if block.get("checked") else " "
                lines.append(f"- [{checked}] {content}")
            else:
                for item in items:
                    checked = "x" if item.get("checked") else " "
                    lines.append(f"- [{checked}] {item.get('content', '')}")
        elif t == "important":
            lines.append(f"!!! {content}")
        elif t == "bullet":
            lines.append(f"- {content}")
        elif t == "numbered":
            numbered_items = block.get("items", [])
            if numbered_items:
                for idx, item in enumerate(numbered_items, start=1):
                    lines.append(f"{idx}. {item.get('content', '')}")
            else:
                lines.append(f"1. {content}")
        elif t == "code":
            lang = block.get("language", "")
            lines.append(f"```{lang}")
            lines.append(content)
            lines.append("```")
        elif t == "hr":
            lines.append("---")
        else:
            lines.append(content)

    return "\n".join(lines)
