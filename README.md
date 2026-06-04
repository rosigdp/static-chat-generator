# Static Chat Generator

A lightweight tool for authoring **prompt → expected-response cases** for our LLM product, then
**playing them back for demo recordings** and **exporting them as a spec for developers**.

One authoring step → two deliverables (a recordable demo + a machine-readable spec). No design
software and no per-seat license required: it runs in any browser.

## How the chrome stays faithful

`index.html` is **the real Claudia conversation page** (HTML + CSS extracted from an MHTML
snapshot of the live app), with the framework JS stripped out and a small playback engine
bolted on. The sidebar, top bar, composer, message bubbles, and the entire Tailwind/Catapa
design system come straight from your product — not a look-alike rebuild.

When the live UI changes, you don't rewrite the tool. You refresh the chrome:

1. In your browser, open the conversation page on Claudia and "Save page as → Webpage, Single File (.mhtml)".
2. Drop it into `mhtml/` (replacing the previous one), or edit the path at the top of `build_studio.py`.
3. Run `python3 build_studio.py`. A new `index.html` is produced with your latest UI.

The case data, theme overrides, and playback engine are untouched.

---

## The pieces

| File | What it is | Who edits it | How |
| --- | --- | --- | --- |
| `cases-template.xlsx` | The **authoring input**. One row per case + a Theme sheet. | Anyone (PMs, UX) | In Excel / Google Sheets |
| `index.html` | The **tool** — your real Claudia chrome with the playback engine bolted on. | Rarely; via Claude Code | See `TWEAKS.md` |
| `build_studio.py` | The **builder** that produces `index.html` from the MHTML + engine. | When tweaking | See `TWEAKS.md` |
| `GETTING-STARTED.md` | First-time coder onboarding. Read this first if you've never coded. | — | — |
| `TWEAKS.md` | Cookbook of common changes with copy-pasteable prompts. | — | — |
| `SPEC.md` | The **regeneration spec**. Hand to Claude if everything breaks. | When behavior changes | Read by Claude |
| `README.md` | This file. | — | — |

The valuable, durable asset is the **xlsx of cases**. The tool is a disposable renderer over it —
if `index.html` ever breaks, it can be regenerated from `SPEC.md` in minutes (see "If the tool breaks").

---

## Daily use

1. Open `cases-template.xlsx`, add a row per case on the **Cases** sheet
   (User Prompt · Response Type · Response · Expected Behavior).
2. Open `index.html` in a browser → **Import .xlsx** → choose your file.
3. **Play** to preview. Use **Record mode** (hides the editor) + your screen recorder for the demo.
4. **Spec JSON** downloads the cases (with version stamps) for the dev team.

> The `.xlsx` import needs internet **once** to load the spreadsheet parser; recording works offline after.

### Response formats (the "Response" cell)
- **markdown** — normal text; supports `**bold**`, `*italics*`, `` `code` ``, lists, `>` quotes, and `| pipe | tables |`.
- **table** — one row per line, cells split by `|`. First line is the header.
- **buttons** — one per line: `Label | optional_action_name`.
- **a2ui** — A2UI v0.9 envelopes as a JSON array (or one JSON object per line). Renders as real UI; button/input clicks log to the **Events** console.

---

## "I want to change X" → do Y

| You want to… | Do this | Needs code? |
| --- | --- | --- |
| Add / edit / reorder cases | Edit `cases-template.xlsx`, re-import | No |
| Recolor / rename / change avatar | Edit the **Theme** sheet in the xlsx, **or** the in-app **Branding** tab | No |
| Match the product's exact look | Set the Theme values; for a pixel match, see "Reskinning" in `SPEC.md` | No (tokens) |
| Add a new response type, fix a bug, support a new A2UI component | Open `index.html` in Claude and describe the change (see below) | Yes — via Claude |
| Track which UI version a case targets | Bump `VERSION` at the top of the `<script>` in `index.html`; it's stamped into every export | One-line edit |

### Changing behavior via Claude (no JS knowledge needed)
1. Upload `index.html` (and `SPEC.md` for context) to Claude.
2. Describe the change in plain language, e.g. *"Add a 'system note' response type that renders as small grey centered text."*
3. Claude returns an updated `index.html`. Commit it.

This is why the bus factor is low: **the maintainer skill is describing what you want, not writing JavaScript.**

---

## Hosting it for the team (recommended)

Put this folder in a Git repo so it's shared, versioned, and reviewable — not a file on one laptop.

```
git init && git add . && git commit -m "Static Chat Generator v1"
# push to a private GitHub repo, then enable GitHub Pages on the main branch
```

With **GitHub Pages**, the tool becomes a URL everyone opens. Non-coders can edit files (including the
xlsx and theme) directly in GitHub's web UI, with full history and one-click rollback.

---

## If the tool breaks (recovery)

You can rebuild it from scratch: give Claude `SPEC.md` and say *"regenerate index.html from this spec."*
Because the cases live in the xlsx (not inside the tool), nothing is lost.

---

## Make it owned by the team

- Have **2–3 teammates each make one real change this week** (a color, a case, a small feature via Claude).
  A maintainer who has never touched it isn't a maintainer.
- Keep it **lean**. Every feature pushed into the xlsx/Theme is one less reason to touch code.
- Resist pixel-perfect fidelity — "recognizably us" is enough for demos and is far cheaper to maintain.
