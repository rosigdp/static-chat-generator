# Getting Started (first-time coder edition)

You don't need to learn to code. You'll describe changes in plain language and
Claude does them for you — on your computer, with a visual diff you accept or
reject for each change. This guide gets you from zero to making your first tweak.

There is **no terminal in this workflow.** Claude Code's desktop app gives you
a graphical interface and runs any commands for you when needed.

---

## What you need

- A computer (macOS or Windows)
- A Claude Pro subscription (your team already has this)
- The repo folder — unzip `static-chat-generator-repo.zip` somewhere easy to find,
  like `Documents/static-chat-generator`

---

## Step 1 — Install Claude (5 minutes)

1. Go to **<https://claude.com/download>**.
2. Download the installer for your OS and run it.
3. Open the app. Sign in with the same email you use for Claude Pro.

The Claude desktop app has three tabs at the top: **Chat**, **Cowork**, and
**Code**. You'll live in the **Code** tab. It comes with everything you need —
no extra installs, no Node.js, no terminal.

---

## Step 2 — Install Python (one-time, ~2 minutes)

The tool rebuilds itself with a small Python script. You won't run it directly
— Claude will — but Python has to be on your computer.

- **macOS:** open the Terminal app and type `python3 --version`. If you see a
  version number, you're done. If not, install from <https://python.org/downloads>.
- **Windows:** install from <https://python.org/downloads>. On the first install
  screen, **check the box "Add Python to PATH"** before clicking Install.

That's the only install you do directly. Everything else, Claude handles.

---

## Step 3 — Open the repo in Claude

1. In the Claude app, click the **Code** tab.
2. Click **Open folder** (or "Add project").
3. Pick the unzipped `static-chat-generator` folder.

You'll see the files on the left (`index.html`, `build_studio.py`, the xlsx,
the docs) and a chat area on the right. Anything you type on the right talks
about the files on the left.

> First time only: Claude may ask whether to trust this folder. Yes.

---

## Step 4 — Your first tweak (end-to-end)

Let's change the Studio toolbar's Play button color, as a no-stakes warm-up.

1. In the chat area, paste this:

   > In `build_studio.py`, find the `STUDIO_CSS` block. Inside the rule
   > `.studio-tb .studio-btn.primary`, change `background:#ff6b4a` to
   > `background:#2563eb`. Then run `python3 build_studio.py` to rebuild
   > `index.html`.

2. Claude shows you a **diff** — the exact lines it wants to change, in red and
   green. Click **Accept** to apply, or **Reject** if it looks wrong.
3. Claude then asks permission to run the rebuild command. Click **Allow**.
4. Open `index.html` in your browser (double-click it in the file list, or open
   it from your computer). You'll see the Play button is now blue. Done.

That's the entire loop. Describe, accept, refresh.

---

## Step 5 — When you're ready to share with the team

You can do everything above with a local folder. When you want the team to
collaborate without emailing files around:

1. Create a free account at <https://github.com>.
2. Create a **private** repository.
3. Drag the `static-chat-generator` folder's contents into the GitHub web UI (the
   "uploading an existing file" button). No git commands needed.
4. Enable **GitHub Pages** in the repo's Settings → Pages. The tool becomes
   a URL the whole team opens.

Now any teammate with Claude Pro can clone the repo into their Claude Code
desktop app and make changes the same way you did.

---

## Common gotchas

- **"Claude asks permission to run a command."** That's normal — it's running
  the rebuild script. Allow it.
- **"I made the change but the page looks the same."** You probably need to
  refresh `index.html` in your browser, or you forgot to rebuild. Tell Claude
  "rebuild" if it didn't.
- **"Something broke and I don't know what."** In Claude Code, tell it
  "undo my last change." It tracks history. If it's really broken, see
  "When everything breaks" below.

---

## When everything breaks (recovery)

The cases live in the xlsx — **that's the asset you can't lose**. The tool can
always be rebuilt:

- Open `SPEC.md` in Claude and say: *"Regenerate `build_studio.py` and
  `index.html` from this spec."*
- For the chrome (your real product look), drop a fresh MHTML next to
  `build_studio.py` and ask Claude to point the builder at it.

So even in the worst case, you've lost maybe an hour. The cases are safe.

---

## Where to go from here

- **`TWEAKS.md`** — a cookbook of common tweaks with copy-pasteable prompts.
  Start there. Most things you'll want to change are already listed.
- **`README.md`** — overview and team workflow.
- **`SPEC.md`** — the build manual. Pass this to Claude if you ever need to
  rebuild from scratch.
