# Static Chat Generator — Regeneration Spec

This document describes the tool fully enough that Claude can **rebuild `index.html` from scratch**.
To regenerate: *"Build a single self-contained `index.html` from this spec."*

## Purpose
A static, fake-but-faithful chat UI for an LLM product. A PM/UX author writes prompt → expected-response
**cases**; the tool **plays them back** (typed/streamed) for screen-recorded demos, and **exports** them as a
JSON spec for developers. It is NOT connected to a real model — every response is pre-authored.

## Non-negotiable constraints
- **One self-contained HTML file.** All CSS + JS inline. Runs by double-clicking; works offline for recording.
- Only external dependency: **SheetJS** from cdnjs (to parse the `.xlsx`) and Google Fonts (graceful fallback).
- **No browser storage APIs** beyond in-memory state.
- Engine, skin (theme), and data (cases) must stay clearly separated so the look can change without touching logic.

## Layout
Two columns. Left = **editor** (380px); right = **stage** (chat preview + toolbar). A **Record mode** collapses
the editor to 0 for full-screen capture.

- **Editor** has two tabs: **Cases** and **Branding**.
  - A *case* = `{ prompt, type, content, notes }`. `type ∈ {markdown, table, buttons, a2ui}`.
  - Per case: user-prompt textarea, a type pill-selector, a response textarea, and a notes/expected-behavior textarea.
  - Add / delete / reorder cases.
  - Branding tab edits the skin tokens (see below).
- **Stage**: a framed "device" mimicking a chat product — header (avatar + product/assistant name) and a scrolling
  message body. Toolbar: Play/Stop, Reset, Type/Stream/Gap speed sliders, Events toggle, Record mode, Import .xlsx,
  Spec JSON export, JSON import. A footnote shows the version badge.

## Skin / theme tokens (the ONLY thing that changes to reskin)
`DEFAULT_BRAND = { productName, assistantName, userName, assistantAvatar, userAvatar, primary, bg, surface,
ink, userBubble, font }`. Applied to CSS variables `--p-*` on the chat preview. Avatars accept an emoji or an
image URL. The engine reads only these variables for styling the preview — never hard-code colors elsewhere.

## Version stamps
`VERSION = { tool, uiSkin, a2uiCatalog }`, shown in the footnote and written into every export so a saved
case stays interpretable after the live UI changes. `uiSkin` is renamed when reskinned (e.g. `"acme-v2.3"`).

## Playback engine
On **Play**, iterate cases in order. For each: append a **user** bubble and type the prompt in character by
character (caret blink); pause; show an assistant **typing indicator**; then stream the assistant response by type:
- **markdown** — reveal source progressively, re-rendering markdown each tick; caret while streaming.
- **table** — brief pause, then render the pipe table.
- **buttons** — render clickable chips; click logs a `quick_reply` event.
- **a2ui** — apply envelopes one at a time (mimics A2UI progressive rendering), re-rendering the surface each step.
Speed sliders (1–10) map inversely to per-step delay. Reset/Stop aborts cleanly.

## Markdown renderer (compact, safe)
HTML-escape first. Support: fenced code blocks, `#`/`##`/`###` headings, `**bold**`, `*italics*`, `` `code` ``,
`[text](url)`, `-`/`*` and `1.` lists, `>` blockquotes, `---` rules, and `| pipe | tables |` (header + `---` separator).

## A2UI renderer (v0.9 subset)
Parse envelopes (JSON array or JSONL). Build a surface from `createSurface` (theme), `updateComponents`
(flat **adjacency list**, one component with `id:"root"`), `updateDataModel` (JSON-Pointer upsert into a data model).
Render the tree from `root`, skipping unknown/missing refs (progressive rendering).
- Data binding: `{path}` resolves via JSON Pointer (absolute `/x`, or relative to template scope). `formatString`
  interpolates `${/path}` (function-call interpolation may be stubbed).
- Components: Text (markdown + `variant`), Image, Icon (emoji map), Row (`justify`/`align`), Column, List, Card,
  Divider, Button (`action.event` → log to Events console with resolved context + data model; `action.functionCall`
  openUrl → log), TextField/CheckBox/ChoicePicker/Slider (two-way bind into the data model), Tabs, Modal.
- `children` may be an array of ids OR a template `{path, componentId}` that iterates a data-model array with a child scope.
- Theme `primaryColor` overrides `--p-primary` for the surface; `agentDisplayName`/`iconUrl` render an attribution bar.
Reference: https://a2ui.org/specification/v0.9-a2ui/

## Events console
Collapsible panel logging UI actions (`timestamp · action name · payload`) from buttons/inputs — the demo of what
events devs must handle. Auto-opens on first event.

## Import / Export
- **Import .xlsx** (SheetJS): a **Cases** sheet (columns: User Prompt, Response Type, Response, Expected Behavior;
  tolerant header matching) → cases; a **Theme** sheet (key/value) → brand tokens.
- **Import JSON** / **Export JSON**: round-trip. Export shape:
  `{ meta:{tool,toolVersion,uiSkin,a2uiCatalog,exported}, brand, cases:[{index,prompt,responseType,response,expectedBehavior}] }`.

## Aesthetic
Tool chrome: refined dark "studio" UI (distinctive display font for the wordmark). Chat preview: deliberately
clean/neutral so it reads as a real LLM product and is trivially reskinned to match ours. Do not over-style the preview.

## Reskinning to match the real product
Preferred order of fidelity: (1) set Theme tokens to "recognizably us"; (2) for a closer match, copy the product's
real CSS custom properties into the `--p-*` variables; (3) for a pixel match, replace the preview markup/CSS with the
product's actual chat-message HTML/CSS (kept behind the same token names so the engine is untouched).
