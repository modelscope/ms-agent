"""Readable, dependency-light exports of the reconstructed WebUI transcript.

The append-only SessionLog remains the source of truth.  Export consumes the
same ``SessionMessage`` projection as history replay, so live UI and downloaded
files agree on user text, thoughts, tools, plans, errors and interruptions.
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

import markdown as markdown_lib
from bs4 import BeautifulSoup

from app.backends.errors import NotFound
from app.backends.ms_agent.common import find_session
from app.schemas.session import SessionFile, SessionMessage, SessionPart, SessionStep

ExportFormat = Literal["markdown", "html"]
ExportDetail = Literal["full", "compact", "user-only"]


@dataclass(frozen=True)
class ExportMetadata:
    title: str
    session_id: str
    project_name: str
    project_id: str
    model: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class SessionExport:
    content: str
    filename: str
    ascii_filename: str
    media_type: str


_INVALID_FILENAME = re.compile(r"[\x00-\x1f\x7f/\\:*?\"<>|]+")
_BACKTICKS = re.compile(r"`+")
_SAFE_DATA_IMAGE = re.compile(
    r"^data:image/(?:png|gif|jpe?g|webp|svg\+xml);base64,", re.IGNORECASE)
_STEP_LABELS = {
    "authorization": "Permission",
    "browser": "Web page",
    "file_edit": "File edit",
    "file_read": "File read",
    "file_write": "File write",
    "memory": "Memory",
    "search": "Search",
    "skill_list": "Skills",
    "skill_load": "Skill",
    "terminal": "Terminal",
    "tool_call": "Tool",
}


def _safe_filename(value: str, fallback: str) -> str:
    cleaned = _INVALID_FILENAME.sub("-", value).strip(" .-")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned[:96].rstrip(" .-") or fallback)


def _inline_code(value: str) -> str:
    runs = [len(match.group(0)) for match in _BACKTICKS.finditer(value)]
    fence = "`" * (max(runs, default=0) + 1)
    padding = " " if value.startswith("`") or value.endswith("`") else ""
    return f"{fence}{padding}{value}{padding}{fence}"


def _fenced(value: object, language: str = "text") -> str:
    text = _pretty(value)
    runs = [len(match.group(0)) for match in re.finditer(r"`{3,}", text)]
    fence = "`" * max(3, max(runs, default=2) + 1)
    return f"{fence}{language}\n{text}\n{fence}"


def _pretty(value: object) -> str:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return value
        return json.dumps(parsed, ensure_ascii=False, indent=2)
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _same_payload(left: object, right: object) -> bool:
    return _pretty(left).strip() == _pretty(right).strip()


def _duration(value: int | None) -> str:
    if value is None:
        return ""
    seconds = value / 1000
    return f"{seconds:.1f}s" if seconds < 10 else f"{seconds:.0f}s"


def _thought_duration(value: int | None) -> str:
    return f" · {value}s" if value is not None else ""


def _display_datetime(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    zone = parsed.tzname() or ""
    suffix = f" {zone}" if zone else ""
    return parsed.strftime("%Y-%m-%d · %H:%M") + suffix


def _css_token(value: object, fallback: str) -> str:
    token = re.sub(r"[^a-z0-9_-]+", "-", str(value or "").lower()).strip("-")
    return token or fallback


def _step_status(step: SessionStep) -> str:
    status = str(step.meta.get("status") or step.meta.get("state") or "done").lower()
    return "error" if status in ("error", "failed", "rejected", "denied") else status


def _step_label(step: SessionStep) -> str:
    if str(step.meta.get("source") or "").lower() == "mcp":
        return "MCP"
    return _STEP_LABELS.get(step.kind, "Tool")


def _step_title(step: SessionStep) -> str:
    meta = step.meta
    tool = str(meta.get("tool") or step.kind).strip()
    detail = str(
        meta.get("title") or meta.get("desc") or meta.get("description")
        or meta.get("path") or "").strip()
    if detail and detail != tool:
        if len(detail) > 120:
            detail = detail[:117] + "…"
        return f"{tool} · {detail}"
    return tool


def _status_mark(step: SessionStep) -> str:
    status = _step_status(step)
    if status == "error":
        return "×"
    if status in ("running", "pending"):
        return "…"
    return "✓"


def _status_icon(step: SessionStep) -> str:
    """Geometrically centered status glyph as inline SVG.

    The text "×" / "✓" glyphs are not optically centered in their line box, so
    a grid-centered container still renders them off-center. A symmetric SVG
    drawn around the (12, 12) viewBox center sits exactly in the circle.
    """
    status = _step_status(step)
    if status in ("running", "pending"):
        return ('<svg class="status-glyph" viewBox="0 0 24 24" width="9" '
                'height="9" fill="currentColor" aria-hidden="true">'
                '<circle cx="12" cy="12" r="6"/></svg>')
    path = ('M6 6L18 18M18 6L6 18' if status == "error" else 'M5 12.5L10 17.5L19 7')
    return ('<svg class="status-glyph" viewBox="0 0 24 24" width="12" '
            'height="12" fill="none" stroke="currentColor" stroke-width="3" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            f'<path d="{path}"/></svg>')


def _markdown_files(files: list[SessionFile]) -> list[str]:
    if not files:
        return []
    lines = ["", "**Attachments**"]
    for file in files:
        suffix: list[str] = []
        if file.size is not None:
            suffix.append(f"{file.size} bytes")
        if not file.exists:
            suffix.append("deleted")
        if file.delivery:
            suffix.append(file.delivery)
        note = f" — {', '.join(suffix)}" if suffix else ""
        lines.append(f"- {_inline_code(file.path)}{note}")
    return lines


def _markdown_tasks(part: SessionPart) -> list[str]:
    lines = ["", "### Plan"]
    for task in part.tasks:
        checked = "x" if task.status in ("done", "completed") else " "
        status = "" if checked == "x" else f" ({task.status})"
        lines.append(f"- [{checked}] {task.label}{status}")
    return lines


def _markdown_step(step: SessionStep, detail: ExportDetail) -> list[str]:
    title = _step_title(step)
    lines = ["", f"### {_status_mark(step)} Tool · {title}"]
    duration = step.meta.get("duration_ms")
    if isinstance(duration, (int, float)):
        lines.append(f"Duration: {_duration(int(duration))}")
    if detail == "compact":
        error = step.meta.get("error")
        if error:
            lines.extend(["", f"> {str(error)}"])
        return lines
    arguments = step.meta.get("arguments")
    if arguments not in (None, {}, ""):
        lines.extend(["", "**Arguments**", "", _fenced(arguments, "json")])
    result = step.meta.get("result")
    error = step.meta.get("error")
    if result not in (None, "") and not (error and _same_payload(result, error)):
        lines.extend(["", "**Result**", "", _fenced(result)])
    if error:
        lines.extend(["", "**Error**", "", _fenced(error)])
    return lines


def _markdown_part(part: SessionPart, detail: ExportDetail) -> list[str]:
    if part.kind == "text":
        return ["", part.text] if part.text else []
    if part.kind == "thought":
        if detail == "compact":
            return ["", f"_Thought{_thought_duration(part.duration)}_\n"]
        return ["", f"### Thought{_thought_duration(part.duration)}", "", part.text]
    if part.kind == "tasks":
        return _markdown_tasks(part)
    if part.kind == "step" and part.step is not None:
        return _markdown_step(part.step, detail)
    if part.kind == "error":
        text = part.text.replace("\n", "\n> ")
        return ["", f"> **Error:** {text}"]
    if part.kind == "interrupted":
        return ["", "> ⏹ **Interrupted**"]
    if detail == "full":
        return ["", "### Unknown record", "", _fenced(part.model_dump(exclude_none=True), "json")]
    return []


def render_markdown(
    metadata: ExportMetadata,
    messages: list[SessionMessage],
    detail: ExportDetail = "full",
) -> str:
    """Render a stable, readable Markdown transcript."""
    lines = [
        f"# {metadata.title}",
        "",
        f"> Project: {metadata.project_name} ({metadata.project_id})  ",
        f"> Session: {metadata.session_id}  ",
        f"> Model: {metadata.model or 'Unknown'}  ",
        f"> Created: {metadata.created_at}  ",
        f"> Updated: {metadata.updated_at}  ",
        f"> Messages: {len(messages)}",
    ]
    for message in messages:
        role = "User" if message.role == "user" else "Assistant"
        lines.extend(["", "---", "", f"## {role}"])
        if message.role == "user":
            if message.content:
                lines.extend(["", message.content])
            if detail != "user-only":
                lines.extend(_markdown_files(message.files))
            continue
        if detail == "user-only":
            if message.content:
                lines.extend(["", message.content])
            continue
        if message.parts:
            for part in message.parts:
                lines.extend(_markdown_part(part, detail))
        elif message.content:
            lines.extend(["", message.content])
        if message.changed_files:
            lines.extend(["", "**Changed files**"])
            lines.extend(f"- {_inline_code(path)}" for path in message.changed_files)
        duration = _duration(message.duration_ms)
        if duration:
            lines.extend(["", f"_Turn duration: {duration}_"])
    return "\n".join(lines).rstrip() + "\n"


def _safe_markdown_html(source: str) -> str:
    """Render Markdown without allowing transcript content to inject HTML/JS."""
    escaped = html.escape(source, quote=False)
    rendered = markdown_lib.markdown(
        escaped,
        extensions=["extra", "sane_lists", "nl2br"],
        output_format="html5",
    )
    soup = BeautifulSoup(rendered, "html.parser")
    for link in soup.find_all("a"):
        href = str(link.get("href") or "").strip()
        parsed = urlsplit(href)
        if href.startswith("#") or parsed.scheme.lower() in ("http", "https", "mailto"):
            link["rel"] = "noopener noreferrer"
            if parsed.scheme.lower() in ("http", "https"):
                link["target"] = "_blank"
        else:
            link.attrs.pop("href", None)
    for image in list(soup.find_all("img")):
        src = str(image.get("src") or "")
        if _SAFE_DATA_IMAGE.match(src):
            image.attrs = {
                "src": src,
                "alt": str(image.get("alt") or "Image"),
                "loading": "lazy",
            }
            continue
        label = str(image.get("alt") or "Image")
        replacement = soup.new_tag("span", attrs={"class": "image-reference"})
        replacement.string = f"Image: {label}" + (f" ({src})" if src else "")
        image.replace_with(replacement)
    return str(soup)


def _html_section_heading(symbol: str, title: str, note: str) -> str:
    return (f'<div class="section-heading"><span class="section-symbol" '
            f'aria-hidden="true">{symbol}</span><div><h3>{title}</h3>'
            f'<p>{html.escape(note)}</p></div></div>')


def _html_files(files: list[SessionFile]) -> str:
    if not files:
        return ""
    items: list[str] = []
    for file in files:
        notes: list[str] = []
        if file.size is not None:
            notes.append(f"{file.size} bytes")
        if not file.exists:
            notes.append("deleted")
        if file.delivery:
            notes.append(file.delivery)
        suffix = (f'<span class="file-note">{html.escape(" · ".join(notes))}</span>'
                  if notes else "")
        items.append(
            f'<li><span class="file-mark" aria-hidden="true">↗</span>'
            f'<span class="file-copy"><code>{html.escape(file.path)}</code>{suffix}</span></li>')
    heading = _html_section_heading("＋", "Attachments", f"{len(files)} files")
    return (f'<section class="resource-card attachments" data-kind="file">{heading}'
            f'<ul class="file-list">{"".join(items)}</ul></section>')


def _html_tasks(part: SessionPart) -> str:
    rows = []
    for task in part.tasks:
        done = task.status in ("done", "completed")
        mark = "✓" if done else "○"
        status = _css_token(task.status, "pending")
        rows.append(
            f'<li class="task {status}"><span aria-hidden="true">{mark}</span>'
            f"<div>{html.escape(task.label)}</div></li>")
    heading = _html_section_heading("✓", "Plan", f"{len(part.tasks)} tasks")
    return (f'<section class="resource-card tasks" data-kind="task">{heading}'
            f'<ul class="task-list">{"".join(rows)}</ul></section>')


def _html_step_section(label: str, value: object, language: str = "") -> str:
    language_attr = f' data-language="{language}"' if language else ""
    return (f'<section class="step-section"><h4>{label}</h4>'
            f'<pre{language_attr}><code>{html.escape(_pretty(value))}</code></pre></section>')


def _html_step(step: SessionStep, detail: ExportDetail) -> str:
    title = html.escape(_step_title(step))
    status = _css_token(_step_status(step), "done")
    step_kind = _css_token(step.kind, "tool")
    source = _css_token(step.meta.get("source"), "native")
    kind_label = html.escape(_step_label(step))
    duration = step.meta.get("duration_ms")
    duration_text = (_duration(int(duration))
                     if isinstance(duration, (int, float)) else "")
    badge = f'<span class="duration">{duration_text}</span>' if duration_text else ""
    error = step.meta.get("error")
    error_html = (f'<div class="step-error">{html.escape(str(error))}</div>'
                  if error else "")
    summary = (f'<span class="step-summary-main"><span class="status-mark" '
               f'aria-hidden="true">{_status_icon(step)}</span>'
               f'<span class="step-kind">{kind_label}</span>'
               f'<span class="step-title">{title}</span></span>{badge}')
    attrs = (f'data-kind="tool" data-step-kind="{step_kind}" '
             f'data-source="{source}"')
    if detail == "compact":
        return (f'<div class="step compact {status}" {attrs}>'
                f'<div class="step-compact-header">{summary}</div>{error_html}</div>')
    sections: list[str] = []
    arguments = step.meta.get("arguments")
    if arguments not in (None, {}, ""):
        sections.append(_html_step_section("Input", arguments, "json"))
    result = step.meta.get("result")
    if result not in (None, "") and not (error and _same_payload(result, error)):
        sections.append(_html_step_section("Output", result))
    if error:
        sections.append(_html_step_section("Error", error))
    if not sections:
        sections.append('<p class="empty-detail">No additional details recorded.</p>')
    return (f'<details class="step {status}" {attrs}><summary>{summary}</summary>'
            f'<div class="step-body">{"".join(sections)}</div></details>')


def _html_part(part: SessionPart, detail: ExportDetail) -> str:
    if part.kind == "text":
        return (f'<section class="markdown answer" data-kind="answer">'
                f"{_safe_markdown_html(part.text)}</section>") if part.text else ""
    if part.kind == "thought":
        duration = _thought_duration(part.duration)
        heading = (f'<span class="thought-label"><span class="thought-mark" '
                   f'aria-hidden="true">✦</span>Thinking</span>'
                   f'<span class="duration">{html.escape(duration.removeprefix(" · "))}</span>')
        if detail == "compact":
            return (f'<div class="thought compact" data-kind="thought">{heading}</div>')
        return (f'<details class="thought" data-kind="thought"><summary>{heading}</summary>'
                f'<div class="markdown thought-body">{_safe_markdown_html(part.text)}</div>'
                f'</details>')
    if part.kind == "tasks":
        return _html_tasks(part)
    if part.kind == "step" and part.step is not None:
        return _html_step(part.step, detail)
    if part.kind == "error":
        return (f'<div class="error" data-kind="error"><span class="error-mark" '
                f'aria-hidden="true">!</span><div><strong>Turn error</strong>'
                f'<p>{html.escape(part.text)}</p></div></div>')
    if part.kind == "interrupted":
        return ('<div class="interrupted" data-kind="interrupted">'
                '<span aria-hidden="true">■</span> Turn interrupted</div>')
    if detail == "full":
        payload = html.escape(json.dumps(part.model_dump(exclude_none=True),
                                         ensure_ascii=False, indent=2))
        return (f'<details class="unknown"><summary>Unknown record</summary>'
                f"<pre><code>{payload}</code></pre></details>")
    return ""


def _html_changed_files(paths: list[str]) -> str:
    heading = _html_section_heading("↗", "Changed files", f"{len(paths)} files")
    items = "".join(
        f'<li><span class="file-mark" aria-hidden="true">↳</span>'
        f'<code>{html.escape(path)}</code></li>' for path in paths)
    return (f'<section class="resource-card changed" data-kind="file">{heading}'
            f'<ul class="file-list">{items}</ul></section>')


def _html_message(message: SessionMessage, index: int,
                  detail: ExportDetail) -> str:
    role = "user" if message.role == "user" else "assistant"
    label = "User" if role == "user" else "Assistant"
    body: list[str] = []
    if role == "user":
        if message.content:
            body.append(f'<div class="markdown">{_safe_markdown_html(message.content)}</div>')
        if detail != "user-only":
            body.append(_html_files(message.files))
    elif detail == "user-only":
        if message.content:
            body.append(f'<div class="markdown answer">{_safe_markdown_html(message.content)}</div>')
    elif message.parts:
        body.extend(_html_part(part, detail) for part in message.parts)
    elif message.content:
        body.append(f'<div class="markdown answer">{_safe_markdown_html(message.content)}</div>')
    if role == "assistant" and detail != "user-only":
        if message.changed_files:
            body.append(_html_changed_files(message.changed_files))
        duration = _duration(message.duration_ms)
        if duration:
            body.append(f'<div class="turn-duration">Completed in {duration}</div>')
    index_label = f"{index:02d}"
    return (f'<article class="message {role}" data-role="{role}" id="message-{index}">'
            f'<header class="message-header"><div class="message-identity">'
            f'<span class="avatar">{"U" if role == "user" else "A"}</span>'
            f'<strong>{label}</strong></div><a class="message-anchor" href="#message-{index}" '
            f'aria-label="Link to message {index}">#{index_label}</a></header>'
            f'<div class="message-body">{"".join(body)}</div></article>')


_STYLE = """
:root {
  color-scheme: light dark;
  --page: #f4f5f9;
  --surface: #ffffff;
  --surface-raised: #ffffff;
  --surface-soft: #f8f8fb;
  --surface-strong: #f0f1f5;
  --text: #171923;
  --text-soft: #3f4654;
  --muted: #697386;
  --subtle: #98a2b3;
  --border: #e2e5eb;
  --border-strong: #d3d8e1;
  --brand: #6157e8;
  --brand-2: #8b5cf6;
  --brand-soft: #eeecff;
  --user: #f1f0ff;
  --success: #16794b;
  --success-soft: #ecfdf3;
  --warning: #a15c07;
  --warning-soft: #fff8e7;
  --danger: #b42318;
  --danger-soft: #fff1f0;
  --code: #171923;
  --code-text: #eef1f6;
  --shadow-sm: 0 1px 2px rgba(16, 24, 40, .04);
  --shadow-md: 0 12px 36px rgba(34, 31, 68, .08);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  min-width: 320px;
  background:
    radial-gradient(circle at 12% 0%, rgba(122, 113, 245, .09), transparent 28rem),
    radial-gradient(circle at 88% 16%, rgba(56, 189, 248, .07), transparent 26rem),
    var(--page);
  color: var(--text);
  font: 15px/1.68 Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  text-rendering: optimizeLegibility;
  -webkit-font-smoothing: antialiased;
}
a { color: var(--brand); text-decoration-thickness: 1px; text-underline-offset: 3px; }
a:hover { color: var(--brand-2); }
button, input { font: inherit; }
.page { width: min(100%, 1080px); margin: 0 auto; padding: 40px 28px 104px; }
.hero {
  position: relative;
  overflow: hidden;
  margin-bottom: 20px;
  padding: 34px 36px 28px;
  border: 1px solid rgba(255, 255, 255, .14);
  border-radius: 24px;
  background: linear-gradient(135deg, #17162d 0%, #28244f 62%, #36316b 100%);
  color: #fff;
  box-shadow: 0 22px 58px rgba(31, 28, 67, .2);
}
.hero::after {
  position: absolute;
  top: -90px;
  right: -70px;
  width: 300px;
  height: 300px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(151, 139, 255, .35), transparent 68%);
  content: "";
  pointer-events: none;
}
.hero-kicker { display: flex; flex-wrap: wrap; align-items: center; gap: 9px; margin-bottom: 22px; color: #d8d5ff; font-size: 12px; font-weight: 650; letter-spacing: .04em; text-transform: uppercase; }
.brand-mark { display: inline-grid; width: 25px; height: 25px; place-items: center; border: 1px solid rgba(255,255,255,.28); border-radius: 8px; background: rgba(255,255,255,.1); color: #fff; font-size: 10px; letter-spacing: 0; }
.kicker-separator { width: 3px; height: 3px; border-radius: 50%; background: rgba(255,255,255,.45); }
.mode-badge { padding: 3px 9px; border: 1px solid rgba(255,255,255,.18); border-radius: 999px; background: rgba(255,255,255,.09); color: #f1efff; font-size: 10px; letter-spacing: .06em; }
.hero-title { position: relative; z-index: 1; max-width: 780px; }
.hero h1 { margin: 0; font-size: clamp(30px, 5vw, 46px); line-height: 1.14; letter-spacing: -.035em; overflow-wrap: anywhere; }
.hero-subtitle { margin: 12px 0 0; color: rgba(255,255,255,.7); font-size: 14px; }
.hero-stats { position: relative; z-index: 1; display: grid; grid-template-columns: .75fr .75fr 1.5fr; gap: 10px; margin-top: 28px; }
.hero-stat { min-width: 0; padding: 13px 15px; border: 1px solid rgba(255,255,255,.12); border-radius: 13px; background: rgba(255,255,255,.07); backdrop-filter: blur(10px); }
.hero-stat span { display: block; margin-bottom: 4px; color: rgba(255,255,255,.56); font-size: 10px; font-weight: 650; letter-spacing: .07em; text-transform: uppercase; }
.hero-stat strong { display: block; color: #fff; font-size: 14px; font-weight: 620; line-height: 1.4; overflow-wrap: anywhere; }
.archive-details { position: relative; z-index: 1; margin-top: 17px; color: rgba(255,255,255,.66); font-size: 12px; }
.archive-details summary { width: max-content; cursor: pointer; color: rgba(255,255,255,.72); }
.archive-details dl { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 5px 14px; margin: 12px 0 0; padding: 13px 15px; border-radius: 12px; background: rgba(0,0,0,.16); }
.archive-details dt { color: rgba(255,255,255,.48); }
.archive-details dd { min-width: 0; margin: 0; overflow-wrap: anywhere; }
.toolbar {
  position: sticky;
  top: 12px;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 16px;
  margin: 0 0 24px;
  padding: 12px 14px;
  border: 1px solid rgba(218, 221, 230, .9);
  border-radius: 16px;
  background: rgba(255, 255, 255, .86);
  box-shadow: var(--shadow-md);
  backdrop-filter: blur(18px) saturate(160%);
}
.toolbar-copy { flex: none; padding: 0 5px; }
.toolbar-copy strong { display: block; font-size: 13px; line-height: 1.25; }
.toolbar-copy span { display: block; margin-top: 2px; color: var(--muted); font-size: 10px; }
.filter-options { display: flex; min-width: 0; flex: 1; flex-wrap: wrap; gap: 6px; }
.filter-pill { display: inline-flex; align-items: center; gap: 6px; padding: 6px 9px; border: 1px solid var(--border); border-radius: 999px; background: var(--surface-soft); color: var(--text-soft); cursor: pointer; font-size: 11px; transition: border-color .15s ease, background .15s ease, color .15s ease; }
.filter-pill:hover { border-color: #b9b4f5; background: var(--brand-soft); color: var(--brand); }
.filter-pill input { width: 13px; height: 13px; margin: 0; accent-color: var(--brand); }
.toolbar-actions { display: flex; flex: none; gap: 6px; }
.toolbar-button { padding: 6px 9px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); color: var(--muted); cursor: pointer; font-size: 11px; }
.toolbar-button:hover { border-color: #b9b4f5; color: var(--brand); }
.transcript { display: flow-root; }
.message { position: relative; width: 100%; margin: 0 0 22px; padding: 22px 24px; border: 1px solid var(--border); border-radius: 19px; background: var(--surface); box-shadow: var(--shadow-sm); scroll-margin-top: 98px; }
.message::before { position: absolute; top: 0; bottom: 0; left: -17px; width: 1px; background: linear-gradient(var(--border), transparent); content: ""; }
.message.user { width: min(84%, 790px); margin-left: auto; border-color: #dedbff; background: linear-gradient(145deg, #f6f5ff, var(--user)); }
.message.user::before { display: none; }
.message-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.message-identity { display: flex; align-items: center; gap: 9px; }
.message-identity strong { font-size: 13px; letter-spacing: -.01em; }
.message-anchor { color: var(--subtle); font: 500 10px/1 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; text-decoration: none; opacity: 0; transition: opacity .15s ease; }
.message:hover .message-anchor, .message-anchor:focus { opacity: 1; }
.avatar { display: grid; width: 28px; height: 28px; place-items: center; border-radius: 9px; background: linear-gradient(145deg, var(--brand), var(--brand-2)); color: #fff; font-size: 11px; font-weight: 750; box-shadow: 0 5px 12px rgba(97, 87, 232, .2); }
.user .avatar { background: #344054; box-shadow: none; }
.message-body > :first-child { margin-top: 0; }
.message-body > :last-child { margin-bottom: 0; }
.markdown { min-width: 0; color: var(--text-soft); overflow-wrap: anywhere; }
.markdown p { margin: 0 0 12px; }
.markdown p:last-child { margin-bottom: 0; }
.markdown h1, .markdown h2, .markdown h3, .markdown h4 { margin: 24px 0 10px; color: var(--text); line-height: 1.3; letter-spacing: -.02em; }
.markdown h1 { font-size: 25px; }
.markdown h2 { padding-bottom: 7px; border-bottom: 1px solid var(--border); font-size: 20px; }
.markdown h3 { font-size: 17px; }
.markdown h4 { font-size: 15px; }
.markdown ul, .markdown ol { margin: 10px 0 14px; padding-left: 23px; }
.markdown li { margin: 4px 0; }
.markdown hr { height: 1px; margin: 24px 0; border: 0; background: var(--border); }
.markdown blockquote { margin: 16px 0; padding: 9px 14px; border-left: 3px solid var(--brand); border-radius: 0 8px 8px 0; background: var(--brand-soft); color: var(--muted); }
.markdown img { display: block; max-width: 100%; height: auto; margin: 14px auto; border-radius: 12px; box-shadow: var(--shadow-md); }
.image-reference { color: var(--muted); font-style: italic; }
.markdown code, .file-list code { font-family: ui-monospace, "SFMono-Regular", Consolas, monospace; }
.markdown :not(pre) > code, .file-list code { padding: 2px 5px; border: 1px solid var(--border); border-radius: 5px; background: var(--surface-strong); color: var(--text); font-size: .88em; overflow-wrap: anywhere; }
.markdown pre, .step pre, .unknown pre { max-height: 34rem; overflow: auto; margin: 10px 0 0; padding: 15px 16px; border: 1px solid rgba(255,255,255,.08); border-radius: 11px; background: var(--code); color: var(--code-text); font: 12px/1.62 ui-monospace, "SFMono-Regular", Consolas, monospace; white-space: pre-wrap; word-break: break-word; overscroll-behavior: contain; }
.markdown table { display: block; width: 100%; overflow-x: auto; margin: 14px 0; border: 1px solid var(--border); border-radius: 10px; border-collapse: separate; border-spacing: 0; }
.markdown th, .markdown td { min-width: 110px; padding: 9px 11px; border-right: 1px solid var(--border); border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }
.markdown th { background: var(--surface-strong); color: var(--text); font-size: 12px; }
.markdown tr:last-child td { border-bottom: 0; }
.markdown th:last-child, .markdown td:last-child { border-right: 0; }
.answer { margin-top: 16px; padding-top: 18px; border-top: 1px solid var(--border); color: var(--text); }
details > summary { cursor: pointer; list-style-position: outside; }
details > summary:focus-visible, button:focus-visible, input:focus-visible, a:focus-visible { outline: 2px solid var(--brand); outline-offset: 3px; }
.thought, .step, .resource-card, .error, .interrupted, .unknown { margin: 10px 0; border: 1px solid var(--border); border-radius: 12px; background: var(--surface-soft); }
.thought { border-color: #e3e0ff; background: #f8f7ff; color: #685f94; }
.thought summary, .thought.compact { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 44px; padding: 11px 14px; font-size: 12px; font-weight: 620; }
.thought-label { display: inline-flex; align-items: center; gap: 8px; }
.thought-mark { display: inline-grid; width: 21px; height: 21px; place-items: center; border-radius: 7px; background: #e7e4ff; color: var(--brand); font-size: 10px; }
.thought-body { margin: 0; padding: 4px 14px 15px; border-top: 1px solid #e5e2ff; color: var(--muted); font-size: 13px; }
.duration, .turn-duration { color: var(--muted); font-size: 10px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.step { overflow: hidden; }
.step summary, .step-compact-header { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 12px; min-height: 44px; padding: 11px 14px; }
.step summary { font-size: 12px; font-weight: 570; }
.step summary:hover { background: rgba(97, 87, 232, .035); }
.step-summary-main { display: flex; min-width: 0; flex: 1; align-items: center; gap: 8px; }
.status-mark { display: inline-grid; width: 20px; height: 20px; flex: none; place-items: center; border-radius: 50%; background: var(--success-soft); color: var(--success); font-weight: 760; }
.status-mark .status-glyph { display: block; }
.step-kind { flex: none; padding: 2px 7px; border: 1px solid var(--border); border-radius: 999px; background: var(--surface); color: var(--muted); font-size: 9px; font-weight: 700; letter-spacing: .045em; text-transform: uppercase; }
.step-title { min-width: 0; color: var(--text-soft); overflow-wrap: anywhere; }
.step-compact-header .duration, .step summary .duration { flex: none; }
.step[data-source="mcp"] .step-kind { border-color: #a5e8f4; background: #ecfdff; color: #087f8c; }
.step[data-step-kind="terminal"] .step-kind { border-color: #b7e4cb; background: #effcf5; color: #16794b; }
.step[data-step-kind^="file"] .step-kind { border-color: #b9d9ff; background: #eff8ff; color: #175cd3; }
.step[data-step-kind="memory"] .step-kind, .step[data-step-kind^="skill"] .step-kind { border-color: #d9c6ff; background: #f6f0ff; color: #7a3fc2; }
.step[data-step-kind="search"] .step-kind, .step[data-step-kind="browser"] .step-kind { border-color: #f6d58a; background: var(--warning-soft); color: var(--warning); }
.step-body { padding: 0 14px 14px; border-top: 1px solid var(--border); }
.step-section { padding-top: 12px; }
.step-section h4 { margin: 0; color: var(--muted); font-size: 9px; font-weight: 720; letter-spacing: .08em; text-transform: uppercase; }
.empty-detail { margin: 13px 0 0; color: var(--subtle); font-size: 12px; }
.step.error { border-color: #f4b5b0; background: var(--danger-soft); }
.step.error .status-mark { background: #fee4e2; color: var(--danger); }
.step.error .step-kind, .step.error .step-title { color: var(--danger); }
.step-error { margin: 0 14px 14px; padding: 10px 11px; border-radius: 8px; background: rgba(180,35,24,.07); color: var(--danger); font-size: 12px; line-height: 1.55; overflow-wrap: anywhere; white-space: pre-wrap; }
.resource-card { padding: 14px; }
.section-heading { display: flex; align-items: center; gap: 10px; }
.section-symbol { display: inline-grid; width: 27px; height: 27px; flex: none; place-items: center; border-radius: 8px; background: var(--brand-soft); color: var(--brand); font-size: 12px; font-weight: 720; }
.section-heading h3 { margin: 0; color: var(--text); font-size: 12px; }
.section-heading p { margin: 1px 0 0; color: var(--muted); font-size: 10px; }
.task-list, .file-list { margin: 12px 0 0; padding: 0; list-style: none; }
.task { display: flex; align-items: flex-start; gap: 9px; padding: 7px 0; border-top: 1px solid var(--border); color: var(--text-soft); font-size: 12px; }
.task > span { width: 18px; flex: none; color: var(--brand); font-weight: 720; text-align: center; }
.task.done > div, .task.completed > div { color: var(--muted); text-decoration: line-through; }
.file-list li { display: flex; min-width: 0; align-items: flex-start; gap: 8px; padding: 7px 0; border-top: 1px solid var(--border); font-size: 12px; }
.file-mark { flex: none; color: var(--brand); }
.file-copy { display: flex; min-width: 0; flex-wrap: wrap; align-items: baseline; gap: 5px; }
.file-note { color: var(--muted); font-size: 10px; }
.error[data-kind="error"] { display: flex; align-items: flex-start; gap: 10px; padding: 13px 14px; border-color: #f4b5b0; background: var(--danger-soft); color: var(--danger); }
.error-mark { display: inline-grid; width: 23px; height: 23px; flex: none; place-items: center; border-radius: 50%; background: #fee4e2; font-weight: 800; }
.error strong { font-size: 12px; }
.error p { margin: 3px 0 0; font-size: 12px; white-space: pre-wrap; overflow-wrap: anywhere; }
.interrupted { padding: 11px 14px; color: var(--muted); font-size: 12px; text-align: center; }
.interrupted span { margin-right: 7px; color: var(--danger); font-size: 8px; }
.unknown { padding: 12px 14px; }
.turn-duration { margin-top: 12px; text-align: right; }
.hide-user .message.user, .hide-assistant .message.assistant, .hide-thought [data-kind="thought"], .hide-tool [data-kind="tool"], .hide-task [data-kind="task"], .hide-error [data-kind="error"], .hide-error .step.error, .hide-file [data-kind="file"] { display: none !important; }
#back-top { position: fixed; right: 24px; bottom: 24px; display: grid; width: 42px; height: 42px; place-items: center; border: 0; border-radius: 13px; background: var(--text); color: var(--surface); cursor: pointer; box-shadow: var(--shadow-md); opacity: 0; pointer-events: none; transform: translateY(8px); transition: opacity .18s ease, transform .18s ease; }
#back-top[data-visible="true"] { opacity: 1; pointer-events: auto; transform: translateY(0); }
@media (prefers-color-scheme: dark) {
  :root { --page:#11121a; --surface:#191b25; --surface-raised:#1e202b; --surface-soft:#20222d; --surface-strong:#292c39; --text:#f4f4f7; --text-soft:#d6d8e1; --muted:#9ca3b5; --subtle:#72798c; --border:#303342; --border-strong:#3b3f50; --brand:#9b8cff; --brand-2:#b38cff; --brand-soft:#292544; --user:#24233a; --success:#68d391; --success-soft:#1d3529; --warning:#f4bf63; --warning-soft:#332a18; --danger:#ff8e86; --danger-soft:#3b2223; --code:#0c0d12; --code-text:#e8eaf0; --shadow-sm:0 1px 2px rgba(0,0,0,.2); --shadow-md:0 14px 42px rgba(0,0,0,.28); }
  body { background: radial-gradient(circle at 12% 0%, rgba(105,91,220,.12), transparent 28rem), radial-gradient(circle at 88% 16%, rgba(14,116,144,.1), transparent 26rem), var(--page); }
  .toolbar { border-color: rgba(62,65,82,.9); background: rgba(25,27,37,.88); }
  .message.user { border-color:#3c3862; background:linear-gradient(145deg,#25243c,var(--user)); }
  .thought { border-color:#393553; background:#211f33; color:#b7b0df; }
  .thought-mark { background:#302b50; }
  .thought-body { border-color:#393553; }
  .step[data-source="mcp"] .step-kind, .step[data-step-kind="terminal"] .step-kind, .step[data-step-kind^="file"] .step-kind, .step[data-step-kind="memory"] .step-kind, .step[data-step-kind^="skill"] .step-kind, .step[data-step-kind="search"] .step-kind, .step[data-step-kind="browser"] .step-kind { background:var(--surface-strong); }
}
@media (max-width: 720px) {
  .page { padding: 14px 12px 76px; }
  .hero { padding: 26px 22px 22px; border-radius: 19px; }
  .hero-stats { grid-template-columns: 1fr 1fr; }
  .hero-stat:last-child { grid-column: 1 / -1; }
  .archive-details dl { grid-template-columns: 1fr; gap: 2px; }
  .archive-details dd { margin-bottom: 7px; }
  .toolbar { top: 6px; align-items: flex-start; flex-direction: column; gap: 10px; border-radius: 13px; }
  .filter-options { width: 100%; }
  .toolbar-actions { width: 100%; }
  .toolbar-button { flex: 1; }
  .message, .message.user { width: 100%; margin-left: 0; padding: 17px 16px; border-radius: 15px; }
  .message::before { display: none; }
  .message-anchor { opacity: 1; }
  .step summary, .step-compact-header { align-items: flex-start; }
  .step-summary-main { flex-wrap: wrap; }
  .step-title { flex-basis: calc(100% - 38px); }
  .markdown table { font-size: 12px; }
  #back-top { right: 14px; bottom: 14px; }
}
@media (max-width: 420px) {
  .hero-stats { grid-template-columns: 1fr; }
  .hero-stat:last-child { grid-column: auto; }
  .filter-pill { padding: 5px 7px; }
  .step-kind { order: 2; }
  .step-title { order: 3; flex-basis: 100%; }
}
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  *, *::before, *::after { transition-duration: .01ms !important; }
}
@media print {
  :root { color-scheme: light; --page:#fff; --surface:#fff; --surface-soft:#f8f8fa; --surface-strong:#f0f1f5; --text:#111827; --text-soft:#374151; --muted:#667085; --border:#d9dce3; }
  @page { margin: 14mm; }
  body { background: #fff; print-color-adjust: exact; -webkit-print-color-adjust: exact; }
  .page { width: 100%; max-width: none; padding: 0; }
  .hero { padding: 22px 24px; border-radius: 14px; box-shadow: none; }
  .toolbar, #back-top { display: none !important; }
  .message { break-inside: avoid; box-shadow: none; }
  .message.user { width: 88%; }
  details > * { display: block !important; }
  .step pre, .markdown pre { max-height: none; overflow: visible; }
  .message-anchor { display: none; }
}
"""

_SCRIPT = """
(function () {
  var root = document.body;
  var backTop = document.getElementById('back-top');
  document.querySelectorAll('[data-filter]').forEach(function (input) {
    input.addEventListener('change', function () {
      root.classList.toggle('hide-' + input.dataset.filter, !input.checked);
    });
  });
  document.querySelectorAll('[data-details]').forEach(function (button) {
    button.addEventListener('click', function () {
      var open = button.dataset.details === 'open';
      document.querySelectorAll('.transcript details').forEach(function (item) {
        item.open = open;
      });
    });
  });
  function syncBackTop() {
    backTop.dataset.visible = window.scrollY > 520 ? 'true' : 'false';
  }
  window.addEventListener('scroll', syncBackTop, { passive: true });
  syncBackTop();
  backTop.addEventListener('click', function () {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });
})();
"""


def _document_language(metadata: ExportMetadata,
                       messages: list[SessionMessage]) -> str:
    sample = metadata.title + " " + " ".join(
        message.content[:300] for message in messages[:4])
    return "zh-CN" if re.search(r"[\u3400-\u9fff]", sample) else "en"


def render_html(
    metadata: ExportMetadata,
    messages: list[SessionMessage],
    detail: ExportDetail = "full",
) -> str:
    """Render an offline, self-contained and transcript-safe HTML document."""
    message_html = "".join(
        _html_message(message, index, detail)
        for index, message in enumerate(messages, start=1))
    actions = "" if detail != "full" else """
<div class="toolbar-actions" aria-label="Detail controls">
<button class="toolbar-button" type="button" data-details="open">Expand all</button>
<button class="toolbar-button" type="button" data-details="closed">Collapse all</button>
</div>"""
    filters = "" if detail == "user-only" else f"""
<nav class="toolbar" aria-label="Transcript controls">
<div class="toolbar-copy"><strong>Transcript</strong><span>Choose visible details</span></div>
<div class="filter-options">
<label class="filter-pill"><input type="checkbox" data-filter="user" checked> User</label>
<label class="filter-pill"><input type="checkbox" data-filter="assistant" checked> Assistant</label>
<label class="filter-pill"><input type="checkbox" data-filter="thought" checked> Thinking</label>
<label class="filter-pill"><input type="checkbox" data-filter="tool" checked> Tools</label>
<label class="filter-pill"><input type="checkbox" data-filter="task" checked> Plans</label>
<label class="filter-pill"><input type="checkbox" data-filter="file" checked> Files</label>
<label class="filter-pill"><input type="checkbox" data-filter="error" checked> Errors</label>
</div>{actions}
</nav>"""
    title = html.escape(metadata.title)
    project_name = html.escape(metadata.project_name)
    model = html.escape(metadata.model or "Unknown")
    mode = {
        "full": "Full transcript",
        "compact": "Compact transcript",
        "user-only": "Conversation only",
    }[detail]
    turns = sum(message.role == "user" for message in messages)
    created = _display_datetime(metadata.created_at)
    updated = _display_datetime(metadata.updated_at)
    stats = (
        f'<div class="hero-stat"><span>Messages</span><strong>{len(messages)}</strong></div>'
        f'<div class="hero-stat"><span>Turns</span><strong>{turns}</strong></div>'
        f'<div class="hero-stat"><span>Model</span><strong>{model}</strong></div>')
    archive_details = (
        '<details class="archive-details"><summary>Archive details</summary><dl>'
        f'<dt>Session ID</dt><dd>{html.escape(metadata.session_id)}</dd>'
        f'<dt>Project ID</dt><dd>{html.escape(metadata.project_id)}</dd>'
        f'<dt>Created</dt><dd><time datetime="{html.escape(metadata.created_at)}">'
        f'{html.escape(created)}</time></dd>'
        f'<dt>Updated</dt><dd><time datetime="{html.escape(metadata.updated_at)}">'
        f'{html.escape(updated)}</time></dd></dl></details>')
    language = _document_language(metadata, messages)
    return f"""<!doctype html>
<html lang="{language}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline';">
<title>{title}</title>
<style>{_STYLE}</style>
</head>
<body>
<main class="page">
<header class="hero">
<div class="hero-kicker"><span class="brand-mark">MS</span><span>MS Agent</span>
<span class="kicker-separator"></span><span>Conversation export</span>
<span class="mode-badge">{mode}</span></div>
<div class="hero-title"><h1>{title}</h1>
<p class="hero-subtitle">{project_name} · Archived conversation</p></div>
<div class="hero-stats">{stats}</div>
{archive_details}
</header>
{filters}
<section class="transcript">{message_html}</section>
</main>
<button id="back-top" type="button" aria-label="Back to top">↑</button>
<script>{_SCRIPT}</script>
</body>
</html>
"""


def build_session_export(
    session_id: str,
    export_format: ExportFormat,
    detail: ExportDetail = "full",
) -> SessionExport:
    """Snapshot one session's current replay model and render it for download."""
    found = find_session(session_id)
    if not found:
        raise NotFound("Conversation not found.")
    project, session, _manager = found
    from app.backends.ms_agent.sessions import list_messages

    messages = list_messages(session_id)
    metadata = ExportMetadata(
        title=session.name or "Conversation",
        session_id=session.id,
        project_name=project.name,
        project_id=project.id,
        model="/".join(
            part for part in (session.model_provider, session.model) if part),
        created_at=session.created_at,
        updated_at=session.updated_at,
    )
    safe_title = _safe_filename(metadata.title, "conversation")
    if export_format == "markdown":
        extension = "md"
        content = render_markdown(metadata, messages, detail)
        media_type = "text/markdown"
    else:
        extension = "html"
        content = render_html(metadata, messages, detail)
        media_type = "text/html"
    return SessionExport(
        content=content,
        filename=f"{safe_title}-{session.id[:8]}.{extension}",
        ascii_filename=f"session-{session.id[:8]}.{extension}",
        media_type=media_type,
    )
