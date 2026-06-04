# Tweaks Cookbook

Each entry below is one common change you might want to make. The **Prompt to
Claude** is the exact text to paste into Claude Code's chat — copy it, tweak
the bit in `«angle brackets»` if you want different values, and send.

After Claude makes the change it will offer to rebuild and you'll see a diff.
Accept, allow the rebuild, refresh `index.html` in your browser, you're done.

> Anatomy reminder: the engine, overlay styles, sample cases, and A2UI defaults
> all live as Python multi-line strings inside `build_studio.py`. The strings
> are named `ENGINE_JS`, `STUDIO_CSS`, `TOOLBAR_HTML`. The "chrome" (sidebar,
> top bar, composer, message DOM) comes from the MHTML, not from these strings.

---

## 1. Recolor the Studio toolbar / Play button

> In `build_studio.py`, in the `STUDIO_CSS` string, change
> `.studio-tb .studio-btn.primary` background from `#ff6b4a` to **«#2563eb»**.
> Then rebuild.

## 2. Change the default model label ("GPT 5.5")

> In `build_studio.py`, in `ENGINE_JS`, change `DEFAULT_BRAND.modelName` from
> `"GPT 5.5"` to **«"Claude Sonnet 4"»**. Also update the same value in the
> `Theme` sheet of `cases-template.xlsx` so they stay in sync. Then rebuild.

## 3. Change the "thinking" / "done" status text (e.g. translate it)

> In `build_studio.py`, in `ENGINE_JS`, find the two status strings in `studioPlay()`:
> `'Mempersiapkan jawaban…'` and `'Selesai Mempersiapkan Jawaban (${secs} detik)'`.
> Replace them with **«"Thinking…"»** and **«"Done in ${secs} s"»**. Then rebuild.

## 4. Change playback timing defaults (faster/slower out of the box)

> In `build_studio.py`, in `TOOLBAR_HTML`, change the `value="6"` on the
> sliders `studioTypeSpeed`, `studioStreamSpeed`, `studioTurnGap` to
> **«8»** (faster) or **«4»** (slower). Then rebuild.

## 5. Refresh the chrome from a new MHTML (after Catapa redesigns the UI)

> Save the latest Claudia conversation page as `.mhtml` and put it at
> **«/path/to/new.mhtml»**. Update the `MHTML` constant at the top of
> `build_studio.py` to that path. Run `python3 build_studio.py`. Open
> `index.html` and confirm the new chrome renders.

## 6. Update the sample cases shown when the tool first opens

> In `build_studio.py`, in `ENGINE_JS`, replace the `studio.turns = [ ... ]`
> array with **«these new cases»** (paste them in the same shape: `{prompt, type,
> notes, content}`). Then rebuild.

> Easier alternative: edit `cases-template.xlsx`, then click **Import .xlsx**
> in the Studio drawer in your browser. No code change at all.

## 7. Tweak the user bubble shape, padding, or color

> In `build_studio.py`, in `ENGINE_JS`, find `mkUserDOM()`. Change the bubble
> wrapper classes — currently `rounded-3xl rounded-ee-none px-5 py-2
> bg-background-alternate`. Use Tailwind utility classes from Catapa's CSS:
> **«e.g. `rounded-2xl px-4 py-3 bg-muted`»**. Then rebuild.

> The chrome uses Catapa's own Tailwind config, so utility classes like
> `bg-muted`, `bg-primary`, `text-foreground`, `border`, `rounded-md`, `p-4`
> all work natively.

## 8. Add a new response type (e.g. "image" or "code-only")

> In `build_studio.py`, in `ENGINE_JS`:
> 1. Add `'image'` to the `RESP_TYPES` array.
> 2. Add an `else if(type==='image')` branch inside `streamInto(el, turn)` that
>    renders **«`<img src="${esc(src)}" style="max-width:100%;border-radius:8px">`»**.
> 3. Add a label `image:'Image'` to the pills map in `studioTurn(t,i)`.
> 4. Add a placeholder hint in the same `ph` object: `image:"Paste an image URL"`.
> Rebuild.

## 9. Add a new theme token that the xlsx Theme sheet can set

> In `build_studio.py`, in `ENGINE_JS`:
> 1. Add the new key to `DEFAULT_BRAND` (e.g. `conversationSubtitle:""`).
> 2. Use it wherever you want (e.g. inside `studioApplyBrand()`).
> 3. Add a row for it in the Theme sheet of `cases-template.xlsx`
>    (column A is the key, B the value, C a description).
> Rebuild.

## 10. Disable typing into the real composer during playback

> In `build_studio.py`, in `ENGINE_JS`'s `studioPlay()` function, remove the
> three lines that touch `composer`: the typing loop's `composer.value =`,
> the `composer.classList.add('studio-caret')`, and the cleanup. User bubbles
> will still appear; only the composer-typing animation is gone. Rebuild.

## 11. Change the conversation title shown in the top bar

> No code change needed. Open Studio drawer → Branding tab → edit
> **"Conversation title."** Or in the xlsx Theme sheet, add a row
> `conversationTitle | «Your title»`.

## 12. Add a markdown feature (e.g. checklists `- [ ]`)

> In `build_studio.py`, in `ENGINE_JS`'s `renderMarkdown(src)`, add a branch
> before the regular `[-*] ` list branch that detects `- [ ]` / `- [x]` and
> outputs `<li><input type="checkbox" disabled ${checked?'checked':''}> ...</li>`.
> Then rebuild.

---

## When you don't know which file to edit

If a tweak doesn't fit any of the above, paste this:

> Look at the codebase and tell me where you'd change **«this thing I want»** —
> which file and which section. Don't edit anything yet; just explain.

Claude will read the relevant files and propose a plan. You approve, then it
makes the change.
