#!/usr/bin/env python3
"""Build static-chat-generator/index.html by grafting the playback engine onto the
real Claudia conversation page extracted from the user's MHTML."""
import email, base64, re, sys, pathlib
from bs4 import BeautifulSoup

HERE      = pathlib.Path(__file__).parent
MHTML_DIR = HERE / "mhtml"
# Use the most recently dropped .mhtml in mhtml/ (refresh by saving a fresh
# one from Claudia in Chrome and dropping it into that folder).
MHTML = max(MHTML_DIR.glob("*.mhtml"), key=lambda p: p.stat().st_mtime, default=None)
if MHTML is None:
    sys.exit(f"No .mhtml file found in {MHTML_DIR} — save one from Claudia and drop it in.")
OUT   = HERE / "index.html"

# --------- parse MHTML ----------
msg = email.message_from_file(open(MHTML))
parts = list(msg.walk())
html_src = None
res = {}  # url -> (ct, bytes)
for p in parts:
    ct = p.get_content_type()
    loc = p.get("Content-Location","")
    payload = p.get_payload(decode=True) or b""
    if ct == "text/html" and html_src is None:
        html_src = payload.decode("utf-8","replace")
    elif loc:
        res[loc] = (ct, payload)

def data_uri(ct, data):
    return f"data:{ct};base64,{base64.b64encode(data).decode()}"

soup = BeautifulSoup(html_src, "lxml")

# 1) remove framework JS and prefetch/preload links
for s in soup.find_all("script"): s.decompose()
for l in list(soup.find_all("link")):
    rels = l.get("rel",[])
    href = l.get("href","")
    if "stylesheet" in rels:
        if href in res:
            ct, data = res[href]
            css = data.decode("utf-8","replace")
            # rewrite url(...) to data URIs where the resource is in the MHTML
            def rep(m):
                u = m.group(1).strip(' \'"')
                if u in res:
                    c2,d2 = res[u]; return f"url({data_uri(c2,d2)})"
                return m.group(0)
            css = re.sub(r"url\(([^)]+)\)", rep, css)
            new = soup.new_tag("style"); new.string = css
            l.replace_with(new)
        else:
            l.decompose()
    elif any(x in rels for x in ("preload","modulepreload","prefetch","manifest","dns-prefetch")):
        l.decompose()
# remove inline <style> only if empty
# (keep all existing ones)

# 2) inline <img> src to data URIs
for img in soup.find_all("img"):
    src = img.get("src","")
    if src in res:
        ct, data = res[src]
        img["src"] = data_uri(ct, data)

# 3) safety net: Google Fonts for Inter + Open Sans (font files often not in MHTML)
soup.head.append(BeautifulSoup(
    '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Open+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">',
    "lxml").link)

# 4) find scroll container; compute LCA of all message-* and tag it as the messages list
scroll = soup.find("div", class_=lambda c: c and "overflow-y-auto" in c and "scroll-smooth" in c)
scroll["data-chat-scroll"] = "1"
# tag the chat region below the top bar (grandparent of the scroll) as the overlay mount
if scroll.parent is not None and scroll.parent.parent is not None:
    scroll.parent.parent["data-chat-area"] = "1"
    # the content card (great-grandparent) holds the top bar + chat; the first-screen
    # overlay mounts here so its grid background sits behind the (transparent) top bar
    if scroll.parent.parent.parent is not None:
        scroll.parent.parent.parent["data-main-card"] = "1"
msgs_all = soup.find_all(id=lambda x: x and x.startswith("message-"))
def _anc(n):
    a=[]; p=n
    while p is not None: a.append(p); p=p.parent
    return a
chains=[_anc(m) for m in msgs_all]
lca=None
for cand in chains[0]:
    if all(cand in ch for ch in chains[1:]): lca=cand; break
if lca is None: lca=msgs_all[0].parent
lca["data-msg-list"]="1"

# 5) clear every direct child of lca that contains a message-* descendant
for child in list(lca.children):
    if getattr(child,"name",None) and child.find(id=lambda x: x and x.startswith("message-")):
        child.decompose()

# 6) tag the conversation title h1 so engine can set it
title = soup.find("h1", class_=lambda c: c and "line-clamp-2" in c)
if title:
    title["data-convo-title"] = "1"
    title.string = ""
    if title.parent is not None:
        title.parent["data-topbar"] = "1"   # made transparent on the first screen

# 6b) tag the sidebar conversation-list container so the engine can rebuild it
#     (one row per conversation title; active row highlighted via bg-secondary).
#     The active captured row carries a static bg-secondary class; its parent is the list.
sel_a = soup.find(lambda t: t.name == "a" and t.get("class") and "bg-secondary" in t.get("class"))
if sel_a is not None and sel_a.parent is not None:
    sel_a.parent["data-convo-list"] = "1"

# 6c) tag the sidebar Proyek (project) name so the engine can edit it
proyek_lbl = soup.find("p", string=lambda s: s and s.strip() == "Proyek")
if proyek_lbl is not None:
    proyek_nm = proyek_lbl.find_next_sibling("p")
    if proyek_nm is not None:
        proyek_nm["data-proyek-name"] = "1"

# 6e) tag the "Percakapan Baru" new-chat button (so the engine can de-highlight rows on screen 1)
new_chat = soup.find(lambda t: t.name in ("a", "button") and t.get_text(strip=True) == "Percakapan Baru")
if new_chat is not None:
    new_chat["data-new-chat"] = "1"

# 6f) tag the composer block (Agen AI row + input card) so the engine can relocate it to screen 1
_ta = soup.find("textarea")
if _ta is not None:
    _blk = _ta
    while _blk is not None and not (_blk.get("class") and any("max-w-[720px]" in c for c in _blk.get("class"))):
        _blk = _blk.parent
    if _blk is not None:
        _blk["data-composer-block"] = "1"
    # tag the in-box bottom toolbar (the row holding the "+" button) so the engine
    # can place the LLM model selector there, next to "+", as in the real product.
    _form = _ta.find_parent("form")
    if _form is not None:
        _plus = None
        for _b in _form.find_all("button"):
            _sv = _b.find("svg")
            if _sv is not None and _sv.get("class") and "lucide-plus" in _sv.get("class"):
                _plus = _b; break
        if _plus is not None and _plus.parent is not None and _plus.parent.parent is not None:
            _plus.parent.parent["data-llm-toolbar"] = "1"

# 6g) tag the share ("Bagi") action so the engine can hide it on screen 1
_share = soup.find(lambda t: t.name == "button" and t.get_text(strip=True) == "Bagi")
if _share is not None:
    _share["data-share-action"] = "1"

# 6d) tag the bottom-sidebar profile (name, email, avatar) so the engine can edit it
email_span = soup.find("span", string=lambda s: s and "@" in s and "." in s)
if email_span is not None:
    email_span["data-profile-email"] = "1"
    name_span = email_span.find_previous_sibling("span")
    if name_span is not None:
        name_span["data-profile-name"] = "1"
    card = email_span.find_parent(class_=lambda c: c and "cursor-pointer" in c)
    if card is not None:
        avatar = card.find("span", class_=lambda c: c and "rounded-full" in c and "size-10" in c)
        if avatar is not None:
            avatar["data-profile-avatar"] = "1"

# 7) freeze any composer textarea/buttons so they don't behave weirdly
for ta in soup.find_all("textarea"):
    ta["data-claudia-composer"] = "1"
    ta["readonly"] = "readonly"
    # we'll type into it during playback
for b in soup.find_all("button"):
    b["type"] = "button"
    if not b.get("data-studio"):
        b["onclick"] = "return false;"

# 8) inject Studio CSS + toolbar + drawer + engine
STUDIO_CSS = r"""
/* === Static Chat Generator overlay (scoped via .studio- prefix) === */
.studio-fab,.studio-drawer,.studio-tb{font-family:Inter,system-ui,sans-serif}
.studio-tb{
  position:fixed; bottom:18px; left:50%; transform:translateX(-50%);
  display:flex; align-items:center; gap:8px; padding:8px 10px;
  background:rgba(20,22,28,.92); color:#fff; border-radius:14px;
  box-shadow:0 12px 40px -8px rgba(0,0,0,.4);
  backdrop-filter: blur(8px); z-index:99998;
}
.studio-tb .studio-btn{
  background:#2a2e3a; border:0; color:#fff; padding:7px 12px;
  border-radius:9px; font-size:12.5px; font-weight:500; cursor:pointer;
}
.studio-tb .studio-btn.primary{background:#2563eb}
.studio-tb .studio-btn:hover{filter:brightness(1.1)}
.studio-tb .studio-speed{display:flex;align-items:center;gap:6px;font-size:11px;color:#bbb}
.studio-tb input[type=range]{width:70px;accent-color:#ff6b4a}
.studio-tb .sep{width:1px;height:20px;background:#3a3e4a}

.studio-drawer{
  position:fixed; top:0; right:0; height:100vh; width:420px; max-width:90vw;
  background:#16181f; color:#e8eaf0; box-shadow:-20px 0 60px -10px rgba(0,0,0,.4);
  transform:translateX(100%); transition:transform .25s; z-index:99999;
  display:flex; flex-direction:column;
}
.studio-drawer.open{transform:translateX(0)}
.studio-drawer-head{
  padding:14px 16px; border-bottom:1px solid #262a36;
  display:flex; align-items:center; justify-content:space-between;
}
.studio-drawer-head b{font-size:14.5px}
.studio-drawer-head button{background:none;border:0;color:#9aa0b4;font-size:18px;cursor:pointer}
.studio-tabs{display:flex;gap:4px;padding:8px 10px;background:#1c1f29;border-bottom:1px solid #262a36}
.studio-tabs button{flex:1;background:transparent;border:0;color:#9aa0b4;padding:7px;border-radius:7px;font-size:12px;font-weight:500;cursor:pointer}
.studio-tabs button.active{background:#0e0f13;color:#fff}
.studio-scroll{overflow-y:auto;padding:12px;flex:1}
.studio-scroll::-webkit-scrollbar{width:8px}
.studio-scroll::-webkit-scrollbar-thumb{background:#2c303d;border-radius:8px}
.studio-io{padding:10px 12px;border-top:1px solid #262a36;display:flex;gap:8px;flex-wrap:wrap}
.studio-io button{background:#262a36;border:0;color:#e8eaf0;padding:8px 12px;border-radius:8px;font-size:12px;cursor:pointer}
.studio-io button:hover{background:#323645}

.studio-turn{background:#1c1f29;border:1px solid #262a36;border-radius:12px;margin-bottom:10px;overflow:hidden}
.studio-turn-h{display:flex;align-items:center;gap:6px;padding:8px 10px;background:#1a1d27;border-bottom:1px solid #262a36}
.studio-turn-h .num{width:18px;height:18px;border-radius:5px;background:#ff6b4a;color:#fff;display:grid;place-items:center;font-size:10.5px;font-weight:600}
.studio-turn-h .t{flex:1;font-size:11.5px;font-weight:600}
.studio-turn-h .ic{background:none;border:0;color:#7b8094;width:22px;height:22px;border-radius:5px;cursor:pointer}
.studio-turn-h .ic:hover{background:#262a36;color:#e8eaf0}
.studio-turn-b{padding:10px}
.studio-fld{margin-bottom:9px}
.studio-fld:last-child{margin-bottom:0}
.studio-fld label{display:block;font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:#7b8094;margin-bottom:4px;font-weight:600}
.studio-fld textarea,.studio-fld input,.studio-fld select{
  width:100%;background:#12141b;border:1px solid #262a36;color:#e8eaf0;
  border-radius:8px;padding:7px 9px;font-size:12.5px;resize:vertical;font-family:inherit;
}
.studio-fld textarea{min-height:48px;line-height:1.45}
.studio-fld textarea.code{font-family:"Geist Mono",ui-monospace,monospace;font-size:11.5px}
.studio-pills{display:flex;gap:3px;margin-bottom:6px;flex-wrap:wrap}
.studio-pills button{border:1px solid #262a36;background:#12141b;color:#9aa0b4;padding:3px 8px;border-radius:14px;font-size:10.5px;cursor:pointer}
.studio-pills button.active{background:#7c5cff;border-color:#7c5cff;color:#fff}
.studio-add{width:100%;border:1.5px dashed #313646;background:transparent;color:#9aa0b4;padding:9px;border-radius:11px;font-size:12px;cursor:pointer}
.studio-add:hover{border-color:#ff6b4a;color:#e8eaf0}
.studio-block{border:1px solid #262a36;border-radius:9px;padding:7px;margin-bottom:6px;background:#0f1117}
.studio-block-h{display:flex;align-items:center;gap:4px;margin-bottom:5px}
.studio-block-h .studio-pills{margin-bottom:0;flex:1}
.studio-block-h .ic{flex:0 0 auto;border:0;background:transparent;color:#7b8094;font-size:13px;cursor:pointer;padding:2px 4px;border-radius:6px}
.studio-block-h .ic:hover{color:#e8eaf0;background:#1a1d27}
.studio-add-block{width:100%;border:1px dashed #313646;background:transparent;color:#9aa0b4;padding:6px;border-radius:8px;font-size:11.5px;cursor:pointer;margin-top:2px}
.studio-add-block:hover{border-color:#3ba776;color:#e8eaf0}
.studio-agent{display:flex;align-items:center;gap:8px;padding:6px 8px;border:1px solid #262a36;border-radius:9px;margin-bottom:5px;background:#12141b}
.studio-agent.active{border-color:#3ba776;background:#13201a}
.studio-agent input[type=checkbox],.studio-agent input[type=radio]{width:14px;height:14px;flex:0 0 auto;margin:0;accent-color:#3ba776;cursor:pointer}
.studio-agent .nm{flex:1;font-size:12px;color:#e8eaf0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.studio-agent.off .nm{color:#7b8094}
.studio-agent input.nm-edit{flex:1;min-width:0;width:auto;font-size:12px;padding:4px 7px;border-radius:6px}
.studio-agent.off input.nm-edit{color:#7b8094}
.studio-agent .rm{flex:0 0 auto;border:0;background:transparent;color:#7b8094;font-size:14px;line-height:1;cursor:pointer;padding:0 2px}
.studio-agent .rm:hover{color:#ff6b4a}
.studio-agent-add{display:flex;gap:5px;margin-top:6px}
.studio-agent-add input{flex:1}
.studio-agent-add button{flex:0 0 auto;border:1px solid #3ba776;background:transparent;color:#3ba776;border-radius:9px;padding:0 12px;font-size:12px;cursor:pointer}
.studio-agent-add button:hover{background:#3ba776;color:#0c0e13}
/* ---- first screen (new-chat landing) overlay ---- */
[data-chat-area]{position:relative}
.fs-screen{position:absolute;inset:0;z-index:30;display:flex;align-items:center;justify-content:center;background:hsl(var(--background));overflow:hidden}
/* grid + gradient background + animated green tracers */
.fs-bg{position:absolute;inset:0;z-index:0;pointer-events:none;overflow:hidden}
.fs-grid{position:absolute;inset:0;background-image:linear-gradient(to right,hsl(var(--foreground)/.06) 1px,transparent 1px),linear-gradient(to bottom,hsl(var(--foreground)/.06) 1px,transparent 1px);background-size:100px 100px;-webkit-mask-image:radial-gradient(130% 95% at 50% 25%,#000 60%,transparent 100%);mask-image:radial-gradient(130% 95% at 50% 25%,#000 60%,transparent 100%)}
.fs-glow{position:absolute;inset:0;background:radial-gradient(95% 62% at 50% 104%,hsl(var(--primary)/.42),hsl(var(--primary)/.16) 48%,transparent 76%)}
.fs-tracers{position:absolute;inset:0}
.fs-tracer{position:absolute}
.fs-tracer polyline{fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:var(--len);animation:fsDraw 2.8s ease-out forwards}
@keyframes fsDraw{0%{stroke-dashoffset:var(--len);opacity:0}10%{opacity:1}55%{stroke-dashoffset:0;opacity:1}100%{stroke-dashoffset:0;opacity:0}}
.fs-inner{position:relative;z-index:1;width:100%;max-width:720px;display:flex;flex-direction:column;align-items:center;gap:22px;padding:24px 20px;text-align:center}
/* on the first screen the top bar sits above the overlay (transparent) so the grid shows through */
[data-topbar].fs-topbar-up{position:relative;z-index:40;background:transparent !important}
.fs-greet{font-size:1.5rem;line-height:1.3;color:hsl(var(--foreground))}
.fs-greet strong{font-weight:600}
.fs-sub{display:inline-flex;flex-wrap:wrap;align-items:center;justify-content:center;gap:6px;max-width:640px;font-size:.875rem;line-height:1.35;color:hsl(var(--foreground)/.5)}
.fs-sub .fs-proyek{display:inline-flex;align-items:center;gap:6px;color:hsl(var(--foreground))}
.fs-composer-slot{width:100%;display:flex;justify-content:center}
.fs-chips{display:flex;gap:8px;justify-content:center;flex-wrap:wrap;width:100%}
.studio-fab{
  position:fixed; bottom:18px; right:18px; width:auto; padding:10px 14px;
  background:#ff6b4a; color:#fff; border:0; border-radius:14px;
  font-size:13px; font-weight:600; cursor:pointer; z-index:99997;
  box-shadow:0 8px 24px -6px rgba(255,107,74,.5);
}
.studio-console{
  position:fixed; left:50%; bottom:78px; transform:translateX(-50%);
  width:560px; max-width:90vw; max-height:160px; overflow-y:auto;
  background:#0d1117; color:#9aa0b4; border:1px solid #262a36; border-radius:12px;
  font-family:"Geist Mono",ui-monospace,monospace; font-size:11px; padding:8px 12px;
  z-index:99996; display:none;
}
.studio-console.show{display:block}
.studio-console b{color:#3ddc91}

/* Hide everything Studio in record mode */
html.studio-recording .studio-tb,
html.studio-recording .studio-drawer,
html.studio-recording .studio-fab,
html.studio-recording .studio-console{display:none !important}

/* A2UI components, scoped */
.a2-surface{border:1px solid hsl(var(--border));border-radius:12px;overflow:hidden;background:hsl(var(--background));max-width:560px}
.a2-agent-bar{display:flex;align-items:center;gap:7px;padding:7px 11px;font-size:11.5px;color:hsl(var(--muted-foreground));border-bottom:1px solid hsl(var(--border));background:hsl(var(--muted))}
.a2-pad{padding:14px}
.a2-col{display:flex;flex-direction:column;gap:9px}
.a2-row{display:flex;gap:9px;align-items:center;flex-wrap:wrap}
.a2-row.start{justify-content:flex-start}.a2-row.spaceBetween{justify-content:space-between}.a2-row.center{align-items:center}
.a2-card{border:1px solid hsl(var(--border));border-radius:10px;padding:12px;background:hsl(var(--background))}
.a2-divider{height:1px;background:hsl(var(--border));width:100%}
.a2-text{font-size:14px;line-height:1.5;color:hsl(var(--foreground))}
.a2-text.h1{font-size:1.4em;font-weight:700}.a2-text.h2{font-size:1.18em;font-weight:700}
.a2-text.caption{font-size:11.5px;color:hsl(var(--muted-foreground));text-transform:uppercase;letter-spacing:.04em}
.a2-btn{border:0;border-radius:8px;padding:9px 16px;font-size:13.5px;font-weight:600;cursor:pointer;font-family:inherit}
.a2-btn.primary{background:hsl(var(--primary));color:hsl(var(--primary-foreground))}
.a2-btn.borderless{background:transparent;color:hsl(var(--primary))}
.a2-field{display:flex;flex-direction:column;gap:4px}
.a2-field input{border:1px solid hsl(var(--border));border-radius:8px;padding:8px 11px;font-size:13.5px;width:100%;background:hsl(var(--background));color:hsl(var(--foreground));font-family:inherit}
.a2-choice{display:flex;flex-direction:column;gap:6px}
.a2-choice label{display:flex;gap:8px;align-items:center;font-size:13.5px;color:hsl(var(--foreground))}
.a2-check{display:flex;gap:8px;align-items:center;font-size:13.5px;color:hsl(var(--foreground))}
.a2-err{color:#c0392b;font-family:"Geist Mono",monospace;font-size:12px;padding:10px;background:#fdecea;border-radius:9px;white-space:pre-wrap}
.a2-btn.outline{background:#fff;border:1px solid hsl(var(--border));color:hsl(var(--foreground))}
.a2-btn.ghost{background:transparent;color:hsl(var(--foreground))}
.a2-btn:disabled{opacity:.45;cursor:not-allowed;background:hsl(var(--muted));color:hsl(var(--muted-foreground));border-color:transparent}
.a2-btn.cell{width:44px;height:44px;padding:0;border-radius:50%;display:inline-grid;place-items:center;font-weight:600}
.a2-text.cellhead{width:44px;text-align:center;color:hsl(var(--muted-foreground));font-size:12px}
.a2-card-info{background:#eaf4fb;border-color:#d6e9f7}
.a2-row.end{justify-content:flex-end;width:100%}.a2-row.spaceBetween{width:100%}.a2-row.start{align-items:flex-start}
.a2-row{flex-wrap:nowrap}
.a2-btn .a2-text,.a2-btn p,.a2-text>p:only-child{margin:0}
.a2-surface{max-width:720px}

/* Green focus outline while the engine is typing into the composer */
.studio-typing{transition:none !important;border-color:hsl(var(--primary)) !important;box-shadow:0 0 0 1.5px hsl(var(--primary)),0 1px 30px 4px rgba(7,28,70,.09) !important}
/* Caret while typing into composer or user bubble */
.studio-caret::after{content:"\u258F";color:hsl(var(--primary));animation:studioCaret 1s steps(1) infinite;margin-left:1px}
/* "Mempersiapkan Jawaban" preparation steps loader */
.a-prep{margin:4px 0 2px;padding-left:14px;border-left:2px solid hsl(var(--border));display:flex;flex-direction:column;gap:11px}
.a-prep-step{display:flex;align-items:center;gap:10px;color:hsl(var(--primary));font-size:1rem;line-height:1.75;font-family:inherit}
.a-prep-ic{width:18px;height:18px;flex:0 0 auto;display:inline-flex;align-items:center;justify-content:center;color:hsl(var(--primary))}
.a-prep-spin{width:15px;height:15px;border:2px solid hsl(var(--primary)/.25);border-top-color:hsl(var(--primary));border-radius:50%;animation:aPrepSpin .7s linear infinite}
@keyframes aPrepSpin{to{transform:rotate(360deg)}}
@keyframes studioCaret{50%{opacity:0}}

/* Make sure injected button/quick-reply chips look at home using Catapa tokens */
.quick-chip{
  display:inline-flex; align-items:center; padding:8px 14px;
  border:1px solid hsl(var(--border)); border-radius:999px; font-size:13px;
  color:hsl(var(--foreground)); background:hsl(var(--background));
  cursor:pointer; transition:.15s; font-family:inherit;
}
.quick-chip:hover{background:hsl(var(--muted))}
.quick-chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}
"""

TOOLBAR_HTML = """
<div id="studioTb" class="studio-tb" data-studio="1">
  <button class="studio-btn primary" id="studioPlayBtn" data-studio="1" onclick="studioPlay()">\u25B6 Play</button>
  <button class="studio-btn" data-studio="1" onclick="studioReset()">\u21BB Reset</button>
  <span class="sep"></span>
  <span class="studio-speed">Type<input type="range" min="1" max="10" value="6" id="studioTypeSpeed"></span>
  <span class="studio-speed">Stream<input type="range" min="1" max="10" value="6" id="studioStreamSpeed"></span>
  <span class="studio-speed">Gap<input type="range" min="0" max="10" value="4" id="studioTurnGap"></span>
  <span class="sep"></span>
  <button class="studio-btn" data-studio="1" onclick="studioToggleRec()">\u26F6 Record</button>
  <button class="studio-btn" data-studio="1" onclick="studioToggleConsole()">\u26A1 Events</button>
</div>
<button class="studio-fab" id="studioFab" data-studio="1" onclick="studioToggleDrawer()">\u2630 Studio</button>
<div id="studioDrawer" class="studio-drawer" data-studio="1">
  <div class="studio-drawer-head">
    <b>Static Chat Generator</b>
    <button data-studio="1" onclick="studioToggleDrawer()">\u2715</button>
  </div>
  <div class="studio-tabs">
    <button class="active" data-studio="1" id="studioTabCases" onclick="studioSwitchTab('cases')">Cases</button>
    <button data-studio="1" id="studioTabBrand" onclick="studioSwitchTab('brand')">Branding</button>
  </div>
  <div class="studio-scroll">
    <div id="studioCases"></div>
    <div id="studioBrand" style="display:none"></div>
  </div>
  <div class="studio-io">
    <button data-studio="1" onclick="document.getElementById('studioImpX').click()">\u2191 Import .xlsx</button>
    <input id="studioImpX" type="file" accept=".xlsx" data-studio="1" onchange="studioImportXlsx(event)" style="display:none">
    <button data-studio="1" onclick="studioExportXlsx()">\u2193 Export .xlsx</button>
  </div>
</div>
<div id="studioConsole" class="studio-console" data-studio="1"></div>
"""

ENGINE_JS = r"""
/* ==== Static Chat Generator — engine bolted onto Claudia DOM ==== */
const VERSION={tool:"2.0.0",uiSkin:"claudia-real-dom",a2uiCatalog:"v0.9"};
const RESP_TYPES=['markdown','table','buttons','a2ui'];
// Agen AI we provide out of the box (from the real Claudia capture). Fixed set of 3;
// names are editable in the studio, identity is by id (users cannot add/remove).
const PROVIDED_AGENTS=[
  {id:"browser-use",     name:"Browser Use Agent"},
  {id:"code-interpreter",name:"Code Interpreter Agent"},
  {id:"gl-calendly",     name:"GL Calendly Agent"}
];
const DEFAULT_BRAND={
  // The conversation list IS the left sidebar; active -> top bar + highlighted sidebar row.
  conversations:[
    {id:"c1",title:"Pengajuan Cuti & Pertanyaan HR"},
    {id:"c2",title:"Table Generation Request"},
    {id:"c3",title:"Jadwal Kosong Mahesa Hari Ini"}
  ],
  activeConversation:"c1",
  agents:PROVIDED_AGENTS.map(a=>({...a})), // the 3 provided; all are listed in the composer
  activeAgent:"browser-use",                         // the radio-picked agent ("" = none -> LLM)
  llmName:"Claude Sonnet 4",                         // model used / shown when no Agen AI is selected
  proyekName:"",                                     // sidebar project name (seeded from the capture)
  proyekDesc:"- Help you submit requests, approve requests (manager only), and answer employee related inquiries.", // shown under the hero on screen 1
  profile:{name:"",email:"",picture:""},            // bottom-sidebar profile (seeded from the capture)
  shortcuts:[                                         // screen-1 suggestion chips (separate from cases)
    {id:"s1",text:"Saya mau mengajukan ketidakhadiran"},
    {id:"s2",text:"Saya mau mengajukan koreksi kehadiran"},
    {id:"s3",text:"Cek pengajuan yang harus saya setujui"},
    {id:"s4",text:"Saya mau mengajukan cuti tahunan"}
  ],
  prepSteps:[                                         // "Mempersiapkan Jawaban" loader steps
    {id:"p1",text:"Memahami pesan pengguna"},
    {id:"p2",text:"Mengambil data"}
  ],
  primaryHsl:"" // optional override "H S% L%"
};
function uid(){return Math.random().toString(36).slice(2,9);}
function defaultA2UI(){
  return JSON.stringify([{"version": "v0.9", "createSurface": {"surfaceId": "reschedule", "catalogId": "https://a2ui.org/catalogs/basic/catalog.json", "theme": {"primaryColor": "#16B364", "agentDisplayName": "GL Calendly Agent"}}}, {"version": "v0.9", "updateComponents": {"surfaceId": "reschedule", "components": [{"id": "root", "component": "Card", "child": "page"}, {"id": "page", "component": "Column", "children": ["title", "main", "footer"]}, {"id": "title", "component": "Text", "text": "Reschedule the meeting", "variant": "h1"}, {"id": "main", "component": "Row", "align": "start", "children": ["left", "right"]}, {"id": "left", "component": "Column", "children": ["infocard", "navrow", "dow", "w1", "w2", "w3", "w4", "w5"]}, {"id": "infocard", "component": "Card", "tone": "info", "child": "infocol"}, {"id": "infocol", "component": "Column", "children": ["mtitle", "inforow"]}, {"id": "mtitle", "component": "Text", "text": "PM Monthly with Pak On", "variant": "h2"}, {"id": "inforow", "component": "Row", "align": "start", "children": ["timecol", "guestcol"]}, {"id": "timecol", "component": "Column", "children": ["tl", "tv", "dl", "dv"]}, {"id": "tl", "component": "Text", "text": "Time", "variant": "caption"}, {"id": "tv", "component": "Text", "text": "Tuesday, June 2\n10:00am \u2013 10:30am"}, {"id": "dl", "component": "Text", "text": "Description", "variant": "caption"}, {"id": "dv", "component": "Text", "text": "\u2014"}, {"id": "guestcol", "component": "Column", "children": ["gl", "g1", "g2", "g3", "g4"]}, {"id": "gl", "component": "Text", "text": "4 Guest", "variant": "caption"}, {"id": "g1", "component": "Text", "text": "Maria Davis (organizer)"}, {"id": "g2", "component": "Text", "text": "On Lee"}, {"id": "g3", "component": "Text", "text": "Rizki Saputra"}, {"id": "g4", "component": "Text", "text": "Valerine Putri"}, {"id": "navrow", "component": "Row", "justify": "spaceBetween", "align": "center", "children": ["prev", "month", "next"]}, {"id": "prev", "component": "Button", "variant": "ghost", "child": "prevlbl", "action": {"event": {"name": "prev_month"}}}, {"id": "prevlbl", "component": "Text", "text": "\u2039"}, {"id": "month", "component": "Text", "text": "June 2026", "variant": "h2"}, {"id": "next", "component": "Button", "variant": "ghost", "child": "nextlbl", "action": {"event": {"name": "next_month"}}}, {"id": "nextlbl", "component": "Text", "text": "\u203a"}, {"id": "dow", "component": "Row", "children": ["dow0", "dow1", "dow2", "dow3", "dow4", "dow5", "dow6"]}, {"id": "dow0", "component": "Text", "text": "Sun", "variant": "cellhead"}, {"id": "dow1", "component": "Text", "text": "Mon", "variant": "cellhead"}, {"id": "dow2", "component": "Text", "text": "Tue", "variant": "cellhead"}, {"id": "dow3", "component": "Text", "text": "Wed", "variant": "cellhead"}, {"id": "dow4", "component": "Text", "text": "Thu", "variant": "cellhead"}, {"id": "dow5", "component": "Text", "text": "Fri", "variant": "cellhead"}, {"id": "dow6", "component": "Text", "text": "Sat", "variant": "cellhead"}, {"id": "d1_0l", "component": "Text", "text": "1"}, {"id": "d1_0", "component": "Button", "size": "cell", "variant": "ghost", "disabled": true, "child": "d1_0l"}, {"id": "d1_1l", "component": "Text", "text": "2"}, {"id": "d1_1", "component": "Button", "size": "cell", "variant": "primary", "child": "d1_1l", "action": {"event": {"name": "select_date", "context": {"date": 2}}}}, {"id": "d1_2l", "component": "Text", "text": "3"}, {"id": "d1_2", "component": "Button", "size": "cell", "variant": "outline", "child": "d1_2l", "action": {"event": {"name": "select_date", "context": {"date": 3}}}}, {"id": "d1_3l", "component": "Text", "text": "4"}, {"id": "d1_3", "component": "Button", "size": "cell", "variant": "outline", "child": "d1_3l", "action": {"event": {"name": "select_date", "context": {"date": 4}}}}, {"id": "d1_4l", "component": "Text", "text": "5"}, {"id": "d1_4", "component": "Button", "size": "cell", "variant": "outline", "child": "d1_4l", "action": {"event": {"name": "select_date", "context": {"date": 5}}}}, {"id": "d1_5l", "component": "Text", "text": "6"}, {"id": "d1_5", "component": "Button", "size": "cell", "variant": "outline", "child": "d1_5l", "action": {"event": {"name": "select_date", "context": {"date": 6}}}}, {"id": "d1_6l", "component": "Text", "text": "7"}, {"id": "d1_6", "component": "Button", "size": "cell", "variant": "ghost", "disabled": true, "child": "d1_6l"}, {"id": "w1", "component": "Row", "children": ["d1_0", "d1_1", "d1_2", "d1_3", "d1_4", "d1_5", "d1_6"]}, {"id": "d2_0l", "component": "Text", "text": "8"}, {"id": "d2_0", "component": "Button", "size": "cell", "variant": "ghost", "disabled": true, "child": "d2_0l"}, {"id": "d2_1l", "component": "Text", "text": "9"}, {"id": "d2_1", "component": "Button", "size": "cell", "variant": "outline", "child": "d2_1l", "action": {"event": {"name": "select_date", "context": {"date": 9}}}}, {"id": "d2_2l", "component": "Text", "text": "10"}, {"id": "d2_2", "component": "Button", "size": "cell", "variant": "outline", "child": "d2_2l", "action": {"event": {"name": "select_date", "context": {"date": 10}}}}, {"id": "d2_3l", "component": "Text", "text": "11"}, {"id": "d2_3", "component": "Button", "size": "cell", "variant": "outline", "child": "d2_3l", "action": {"event": {"name": "select_date", "context": {"date": 11}}}}, {"id": "d2_4l", "component": "Text", "text": "12"}, {"id": "d2_4", "component": "Button", "size": "cell", "variant": "outline", "child": "d2_4l", "action": {"event": {"name": "select_date", "context": {"date": 12}}}}, {"id": "d2_5l", "component": "Text", "text": "13"}, {"id": "d2_5", "component": "Button", "size": "cell", "variant": "outline", "child": "d2_5l", "action": {"event": {"name": "select_date", "context": {"date": 13}}}}, {"id": "d2_6l", "component": "Text", "text": "14"}, {"id": "d2_6", "component": "Button", "size": "cell", "variant": "ghost", "disabled": true, "child": "d2_6l"}, {"id": "w2", "component": "Row", "children": ["d2_0", "d2_1", "d2_2", "d2_3", "d2_4", "d2_5", "d2_6"]}, {"id": "d3_0l", "component": "Text", "text": "15"}, {"id": "d3_0", "component": "Button", "size": "cell", "variant": "ghost", "disabled": true, "child": "d3_0l"}, {"id": "d3_1l", "component": "Text", "text": "16"}, {"id": "d3_1", "component": "Button", "size": "cell", "variant": "outline", "child": "d3_1l", "action": {"event": {"name": "select_date", "context": {"date": 16}}}}, {"id": "d3_2l", "component": "Text", "text": "17"}, {"id": "d3_2", "component": "Button", "size": "cell", "variant": "outline", "child": "d3_2l", "action": {"event": {"name": "select_date", "context": {"date": 17}}}}, {"id": "d3_3l", "component": "Text", "text": "18"}, {"id": "d3_3", "component": "Button", "size": "cell", "variant": "outline", "child": "d3_3l", "action": {"event": {"name": "select_date", "context": {"date": 18}}}}, {"id": "d3_4l", "component": "Text", "text": "19"}, {"id": "d3_4", "component": "Button", "size": "cell", "variant": "outline", "child": "d3_4l", "action": {"event": {"name": "select_date", "context": {"date": 19}}}}, {"id": "d3_5l", "component": "Text", "text": "20"}, {"id": "d3_5", "component": "Button", "size": "cell", "variant": "outline", "child": "d3_5l", "action": {"event": {"name": "select_date", "context": {"date": 20}}}}, {"id": "d3_6l", "component": "Text", "text": "21"}, {"id": "d3_6", "component": "Button", "size": "cell", "variant": "ghost", "disabled": true, "child": "d3_6l"}, {"id": "w3", "component": "Row", "children": ["d3_0", "d3_1", "d3_2", "d3_3", "d3_4", "d3_5", "d3_6"]}, {"id": "d4_0l", "component": "Text", "text": "22"}, {"id": "d4_0", "component": "Button", "size": "cell", "variant": "ghost", "disabled": true, "child": "d4_0l"}, {"id": "d4_1l", "component": "Text", "text": "23"}, {"id": "d4_1", "component": "Button", "size": "cell", "variant": "outline", "child": "d4_1l", "action": {"event": {"name": "select_date", "context": {"date": 23}}}}, {"id": "d4_2l", "component": "Text", "text": "24"}, {"id": "d4_2", "component": "Button", "size": "cell", "variant": "outline", "child": "d4_2l", "action": {"event": {"name": "select_date", "context": {"date": 24}}}}, {"id": "d4_3l", "component": "Text", "text": "25"}, {"id": "d4_3", "component": "Button", "size": "cell", "variant": "outline", "child": "d4_3l", "action": {"event": {"name": "select_date", "context": {"date": 25}}}}, {"id": "d4_4l", "component": "Text", "text": "26"}, {"id": "d4_4", "component": "Button", "size": "cell", "variant": "outline", "child": "d4_4l", "action": {"event": {"name": "select_date", "context": {"date": 26}}}}, {"id": "d4_5l", "component": "Text", "text": "27"}, {"id": "d4_5", "component": "Button", "size": "cell", "variant": "outline", "child": "d4_5l", "action": {"event": {"name": "select_date", "context": {"date": 27}}}}, {"id": "d4_6l", "component": "Text", "text": "28"}, {"id": "d4_6", "component": "Button", "size": "cell", "variant": "ghost", "disabled": true, "child": "d4_6l"}, {"id": "w4", "component": "Row", "children": ["d4_0", "d4_1", "d4_2", "d4_3", "d4_4", "d4_5", "d4_6"]}, {"id": "d5_0l", "component": "Text", "text": "29"}, {"id": "d5_0", "component": "Button", "size": "cell", "variant": "ghost", "disabled": true, "child": "d5_0l"}, {"id": "d5_1l", "component": "Text", "text": "30"}, {"id": "d5_1", "component": "Button", "size": "cell", "variant": "outline", "child": "d5_1l", "action": {"event": {"name": "select_date", "context": {"date": 30}}}}, {"id": "d5_2", "component": "Text", "text": " ", "variant": "cellhead"}, {"id": "d5_3", "component": "Text", "text": " ", "variant": "cellhead"}, {"id": "d5_4", "component": "Text", "text": " ", "variant": "cellhead"}, {"id": "d5_5", "component": "Text", "text": " ", "variant": "cellhead"}, {"id": "d5_6", "component": "Text", "text": " ", "variant": "cellhead"}, {"id": "w5", "component": "Row", "children": ["d5_0", "d5_1", "d5_2", "d5_3", "d5_4", "d5_5", "d5_6"]}, {"id": "right", "component": "Column", "children": ["avail", "slots"]}, {"id": "avail", "component": "Text", "text": "AVAILABLE TIME", "variant": "caption"}, {"id": "t_1000l", "component": "Text", "text": "10:00"}, {"id": "t_1000", "component": "Button", "variant": "ghost", "disabled": true, "child": "t_1000l"}, {"id": "t_1030l", "component": "Text", "text": "10:30"}, {"id": "t_1030", "component": "Button", "variant": "outline", "child": "t_1030l", "action": {"event": {"name": "select_time", "context": {"time": "10:30"}}}}, {"id": "t_1100l", "component": "Text", "text": "11:00"}, {"id": "t_1100", "component": "Button", "variant": "primary", "child": "t_1100l", "action": {"event": {"name": "select_time", "context": {"time": "11:00"}}}}, {"id": "t_1130l", "component": "Text", "text": "11:30"}, {"id": "t_1130", "component": "Button", "variant": "outline", "child": "t_1130l", "action": {"event": {"name": "select_time", "context": {"time": "11:30"}}}}, {"id": "t_1200l", "component": "Text", "text": "12:00"}, {"id": "t_1200", "component": "Button", "variant": "outline", "child": "t_1200l", "action": {"event": {"name": "select_time", "context": {"time": "12:00"}}}}, {"id": "t_1230l", "component": "Text", "text": "12:30"}, {"id": "t_1230", "component": "Button", "variant": "outline", "child": "t_1230l", "action": {"event": {"name": "select_time", "context": {"time": "12:30"}}}}, {"id": "t_1300l", "component": "Text", "text": "13:00"}, {"id": "t_1300", "component": "Button", "variant": "outline", "child": "t_1300l", "action": {"event": {"name": "select_time", "context": {"time": "13:00"}}}}, {"id": "t_1330l", "component": "Text", "text": "13:30"}, {"id": "t_1330", "component": "Button", "variant": "outline", "child": "t_1330l", "action": {"event": {"name": "select_time", "context": {"time": "13:30"}}}}, {"id": "t_1500l", "component": "Text", "text": "15:00"}, {"id": "t_1500", "component": "Button", "variant": "outline", "child": "t_1500l", "action": {"event": {"name": "select_time", "context": {"time": "15:00"}}}}, {"id": "slots", "component": "Column", "children": ["t_1000", "t_1030", "t_1100", "t_1130", "t_1200", "t_1230", "t_1300", "t_1330", "t_1500"]}, {"id": "footer", "component": "Row", "justify": "end", "children": ["resched"]}, {"id": "resched", "component": "Button", "variant": "primary", "child": "reschedlbl", "action": {"event": {"name": "reschedule", "context": {"date": {"path": "/sel/date"}, "time": {"path": "/sel/time"}}}}}, {"id": "reschedlbl", "component": "Text", "text": "Reschedule"}]}}, {"version": "v0.9", "updateDataModel": {"surfaceId": "reschedule", "path": "/sel", "value": {"date": 2, "time": "11:00"}}}],null,2);
}
function freshBrand(src){
  const b=Object.assign({...DEFAULT_BRAND},src||{});
  // Agents: up to 3, each {id,name}. All are listed; brand.activeAgent picks the active one ("" = none -> LLM).
  let ag=Array.isArray(b.agents)?b.agents.filter(a=>a&&typeof a.name==='string'):null;
  if(!ag||!ag.length) ag=PROVIDED_AGENTS.map(a=>({...a}));
  b.agents=ag.map(a=>({id:a.id||uid(), name:a.name})).slice(0,3);
  if(b.activeAgent && !b.agents.some(a=>a.id===b.activeAgent)) b.activeAgent='';
  // Conversations: at least one (back-compat from a legacy conversationTitle string).
  let convs=Array.isArray(b.conversations)?b.conversations.filter(c=>c&&typeof c.title==='string'):[];
  if(!convs.length) convs=[{id:uid(),title:(src&&src.conversationTitle)||DEFAULT_BRAND.conversations[0].title}];
  b.conversations=convs.map(c=>({id:c.id||uid(),title:c.title}));
  if(!b.conversations.some(c=>c.id===b.activeConversation)) b.activeConversation=b.conversations[0].id;
  b.profile=Object.assign({name:"",email:"",picture:""}, b.profile||{});
  if(typeof b.proyekName!=='string') b.proyekName="";
  if(typeof b.proyekDesc!=='string') b.proyekDesc=DEFAULT_BRAND.proyekDesc;
  if(typeof b.llmName!=='string'||!b.llmName) b.llmName=DEFAULT_BRAND.llmName;
  let sc=Array.isArray(b.shortcuts)?b.shortcuts.filter(s=>s&&typeof s.text==='string'):null;
  if(!sc) sc=DEFAULT_BRAND.shortcuts;
  b.shortcuts=sc.map(s=>({id:s.id||uid(),text:s.text})).slice(0,4);
  let ps=Array.isArray(b.prepSteps)?b.prepSteps.filter(s=>s&&typeof s.text==='string'):null;
  if(!ps) ps=DEFAULT_BRAND.prepSteps;
  b.prepSteps=ps.map(s=>({id:s.id||uid(),text:s.text}));
  delete b.conversationTitle;
  return b;
}
function agentById(id){return studio.brand.agents.find(a=>a.id===id);}
function studioActiveAgent(){return agentById(studio.brand.activeAgent)||null;}  // the radio-picked agent ("" -> null -> LLM)
function activeAgentName(){
  const a=studioActiveAgent();
  return a?a.name:(studio.brand.llmName||'Assistant');   // none selected -> LLM
}
// Response-header avatar: green agent circle, or the LLM (Claude) icon when no agent.
function studioHeaderAvatar(){
  if(studioActiveAgent()) return AGENT_AVATAR;
  return `<div style="width:36px;height:36px;flex-shrink:0;display:flex;align-items:center;justify-content:center">${CLAUDE_ICON}</div>`;
}
// Resolve --primary to a concrete rgb() (some color props reject hsl(var(--primary))).
function studioPrimaryRGB(){
  const p=document.createElement('span'); p.style.color='hsl(var(--primary))'; p.style.display='none';
  document.body.appendChild(p); const c=getComputedStyle(p).color; p.remove();
  return c||'rgb(35,164,119)';
}
function nameInitials(name){
  const parts=String(name||'').trim().split(/\s+/).filter(Boolean);
  if(!parts.length) return '';
  const f=parts[0][0]||'', l=parts.length>1?parts[parts.length-1][0]:'';
  return (f+l).toUpperCase();
}
function activeConvTitle(){
  const c=studio.brand.conversations.find(c=>c.id===studio.brand.activeConversation);
  return c?c.title:'';
}
let studio={
  brand:freshBrand(),
  turns:[
    {id:uid(),prompt:"Berapa sisa cuti tahunan saya?",
     notes:"Saldo konsisten (kuota \u2212 terpakai = sisa). Tawarkan tindak lanjut. Jangan mengarang angka tanpa data karyawan.",
     blocks:[
       {id:uid(),type:"markdown",content:"Berikut ringkasan **cuti tahunan** Anda untuk 2026:"},
       {id:uid(),type:"table",content:"Komponen | Jumlah\nKuota tahunan | 12 hari\nSudah terpakai | 5 hari\nSisa | 7 hari"},
       {id:uid(),type:"markdown",content:"Ingin saya bantu membuat pengajuan cuti?"}
     ]},
    {id:uid(),prompt:"Jenis cuti apa saja yang tersedia?",type:"table",
     notes:"Sertakan semua jenis cuti aktif beserta kuota dan jalur persetujuan.",
     content:"Jenis Cuti | Kuota | Perlu Persetujuan\nCuti Tahunan | 12 hari/tahun | Atasan langsung\nCuti Sakit | Sesuai surat dokter | HR\nCuti Melahirkan | 90 hari | HR & Atasan\nCuti Penting | 2 hari/kejadian | Atasan langsung"},
    {id:uid(),prompt:"Saya mau mengajukan cuti tahunan",type:"a2ui",
     notes:"Render form pengajuan cuti. Aksi utama 'submit_leave_request'. Field 'alasan' wajib diisi.",
     content:defaultA2UI()},
    {id:uid(),prompt:"Apa yang bisa saya lakukan?",type:"buttons",
     notes:"Empat quick-reply sesuai intent utama Employee Assistant.",
     content:"Ajukan ketidakhadiran | submit_absence\nAjukan koreksi kehadiran | submit_attendance_correction\nCek pengajuan untuk disetujui | view_pending_approvals\nAjukan cuti tahunan | submit_annual_leave"},
    {id:uid(),prompt:"Tunjukkan semua gaya format yang didukung",type:"markdown",
     notes:"Contoh lengkap: heading, bold/italic/strikethrough, inline code, list, list bernomor, tabel, quote, divider, link, dan code block.",
     content:"# Heading 1\n## Heading 2\n### Heading 3\n\n**Bold** menegaskan poin penting, *italic* untuk penekanan halus, ~~strikethrough~~ menandai yang usang, dan `inline code` seperti `user_id` atau `print()`.\n\n> Blockquote untuk catatan atau peringatan penting.\n\n- Item pertama\n- Item kedua\n- Item ketiga\n\n1. Langkah satu\n2. Langkah dua\n3. Langkah tiga\n\n| Fitur | Contoh | Kegunaan |\n| --- | --- | --- |\n| Bold | Penting | Penekanan |\n| Code | console.log() | Pemrograman |\n| Tabel | Baris & kolom | Data terstruktur |\n\n---\n\nLihat [dokumentasi](https://example.com) untuk detail lengkap.\n\n```js\nconsole.log(\"Halo, dunia\");\n```"}
  ]
};

/* ---------- editor ---------- */
function studioRender(){
  const w=document.getElementById('studioCases');
  w.innerHTML=studio.turns.map((t,i)=>studioTurn(t,i)).join('')+
    `<button class="studio-add" onclick="studioAdd()">+ Add case</button>`;
  studioRenderBrand();
}
// A response is a list of typed blocks that play in order (e.g. text -> table -> text).
// Migrate legacy {type,content} turns to a single block on first access.
function turnBlocks(t){
  if(!Array.isArray(t.blocks)){ t.blocks=[{id:uid(),type:t.type||'markdown',content:t.content||''}]; delete t.type; delete t.content; }
  if(!t.blocks.length) t.blocks.push({id:uid(),type:'markdown',content:''});
  return t.blocks;
}
const BLOCK_PH={markdown:"Markdown. **bold**, lists, `code`, tables.",table:"One row per line, cells split by | . First line = header.",buttons:"One button per line.  Label | optional_action_name",a2ui:"A2UI v0.9 envelopes as JSON array (or JSONL)."};
function studioTurn(t,i){
  const blocks=turnBlocks(t);
  const blockHTML=blocks.map(b=>{
    const pills=RESP_TYPES.map(rt=>{
      const lbl={markdown:'Markdown',table:'Table',buttons:'Buttons',a2ui:'A2UI'}[rt];
      return `<button data-studio="1" class="${b.type===rt?'active':''}" onclick="studioBlockType('${t.id}','${b.id}','${rt}')">${lbl}</button>`;
    }).join('');
    const code=(b.type==='a2ui'||b.type==='table'||b.type==='buttons')?'code':'';
    return `<div class="studio-block">
      <div class="studio-block-h"><div class="studio-pills">${pills}</div>
        <button class="ic" data-studio="1" title="Up" onclick="studioBlockMove('${t.id}','${b.id}',-1)">\u2191</button>
        <button class="ic" data-studio="1" title="Down" onclick="studioBlockMove('${t.id}','${b.id}',1)">\u2193</button>
        ${blocks.length>1?`<button class="ic" data-studio="1" title="Remove block" onclick="studioBlockDel('${t.id}','${b.id}')">\u2715</button>`:''}
      </div>
      <textarea data-studio="1" class="${code}" oninput="studioBlockUpd('${t.id}','${b.id}',this.value)" placeholder="${BLOCK_PH[b.type]}">${esc(b.content)}</textarea>
    </div>`;
  }).join('');
  return `
  <div class="studio-turn">
    <div class="studio-turn-h">
      <div class="num">${i+1}</div><div class="t">Case ${i+1}</div>
      <button class="ic" data-studio="1" title="Up" onclick="studioMove('${t.id}',-1)">\u2191</button>
      <button class="ic" data-studio="1" title="Down" onclick="studioMove('${t.id}',1)">\u2193</button>
      <button class="ic" data-studio="1" title="Delete" onclick="studioDel('${t.id}')">\u2715</button>
    </div>
    <div class="studio-turn-b">
      <div class="studio-fld"><label>User prompt</label><textarea data-studio="1" oninput="studioUpd('${t.id}','prompt',this.value)">${esc(t.prompt)}</textarea></div>
      <div class="studio-fld"><label>Expected response (blocks play in order)</label>
        ${blockHTML}
        <button class="studio-add-block" onclick="studioBlockAdd('${t.id}')">+ Add block</button>
      </div>
      <div class="studio-fld"><label>Notes / expected behavior (for devs)</label><textarea data-studio="1" oninput="studioUpd('${t.id}','notes',this.value)">${esc(t.notes||'')}</textarea></div>
    </div>
  </div>`;
}
function studioBlockUpd(tid,bid,v){const t=studio.turns.find(x=>x.id===tid);if(!t)return;const b=turnBlocks(t).find(x=>x.id===bid);if(b)b.content=v;}
function studioBlockType(tid,bid,ty){const t=studio.turns.find(x=>x.id===tid);if(!t)return;const b=turnBlocks(t).find(x=>x.id===bid);if(b){b.type=ty;studioRender();}}
function studioBlockAdd(tid){const t=studio.turns.find(x=>x.id===tid);if(!t)return;turnBlocks(t).push({id:uid(),type:'markdown',content:''});studioRender();}
function studioBlockDel(tid,bid){const t=studio.turns.find(x=>x.id===tid);if(!t)return;t.blocks=turnBlocks(t).filter(x=>x.id!==bid);studioRender();}
function studioBlockMove(tid,bid,d){const t=studio.turns.find(x=>x.id===tid);if(!t)return;const bs=turnBlocks(t);const i=bs.findIndex(x=>x.id===bid),j=i+d;if(j<0||j>=bs.length)return;[bs[i],bs[j]]=[bs[j],bs[i]];studioRender();}
function studioAgentsHTML(){
  // All listed agents are shown in the composer. Radio = the active one (click again
  // to deselect -> no active agent -> LLM). Editable name + remove. Add up to 3.
  const rows=studio.brand.agents.map(a=>{
    const active=studio.brand.activeAgent===a.id;
    return `<div class="studio-agent${active?' active':''}">`
    + `<input type="radio" name="studioActiveAgent" ${active?'checked':''} title="Set active (click again to deselect → LLM)" onclick="studioAgentActivate('${a.id}')">`
    + `<input class="nm-edit" value="${esc(a.name)}" title="Rename agent" oninput="studioAgentRename('${a.id}',this.value)">`
    + `<button class="rm" title="Remove agent" onclick="studioAgentRemove('${a.id}')">×</button>`
    + `</div>`;
  }).join('');
  return rows
    + (studio.brand.agents.length>=3
        ? `<div style="font-size:11px;color:#7b8094;margin-top:4px">Maximum 3 Agen AI.</div>`
        : `<div class="studio-agent-add"><input id="studioAgentNew" placeholder="Add an Agen AI…" onkeydown="if(event.key==='Enter'){event.preventDefault();studioAgentAdd();}"><button onclick="studioAgentAdd()">Add</button></div>`);
}
function studioConvsHTML(){
  const b=studio.brand;
  const rows=b.conversations.map(c=>{
    const active=b.activeConversation===c.id;
    return `<div class="studio-agent${active?' active':''}">`
      + `<input type="radio" name="studioActiveConv" ${active?'checked':''} title="Set as active conversation" onchange="studioConvActivate('${c.id}')">`
      + `<input class="nm-edit" value="${esc(c.title)}" title="Rename conversation" oninput="studioConvRename('${c.id}',this.value)">`
      + (b.conversations.length>1?`<button class="rm" title="Remove conversation" onclick="studioConvRemove('${c.id}')">×</button>`:'')
      + `</div>`;
  }).join('');
  return rows
    + `<div class="studio-agent-add"><input id="studioConvNew" placeholder="Add a conversation title…" onkeydown="if(event.key==='Enter'){event.preventDefault();studioConvAdd();}"><button onclick="studioConvAdd()">Add</button></div>`;
}
function studioRenderBrand(){
  const b=studio.brand;
  document.getElementById('studioBrand').innerHTML=`
    <div class="studio-fld"><label>Conversations (◉ active = top-bar title + selected sidebar item)</label>${studioConvsHTML()}</div>
    <div class="studio-fld"><label>Agen AI (all are listed; ◉ = active on each answer; click again to deselect → LLM; max 3)</label>${studioAgentsHTML()}</div>
    <div class="studio-fld"><label>LLM model (used when no Agen AI is selected)</label><input data-studio="1" value="${esc(b.llmName||'')}" oninput="studioBrand('llmName',this.value)"></div>
    <div class="studio-fld"><label>Proyek name (sidebar project)</label><input data-studio="1" value="${esc(b.proyekName||'')}" oninput="studioBrand('proyekName',this.value)"></div>
    <div class="studio-fld"><label>Proyek description (under the hero on screen 1)</label><textarea data-studio="1" oninput="studioBrand('proyekDesc',this.value)">${esc(b.proyekDesc||'')}</textarea></div>
    <div class="studio-fld"><label>Shortcuts (suggestion chips on screen 1)</label>${studioShortcutsHTML()}</div>
    <div class="studio-fld"><label>Preparation steps (shown one by one before each answer)</label>${studioPrepHTML()}</div>
    <div class="studio-fld"><label>Profile name (bottom sidebar)</label><input data-studio="1" value="${esc(b.profile.name||'')}" oninput="studioProfile('name',this.value)"></div>
    <div class="studio-fld"><label>Profile email</label><input data-studio="1" value="${esc(b.profile.email||'')}" oninput="studioProfile('email',this.value)"></div>
    <div class="studio-fld"><label>Profile picture URL (blank = initials)</label><input data-studio="1" value="${esc(b.profile.picture||'')}" placeholder="https://… (leave empty to use initials)" oninput="studioProfile('picture',this.value)"></div>
    <div class="studio-fld"><label>Override primary (HSL triplet, e.g. <code>198 100% 31%</code>)</label><input data-studio="1" value="${esc(b.primaryHsl||'')}" placeholder="leave empty to keep Claudia's --primary" oninput="studioBrand('primaryHsl',this.value)"></div>
    <div style="font-size:11px;color:#7b8094;line-height:1.5;margin-top:6px">The chat chrome is your real product DOM/CSS. To match a redesign, replace <code>index.html</code> with a fresh MHTML build (see SPEC.md).</div>
  `;
}
function studioSwitchTab(t){
  document.getElementById('studioTabCases').classList.toggle('active',t==='cases');
  document.getElementById('studioTabBrand').classList.toggle('active',t==='brand');
  document.getElementById('studioCases').style.display=t==='cases'?'':'none';
  document.getElementById('studioBrand').style.display=t==='brand'?'':'none';
}
function studioUpd(id,k,v){const t=studio.turns.find(x=>x.id===id);if(t)t[k]=v;}
function studioAdd(){studio.turns.push({id:uid(),prompt:"",blocks:[{id:uid(),type:"markdown",content:""}],notes:""});studioRender();}
function studioDel(id){studio.turns=studio.turns.filter(x=>x.id!==id);studioRender();}
function studioMove(id,d){const i=studio.turns.findIndex(x=>x.id===id),j=i+d;if(j<0||j>=studio.turns.length)return;[studio.turns[i],studio.turns[j]]=[studio.turns[j],studio.turns[i]];studioRender();}
function studioBrand(k,v){studio.brand[k]=v;studioApplyBrand();}
function studioAgentActivate(id){
  // Radio behaviour with deselect: clicking the active agent clears it (-> LLM).
  studio.brand.activeAgent = (studio.brand.activeAgent===id) ? '' : id;
  studioRenderBrand(); studioRenderAgentBar();
}
function studioAgentRename(id,name){
  const a=agentById(id); if(a) a.name=name;
  studioRenderAgentBar(); // not the panel (would steal input focus)
}
function studioAgentRemove(id){
  studio.brand.agents=studio.brand.agents.filter(a=>a.id!==id);
  if(studio.brand.activeAgent===id) studio.brand.activeAgent='';
  studioRenderBrand(); studioRenderAgentBar();
}
function studioAgentAdd(){
  if(studio.brand.agents.length>=3) return;
  const inp=document.getElementById('studioAgentNew');
  const name=(inp&&inp.value||'').trim(); if(!name) return;
  studio.brand.agents.push({id:uid(),name:name});
  studioRenderBrand(); studioRenderAgentBar();
}
// ----- Conversations (titles): active drives top bar + selected sidebar row -----
function studioConvActivate(id){ studio.brand.activeConversation=id; studioRenderBrand(); studioApplyConv(); }
function studioConvRename(id,title){
  const c=studio.brand.conversations.find(c=>c.id===id); if(c) c.title=title;
  studioApplyConv(); // not the panel (keep input focus)
}
function studioConvRemove(id){
  const b=studio.brand; if(b.conversations.length<=1) return;
  b.conversations=b.conversations.filter(c=>c.id!==id);
  if(!b.conversations.some(c=>c.id===b.activeConversation)) b.activeConversation=b.conversations[0].id;
  studioRenderBrand(); studioApplyConv();
}
function studioConvAdd(){
  const inp=document.getElementById('studioConvNew');
  const title=(inp&&inp.value||'').trim(); if(!title) return;
  const id=uid(); studio.brand.conversations.push({id,title}); studio.brand.activeConversation=id;
  studioRenderBrand(); studioApplyConv();
}
// ----- Shortcuts (screen-1 suggestion chips) -----
function studioShortcutsHTML(){
  const rows=studio.brand.shortcuts.map(s=>
    `<div class="studio-agent">`
    + `<input class="nm-edit" value="${esc(s.text)}" title="Edit shortcut" oninput="studioShortcutRename('${s.id}',this.value)">`
    + `<button class="rm" title="Remove shortcut" onclick="studioShortcutRemove('${s.id}')">×</button>`
    + `</div>`).join('');
  const full=studio.brand.shortcuts.length>=SHORTCUT_MAX;
  return rows
    + (full
        ? `<div style="font-size:11px;color:#7b8094;margin-top:4px">Maximum ${SHORTCUT_MAX} shortcuts.</div>`
        : `<div class="studio-agent-add"><input id="studioShortcutNew" placeholder="Add a shortcut…" onkeydown="if(event.key==='Enter'){event.preventDefault();studioShortcutAdd();}"><button onclick="studioShortcutAdd()">Add</button></div>`);
}
function studioShortcutRename(id,text){const s=studio.brand.shortcuts.find(s=>s.id===id); if(s) s.text=text; studioRenderFirstScreen();}
function studioShortcutRemove(id){studio.brand.shortcuts=studio.brand.shortcuts.filter(s=>s.id!==id); studioRenderBrand(); studioRenderFirstScreen();}
function studioShortcutAdd(){
  if(studio.brand.shortcuts.length>=SHORTCUT_MAX) return;
  const inp=document.getElementById('studioShortcutNew');
  const text=(inp&&inp.value||'').trim(); if(!text) return;
  studio.brand.shortcuts.push({id:uid(),text}); studioRenderBrand(); studioRenderFirstScreen();
}
// ----- Preparation steps ("Mempersiapkan Jawaban" loader) -----
function studioPrepHTML(){
  const rows=studio.brand.prepSteps.map(s=>
    `<div class="studio-agent">`
    + `<input class="nm-edit" value="${esc(s.text)}" title="Edit step" oninput="studioPrepRename('${s.id}',this.value)">`
    + `<button class="rm" title="Remove step" onclick="studioPrepRemove('${s.id}')">×</button>`
    + `</div>`).join('');
  return rows
    + `<div class="studio-agent-add"><input id="studioPrepNew" placeholder="Add a preparation step…" onkeydown="if(event.key==='Enter'){event.preventDefault();studioPrepAdd();}"><button onclick="studioPrepAdd()">Add</button></div>`;
}
function studioPrepRename(id,text){const s=studio.brand.prepSteps.find(s=>s.id===id); if(s) s.text=text;}
function studioPrepRemove(id){studio.brand.prepSteps=studio.brand.prepSteps.filter(s=>s.id!==id); studioRenderBrand();}
function studioPrepAdd(){
  const inp=document.getElementById('studioPrepNew');
  const text=(inp&&inp.value||'').trim(); if(!text) return;
  studio.brand.prepSteps.push({id:uid(),text}); studioRenderBrand();
}
// Locate the real Claudia "Agen AI:" composer row by its label paragraph.
function studioAgentBarRow(){
  const p=[...document.querySelectorAll('p')].find(el=>/^\s*Agen AI:/.test(el.textContent||''));
  return p?{row:p.parentElement,label:p}:null;
}
const AGENT_BTN_BASE='font-medium transition-color flex cursor-pointer items-center justify-center space-x-2 truncate whitespace-nowrap rounded border px-3 py-2 text-xs focus:outline-none';
const AGENT_BTN_OFF=AGENT_BTN_BASE+' border-border bg-background text-foreground hover:bg-card-hover focus:bg-card-hover active:bg-card-hover';
const AGENT_BTN_ON=AGENT_BTN_BASE+' border-primary-subtle bg-primary-subtle text-primary-subtle-foreground';
// Render the selected agents as buttons in the composer row (active highlighted),
// followed by the "Agen Lainnya" button.
function studioLLMSelectorHTML(){
  // In-box model selector (next to "+"), styled like the real product (borderless).
  return `<button type="button" class="group flex h-7 max-w-fit items-center justify-between gap-1 rounded-md border-none bg-background p-1 text-xs font-normal text-foreground hover:bg-background-hover">`
    + `<span class="flex items-center gap-2">${CLAUDE_ICON}<span>${esc(studio.brand.llmName||'')}</span></span>`
    + lucide('<path d="m6 9 6 6 6-6"></path>','lucide-chevron-down ml-1 h-4 w-4 shrink-0 text-foreground')
    + `</button>`;
}
// Place the LLM model selector inside the prompt box, right after the "+" button.
function studioRenderLLM(){
  const tb=document.querySelector('[data-llm-toolbar]'); if(!tb) return;
  const old=tb.querySelector(':scope > [data-llm-sel]'); if(old) old.remove();
  if(studioActiveAgent()) return;            // an agent is active -> no LLM selector
  const wrap=document.createElement('div'); wrap.setAttribute('data-llm-sel','1');
  wrap.className='flex items-center'; wrap.innerHTML=studioLLMSelectorHTML();
  const first=tb.firstElementChild;          // the "+" button group
  if(first) tb.insertBefore(wrap, first.nextSibling); else tb.appendChild(wrap);
}
function studioRenderAgentBar(){
  const found=studioAgentBarRow(); if(!found) return;
  const {row,label}=found;
  [...row.children].forEach(c=>{ if(c!==label) c.remove(); });
  const agents=studio.brand.agents;
  // All listed agents are shown; the active (radio-picked) one is highlighted.
  // (The LLM model lives inside the prompt box, not here.)
  agents.forEach(a=>{
    const active=studio.brand.activeAgent===a.id;
    const wrap=document.createElement('div'); wrap.className='lg:w-1/5 lg:overflow-x-hidden';
    wrap.innerHTML=`<label class="${active?AGENT_BTN_ON:AGENT_BTN_OFF}" tabindex="0"><div class="">${AGENT_ICON_SVG}</div><p class="truncate">${esc(a.name)}</p></label>`;
    wrap.firstChild.addEventListener('click',()=>studioAgentActivate(a.id));
    row.appendChild(wrap);
  });
  // "Agen Lainnya" only when the full set of 3 agents is present.
  if(agents.length>=3){
    const more=document.createElement('div'); more.className='lg:w-1/5 lg:overflow-x-hidden';
    more.innerHTML=`<label class="${AGENT_BTN_OFF}" tabindex="0"><div class="">${AGENT_GRID_SVG}</div><p class="truncate font-semibold">Agen Lainnya</p></label>`;
    more.firstChild.addEventListener('click',()=>{document.getElementById('studioDrawer').classList.add('open');studioSwitchTab('brand');studioRenderBrand();});
    row.appendChild(more);
  }
  studioRenderLLM();   // keep the in-box LLM selector in sync (hidden when an agent is active)
}
// Rebuild the left sidebar conversation list from brand.conversations.
// One row per title (cloned from a captured row template); active row highlighted.
function studioRenderConvList(){
  const cont=document.querySelector('[data-convo-list]'); if(!cont) return;
  const rows=[...cont.children].filter(c=>c.tagName==='A');
  if(!cont._convTpl){ if(!rows.length) return; cont._convTpl=rows[0].cloneNode(true); }
  rows.forEach(r=>r.remove());
  // The active conversation is the current chat. On the first (new-chat) screen it is
  // NOT in the sidebar; on the conversation screen it is prepended on top (+1, highlighted).
  const activeId=studio.brand.activeConversation;
  let list=studio.brand.conversations.slice();
  if(studioScreen==='convo'){
    const ai=list.findIndex(c=>c.id===activeId);
    if(ai>=0){ const [a]=list.splice(ai,1); list.unshift(a); }   // move active to top
  } else {
    list=list.filter(c=>c.id!==activeId);                        // first screen: hide active
  }
  list.forEach(c=>{
    const a=cont._convTpl.cloneNode(true);
    const active=(c.id===activeId) && studioScreen==='convo';
    a.classList.toggle('bg-secondary', active);
    a.removeAttribute('href');
    const btn=a.querySelector('button'); if(btn) btn.textContent=c.title; // first button = title
    // Kebab (⋮) menu: shown on the active row; hover-only otherwise.
    const kbtn=a.querySelector('svg.lucide-ellipsis-vertical') ? a.querySelector('svg.lucide-ellipsis-vertical').closest('button') : null;
    if(kbtn){ kbtn.classList.toggle('opacity-100', active); kbtn.classList.toggle('opacity-0', !active); }
    a.addEventListener('click',e=>{e.preventDefault();studioConvActivate(c.id);});
    cont.appendChild(a);
  });
}
// Active conversation title -> top bar; full list -> sidebar.
function studioApplyConv(){
  const t=document.querySelector('[data-convo-title]'); if(t) t.textContent=activeConvTitle();
  studioRenderConvList();
}
// Seed proyek name + profile from the captured DOM once, so defaults match the build.
function studioSeedFromDOM(){
  const b=studio.brand;
  if(!b.proyekName){const el=document.querySelector('[data-proyek-name]'); if(el) b.proyekName=(el.textContent||'').trim();}
  if(!b.profile.name){const el=document.querySelector('[data-profile-name]'); if(el) b.profile.name=(el.textContent||'').trim();}
  if(!b.profile.email){const el=document.querySelector('[data-profile-email]'); if(el) b.profile.email=(el.textContent||'').trim();}
}
function studioProfile(k,v){studio.brand.profile[k]=v;studioApplyProfile();}
function studioApplyProfile(){
  const b=studio.brand;
  const pn=document.querySelector('[data-proyek-name]'); if(pn) pn.textContent=b.proyekName||'';
  const nm=document.querySelector('[data-profile-name]'); if(nm) nm.textContent=b.profile.name||'';
  const em=document.querySelector('[data-profile-email]'); if(em) em.textContent=b.profile.email||'';
  const av=document.querySelector('[data-profile-avatar]');
  if(av){
    av.innerHTML=b.profile.picture
      ? `<img class="aspect-square h-full w-full object-cover" src="${esc(b.profile.picture)}" alt="">`
      : `<span class="flex h-full w-full items-center justify-center rounded-full bg-secondary">${esc(nameInitials(b.profile.name))}</span>`;
  }
}
/* ---------- first screen (new-chat landing) ---------- */
let studioScreen='first';
const SHORTCUT_MAX=4;
const FS_BOT_ICON=lucide('<path d="M12 8V4H8"></path><rect width="16" height="12" x="4" y="8" rx="2"></rect><path d="M2 14h2"></path><path d="M20 14h2"></path><path d="M15 13v2"></path><path d="M9 13v2"></path>','lucide-bot');
const FS_ARROW_ICON=lucide('<path d="M7 7h10v10"></path><path d="M7 17 17 7"></path>','lucide-arrow-up-right order-2 size-6 flex-shrink-0 text-accent transition-transform duration-300 group-hover:-translate-y-1 group-hover:translate-x-1 lg:order-1 lg:self-end');
function studioMountFirstScreen(){
  const area=document.querySelector('[data-main-card]')||document.querySelector('[data-chat-area]'); if(!area) return null;
  let ov=area.querySelector('[data-first-screen]');
  if(!ov){
    ov=document.createElement('div'); ov.className='fs-screen'; ov.setAttribute('data-first-screen','1');
    ov.innerHTML=`<div class="fs-bg" aria-hidden="true"><div class="fs-grid"></div><div class="fs-glow"></div><div class="fs-tracers"></div></div>
    <div class="fs-inner">
      <div class="fs-greet">Halo <strong class="fs-name"></strong>, ada yang bisa saya bantu?</div>
      <p class="fs-sub"><span class="fs-proyek">${FS_BOT_ICON}<span class="fs-proyek-nm"></span></span><span class="fs-desc"></span></p>
      <div class="fs-composer-slot"></div>
      <div class="fs-chips"></div>
    </div>`;
    area.appendChild(ov);
  }
  return ov;
}
// Animated green tracers that draw along grid lines, then fade — random position/length.
let studioTracerTimer=null, studioTracerSeq=0;
function studioSpawnTracer(){
  const layer=document.querySelector('[data-first-screen] .fs-tracers'); if(!layer) return;
  const W=layer.clientWidth, H=layer.clientHeight, G=100; if(!W||!H) return;
  // L-shaped path: start, turn at a grid corner, continue along the other axis.
  const cx=Math.floor(Math.random()*(W/G+1))*G, cy=Math.floor(Math.random()*(H/G+1))*G; // corner
  const a=(1+Math.floor(Math.random()*2))*G, b=(1+Math.floor(Math.random()*2))*G;
  const sx=Math.random()<0.5?-1:1, sy=Math.random()<0.5?-1:1;
  let p1,p3;
  if(Math.random()<0.5){ p1=[cx-sx*a,cy]; p3=[cx,cy+sy*b]; }   // horizontal then vertical
  else { p1=[cx,cy-sy*b]; p3=[cx+sx*a,cy]; }                   // vertical then horizontal
  const xs=[p1[0],cx,p3[0]], ys=[p1[1],cy,p3[1]];
  const minX=Math.min.apply(null,xs), minY=Math.min.apply(null,ys);
  const w=Math.max.apply(null,xs)-minX||2, h=Math.max.apply(null,ys)-minY||2;
  const pts=[p1,[cx,cy],p3].map(p=>(p[0]-minX)+','+(p[1]-minY)).join(' ');
  const gid='fsg'+(studioTracerSeq++);
  const x1=p1[0]-minX, y1=p1[1]-minY, x2=p3[0]-minX, y2=p3[1]-minY; // gradient runs end-to-end
  const el=document.createElement('div'); el.className='fs-tracer';
  el.style.left=minX+'px'; el.style.top=minY+'px'; el.style.setProperty('--len', a+b);
  el.innerHTML=`<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="overflow:visible">`
    + `<defs><linearGradient id="${gid}" gradientUnits="userSpaceOnUse" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}">`
    + `<stop offset="0" stop-color="#00c983" stop-opacity="0"></stop><stop offset="0.25" stop-color="#00c983"></stop>`
    + `<stop offset="0.75" stop-color="#00c983"></stop><stop offset="1" stop-color="#00c983" stop-opacity="0"></stop></linearGradient></defs>`
    + `<polyline points="${pts}" stroke="url(#${gid})"></polyline></svg>`;
  layer.appendChild(el);
  setTimeout(()=>el.remove(),3000);
}
function studioTracerStart(){
  studioTracerStop();
  const tick=()=>{ if(studioScreen!=='first'){studioTracerTimer=null;return;} studioSpawnTracer(); studioTracerTimer=setTimeout(tick, 600+Math.random()*1600); };
  studioTracerTimer=setTimeout(tick, 300);
}
function studioTracerStop(){ if(studioTracerTimer){clearTimeout(studioTracerTimer); studioTracerTimer=null;} }
// Move the real composer block (Agen AI row + input) into the landing, or back home.
function studioComposerToLanding(){
  const blk=document.querySelector('[data-composer-block]');
  const slot=document.querySelector('[data-first-screen] .fs-composer-slot');
  if(blk&&slot&&blk.parentElement!==slot){
    if(!blk._home) blk._home={parent:blk.parentElement, next:blk.nextSibling};
    slot.appendChild(blk);
  }
}
function studioComposerHome(){
  const blk=document.querySelector('[data-composer-block]');
  if(blk&&blk._home&&blk.parentElement!==blk._home.parent){ blk._home.parent.insertBefore(blk, blk._home.next); }
}
function studioRenderFirstScreen(){
  const ov=studioMountFirstScreen(); if(!ov) return;
  const b=studio.brand;
  ov.querySelector('.fs-name').textContent=b.profile.name||'';
  ov.querySelector('.fs-proyek-nm').textContent=b.proyekName||'';
  ov.querySelector('.fs-desc').textContent=b.proyekDesc||'';
  const chips=ov.querySelector('.fs-chips'); chips.innerHTML='';
  b.shortcuts.slice(0,SHORTCUT_MAX).forEach(s=>{
    const card=document.createElement('div');
    card.className='rounded-lg border bg-card text-card-foreground shadow-sm transition-colors duration-300 hover:bg-card-hover group flex-shrink-0 cursor-pointer p-4 w-72 lg:w-40 text-left';
    card.setAttribute('tabindex','0');
    card.innerHTML=`<div class="flex flex-row gap-2 lg:flex-col lg:gap-6"><p class="text-sm order-1 line-clamp-2 grow opacity-secondary group-hover:opacity-primary lg:order-2 lg:line-clamp-4">${esc(s.text)}</p>${FS_ARROW_ICON}</div>`;
    card.addEventListener('click',()=>studioPlay());
    chips.appendChild(card);
  });
}
function studioShowFirstScreen(){
  studioScreen='first';
  const ov=studioMountFirstScreen(); if(ov) ov.style.display='';
  const t=document.querySelector('[data-convo-title]'); if(t) t.textContent='Percakapan Baru';
  const sh=document.querySelector('[data-share-action]'); if(sh) sh.style.display='none';
  const tb=document.querySelector('[data-topbar]'); if(tb) tb.classList.add('fs-topbar-up'); // sit above the grid, transparent
  studioRenderConvList();            // re-render: no active row, kebabs hover-only
  studioRenderFirstScreen();
  studioComposerToLanding();
  studioTracerStart();
}
function studioShowConvo(){
  studioScreen='convo';
  studioTracerStop();
  studioComposerHome();
  const ov=document.querySelector('[data-first-screen]'); if(ov) ov.style.display='none';
  const sh=document.querySelector('[data-share-action]'); if(sh) sh.style.display='';
  const tb=document.querySelector('[data-topbar]'); if(tb) tb.classList.remove('fs-topbar-up');
  studioApplyConv();
}
function studioApplyBrand(){
  if(studioScreen==='first'){ studioShowFirstScreen(); } else { studioApplyConv(); }
  studioApplyProfile();
  if(studio.brand.primaryHsl){
    document.documentElement.style.setProperty('--primary', studio.brand.primaryHsl);
  } else {
    document.documentElement.style.removeProperty('--primary');
  }
  studioRenderAgentBar();
  studioRenderLLM();
}
function studioToggleDrawer(){document.getElementById('studioDrawer').classList.toggle('open');}
function studioToggleRec(){document.documentElement.classList.toggle('studio-recording');}
function studioToggleConsole(){document.getElementById('studioConsole').classList.toggle('show');}

/* ---------- escape + markdown (compact; prose styles it) ---------- */
function esc(s){return (s==null?'':String(s)).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function escAttr(s){return esc(s).replace(/'/g,"&#39;");}
function inlineMD(s){
  return esc(s)
    .replace(/`([^`]+)`/g,'<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*]+)\*/g,'$1<em>$2</em>')
    .replace(/~~([^~]+)~~/g,'<del>$1</del>')
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
}
function renderMarkdown(src){
  const lines=String(src).split('\n');let html='',i=0;
  while(i<lines.length){
    let ln=lines[i];
    if(/^```/.test(ln)){let code='';i++;while(i<lines.length&&!/^```/.test(lines[i])){code+=lines[i]+'\n';i++;}html+=`<pre><code>${esc(code.replace(/\n$/,''))}</code></pre>`;i++;continue;}
    if(/^\s*\|?.+\|.+/.test(ln)&&lines[i+1]!==undefined&&/^\s*\|?[\s:|-]+\|?[\s:|-]*$/.test(lines[i+1])){
      const head=splitRow(ln);i+=2;const rows=[];
      while(i<lines.length&&/\|/.test(lines[i])&&lines[i].trim()!==''){rows.push(splitRow(lines[i]));i++;}
      html+=tableHTML(head,rows);continue;
    }
    if(/^#{1,3}\s/.test(ln)){const lvl=ln.match(/^#+/)[0].length;html+=`<h${lvl}>${inlineMD(ln.replace(/^#+\s/,''))}</h${lvl}>`;i++;continue;}
    if(/^\s*>/.test(ln)){let q='';while(i<lines.length&&/^\s*>/.test(lines[i])){q+=lines[i].replace(/^\s*>\s?/,'')+' ';i++;}html+=`<blockquote>${inlineMD(q.trim())}</blockquote>`;continue;}
    if(/^\s*[-*]\s/.test(ln)){let it='';while(i<lines.length&&/^\s*[-*]\s/.test(lines[i])){it+=`<li>${inlineMD(lines[i].replace(/^\s*[-*]\s/,''))}</li>`;i++;}html+=`<ul>${it}</ul>`;continue;}
    if(/^\s*\d+\.\s/.test(ln)){let it='';while(i<lines.length&&/^\s*\d+\.\s/.test(lines[i])){it+=`<li>${inlineMD(lines[i].replace(/^\s*\d+\.\s/,''))}</li>`;i++;}html+=`<ol>${it}</ol>`;continue;}
    if(/^\s*---\s*$/.test(ln)){html+='<hr>';i++;continue;}
    if(ln.trim()===''){i++;continue;}
    let p=ln;i++;while(i<lines.length&&lines[i].trim()!==''&&!/^(#{1,3}\s|\s*[-*]\s|\s*\d+\.\s|>|```)/.test(lines[i])){p+='\n'+lines[i];i++;}
    html+=`<p>${inlineMD(p).replace(/\n/g,'<br>')}</p>`;
  }
  return html;
}
function splitRow(ln){return ln.replace(/^\s*\|/,'').replace(/\|\s*$/,'').split('|').map(c=>c.trim());}
function tableHTML(h,r){
  const TH='break-words border border-border bg-primary-subtle px-3 py-1 text-start text-primary-subtle-foreground';
  const TD='break-words border border-border px-3 py-1';
  return `<div class="overflow-x-auto"><table class="my-0 border-collapse border border-border">`
    + `<thead><tr>${h.map(x=>`<th class="${TH}">${inlineMD(x)}</th>`).join('')}</tr></thead>`
    + `<tbody>${r.map(rw=>`<tr class="odd:cu-tr-odd">${rw.map(c=>`<td class="${TD}">${inlineMD(c)}</td>`).join('')}</tr>`).join('')}</tbody>`
    + `</table></div>`;
}
function pipeTable(src){const ls=String(src).split('\n').filter(l=>l.trim()!=='');if(!ls.length)return '';return tableHTML(splitRow(ls[0]),ls.slice(1).map(splitRow));}
function buttonsHTML(src){
  const items=String(src).split('\n').filter(l=>l.trim()!=='').map(l=>{const[label,action]=l.split('|').map(s=>s.trim());return{label,action:action||label};});
  return `<div class="quick-chips">${items.map(it=>`<button class="quick-chip" onclick="studioLog('quick_reply',{label:'${escAttr(it.label)}',action:'${escAttr(it.action)}'})">${esc(it.label)}</button>`).join('')}</div>`;
}

/* ---------- A2UI (v0.9 subset) ---------- */
function parseEnvelopes(src){src=String(src).trim();try{const j=JSON.parse(src);return Array.isArray(j)?j:[j];}catch(e){}const out=[];for(const ln of src.split('\n')){const t=ln.trim();if(!t)continue;out.push(JSON.parse(t));}return out;}
function buildSurface(env){const s={id:null,theme:{},components:new Map(),data:{}};for(const e of env){if(e.createSurface){s.id=e.createSurface.surfaceId;s.theme=e.createSurface.theme||{};}else if(e.updateComponents){for(const c of e.updateComponents.components)s.components.set(c.id,c);}else if(e.updateDataModel){setPointer(s.data,e.updateDataModel.path||'/',e.updateDataModel.value);}}return s;}
function setPointer(o,p,v){if(!p||p==='/'){if(v&&typeof v==='object'){for(const k in o)delete o[k];Object.assign(o,v);}return;}const ps=p.replace(/^\//,'').split('/');let c=o;for(let i=0;i<ps.length-1;i++){const k=ps[i];if(typeof c[k]!=='object'||c[k]===null)c[k]={};c=c[k];}c[ps[ps.length-1]]=v;}
function getPointer(o,p,sc){if(p==null)return undefined;let ps=String(p);let base=ps.startsWith('/')?o:(sc!==undefined?sc:o);const parts=ps.replace(/^\//,'').split('/').filter(x=>x!=='');let c=base;for(const k of parts){if(c==null)return undefined;c=c[k];}return c;}
function resolveDyn(v,d,sc){if(v==null)return v;if(typeof v==='object'){if('path' in v)return getPointer(d,v.path,sc);if(v.call==='formatString')return formatString(v.args&&v.args.value,d,sc);return v;}return v;}
function formatString(t,d,sc){if(typeof t!=='string')return t==null?'':String(t);return t.replace(/\$\{([^}]+)\}/g,(m,e)=>{e=e.trim();if(/\(/.test(e))return '';const v=getPointer(d,e,sc);return v==null?'':(typeof v==='object'?JSON.stringify(v):String(v));});}
const ICONS={mail:'\u2709\uFE0F',calendar:'\uD83D\uDCC5',check:'\u2714\uFE0F',star:'\u2B50',user:'\uD83D\uDC64',clock:'\uD83D\uDD50'};
const A2REG={};
function renderA2UI(src){
  let env; try{env=parseEnvelopes(src);}catch(e){return `<div class="a2-err">A2UI parse error:\n${esc(e.message)}</div>`;}
  let surf; try{surf=buildSurface(env);}catch(e){return `<div class="a2-err">A2UI build error:\n${esc(e.message)}</div>`;}
  if(!surf.components.has('root'))return `<div class="a2-err">A2UI: no component with id "root".</div>`;
  const sid='a2_'+uid(); A2REG[sid]={surface:surf};
  const inner=renderComponent('root',surf,surf.data,undefined,sid);
  const th=surf.theme||{};
  const bar = th.agentDisplayName ? `<div class="a2-agent-bar">\u2726 ${esc(th.agentDisplayName)}</div>` : '';
  const style = th.primaryColor ? ` style="--primary:${hexToHsl(th.primaryColor)}"` : '';
  return `<div class="a2-surface" id="${sid}"${style}>${bar}<div class="a2-pad">${inner}</div></div>`;
}
function hexToHsl(hex){const m=/^#?([0-9a-f]{6})$/i.exec(hex);if(!m)return '';let r=parseInt(m[1].slice(0,2),16)/255,g=parseInt(m[1].slice(2,4),16)/255,b=parseInt(m[1].slice(4,6),16)/255;const mx=Math.max(r,g,b),mn=Math.min(r,g,b);let h,s,l=(mx+mn)/2;if(mx===mn){h=s=0;}else{const d=mx-mn;s=l>0.5?d/(2-mx-mn):d/(mx+mn);switch(mx){case r:h=(g-b)/d+(g<b?6:0);break;case g:h=(b-r)/d+2;break;case b:h=(r-g)/d+4;break;}h*=60;}return `${Math.round(h)} ${Math.round(s*100)}% ${Math.round(l*100)}%`;}
function renderComponent(id,surf,data,scope,sid){
  const c=surf.components.get(id);if(!c)return '';
  const childIds=ids=>(ids||[]).map(x=>renderComponent(x,surf,data,scope,sid)).join('');
  function renderChildren(spec){
    if(Array.isArray(spec))return childIds(spec);
    if(spec&&typeof spec==='object'&&spec.path){const arr=getPointer(data,spec.path,scope)||[];const base=spec.path.replace(/^\//,'');return arr.map((it,idx)=>renderComponent(spec.componentId,surf,data,getPointer(data,'/'+base+'/'+idx),sid)).join('');}
    return '';
  }
  switch(c.component){
    case 'Text':{const t=resolveDyn(c.text,data,scope);const v=c.variant||'';return `<div class="a2-text ${v}">${renderMarkdown(String(t==null?'':t))}</div>`;}
    case 'Column':return `<div class="a2-col">${c.children?renderChildren(c.children):childIds(c.child?[c.child]:[])}</div>`;
    case 'Row':return `<div class="a2-row ${c.justify||''} ${c.align||''}">${c.children?renderChildren(c.children):childIds(c.child?[c.child]:[])}</div>`;
    case 'List':return `<div class="a2-col">${renderChildren(c.children)}</div>`;
    case 'Card':return `<div class="a2-card ${c.tone==='info'?'a2-card-info':''}">${c.child?renderComponent(c.child,surf,data,scope,sid):renderChildren(c.children)}</div>`;
    case 'Divider':return `<div class="a2-divider"></div>`;
    case 'Image':{const u=resolveDyn(c.url||c.src,data,scope);return `<img class="a2-img" style="max-width:100%;border-radius:8px" src="${esc(u)}" alt="">`;}
    case 'Icon':return `<span style="font-size:18px">${esc(ICONS[c.name]||'\u2022')}</span>`;
    case 'Button':{
      const label=c.child?renderComponent(c.child,surf,data,scope,sid):esc(resolveDyn(c.text,data,scope)||'Button');
      const VAR={primary:'primary',outline:'outline',ghost:'ghost',borderless:'ghost',secondary:'outline'};
      const variant=VAR[c.variant]||'primary';
      const size=c.size==='cell'?' cell':'';
      const dis=c.disabled?' disabled':'';
      const ev=c.action&&c.action.event;
      const handler=(ev&&!c.disabled)?` onclick='a2Action(${JSON.stringify(JSON.stringify({sid,name:ev.name,ctx:ev.context||{}}))})'`:'';
      return `<button class="a2-btn ${variant}${size}"${dis}${handler}>${label}</button>`;
    }
    case 'TextField':{const p=c.value&&c.value.path;const v=getPointer(data,p,scope)||'';return `<label class="a2-field"><span class="a2-text caption">${esc(c.label||'')}</span><input value="${escAttr(v)}" placeholder="${escAttr(c.placeholder||'')}" oninput='a2Input(${JSON.stringify(JSON.stringify({sid,path:p}))},this.value)'></label>`;}
    case 'CheckBox':{const p=c.value&&c.value.path;const v=getPointer(data,p,scope);return `<label class="a2-check"><input type="checkbox" ${v?'checked':''} onchange='a2Input(${JSON.stringify(JSON.stringify({sid,path:p}))},this.checked)'> ${esc(c.label||'')}</label>`;}
    case 'ChoicePicker':{const p=c.value&&c.value.path;const cur=getPointer(data,p,scope);const name=id;return `<div class="a2-choice">${(c.options||[]).map(o=>{const checked=Array.isArray(cur)?cur.includes(o.value):cur===o.value;return `<label><input type="radio" name="${name}" ${checked?'checked':''} onchange='a2Input(${JSON.stringify(JSON.stringify({sid,path:p}))}, ${JSON.stringify(o.value)})'> ${esc(o.label)}</label>`;}).join('')}</div>`;}
    default:return `<div class="a2-text">${esc(c.component)}</div>`;
  }
}
function a2Input(meta,val){const {sid,path}=JSON.parse(meta);const r=A2REG[sid];if(!r||!path)return;setPointer(r.surface.data,path,val);}
function a2Action(meta){const {sid,name,ctx}=JSON.parse(meta);const r=A2REG[sid];const ctxR={};for(const k in (ctx||{})){const v=ctx[k];ctxR[k]=(v&&typeof v==='object'&&'path'in v)?getPointer(r.surface.data,v.path):v;}studioLog(name,{...ctxR,_dataModel:r?r.surface.data:undefined});}

/* ---------- events console ---------- */
function studioLog(name,payload){
  const c=document.getElementById('studioConsole');
  if(!c.classList.contains('show')) c.classList.add('show');
  const t=new Date().toLocaleTimeString();
  const d=document.createElement('div'); d.innerHTML=`${esc(t)} <b>${esc(name)}</b> ${esc(JSON.stringify(payload))}`;
  c.appendChild(d); c.scrollTop=c.scrollHeight;
}

/* ---------- playback into the real Claudia DOM ---------- */
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
function spd(id,base){const v=+document.getElementById(id).value;return Math.max(5,base*(11-v));}
let studioPlaying=false, studioAbort=false;
function studioReset(){studioAbort=true;studioPlaying=false;const list=document.querySelector('[data-msg-list]');if(list)list.innerHTML='';const ta=document.querySelector('[data-claudia-composer]');if(ta)ta.value='';document.getElementById('studioPlayBtn').textContent='\u25B6 Play';studioShowFirstScreen();}
function scrollChat(){const s=document.querySelector('[data-chat-scroll]');if(s)s.scrollTop=s.scrollHeight;}

function mkUserDOM(){
  const w=document.createElement('div');
  w.innerHTML=`<div class="relative" style="min-height:0px">
    <div class="flex flex-col items-end py-4 lg:py-0">
      <div class="group w-full lg:w-fit lg:max-w-[75%]">
        <div class="rounded-3xl rounded-ee-none px-5 py-2 bg-background-alternate">
          <div class="flex-1 space-y-4 overflow-hidden p-1">
            <p class="prose relative break-words dark:prose-invert prose-p:leading-relaxed text-wrap message-user whitespace-pre-wrap u-body"></p>
          </div>
        </div>
        <div class="mt-2 flex justify-end space-x-1">
          <span class="self-center px-0.5 text-xs tabular-nums u-time"></span>
        </div>
      </div>
    </div>
  </div>`;
  const root=w.firstElementChild;
  return {root, body:root.querySelector('.u-body'), time:root.querySelector('.u-time')};
}
// Real Claudia AgentIcon (currentColor drives stroke/fill).
const AGENT_ICON_SVG=`<svg class="stroke-width-[0.5] size-4 shrink-0" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg"><g><path d="M12.9666 5.29527V11.4479C12.9666 11.8976 12.602 12.2622 12.1523 12.2622H9.70313L8.00001 14.2778L6.29688 12.2622H3.84776C3.39801 12.2622 3.03345 11.8976 3.03345 11.4479V5.29527C3.03345 4.84552 3.39804 4.48096 3.84776 4.48096H12.1522C12.602 4.48096 12.9666 4.84555 12.9666 5.29527Z" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"></path><path d="M14.8416 10.0566H12.9666V6.26074H14.8416C15.2225 6.26074 15.5312 6.56952 15.5312 6.95043V9.36687C15.5312 9.74777 15.2225 10.0566 14.8416 10.0566Z" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"></path><path d="M1.15844 10.0566H3.03344V6.26074H1.15844C0.777531 6.26074 0.46875 6.56952 0.46875 6.95043V9.36687C0.46875 9.74777 0.777531 10.0566 1.15844 10.0566Z" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"></path><path d="M1.15845 6.26067C1.15845 3.07373 3.74195 0.490234 6.92888 0.490234H9.07113C12.2581 0.490234 14.8416 3.07373 14.8416 6.26067" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"></path><g><circle cx="6.08838" cy="7.14087" fill="currentColor" r="0.46875"></circle><circle cx="9.71301" cy="7.14087" fill="currentColor" r="0.46875"></circle><path d="M10.0256 9.16528C8.76374 10.2843 7.23633 10.2843 5.97449 9.16528" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"></path></g></g></svg>`;
// Lucide icon helper (24-grid, 1.5 stroke) — matches the real Claudia icons.
function lucide(inner,extra){return `<svg aria-hidden="true" class="lucide size-4${extra?' '+extra:''}" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" xmlns="http://www.w3.org/2000/svg">${inner}</svg>`;}
// "Agen Lainnya" uses the real outlined lucide-layout-grid (not a solid glyph).
const AGENT_GRID_SVG=lucide('<rect width="7" height="7" x="3" y="3" rx="1"></rect><rect width="7" height="7" x="14" y="3" rx="1"></rect><rect width="7" height="7" x="14" y="14" rx="1"></rect><rect width="7" height="7" x="3" y="14" rx="1"></rect>','lucide-layout-grid');
// Action icons shown under every response (copy, like, dislike, view, regenerate, more).
const RESP_ACTION_ICONS=[
  '<rect height="14" rx="2" ry="2" width="14" x="8" y="8"></rect><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"></path>',
  '<path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"></path><path d="M7 10v12"></path>',
  '<path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z"></path><path d="M17 14V2"></path>',
  '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"></path><circle cx="12" cy="12" r="3"></circle>',
  '<path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"></path><path d="M3 3v5h5"></path><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"></path><path d="M16 16h5v5"></path>',
  '<circle cx="12" cy="12" r="1"></circle><circle cx="12" cy="5" r="1"></circle><circle cx="12" cy="19" r="1"></circle>'
];
const RESP_ACTIONS_HTML=RESP_ACTION_ICONS.map(inner=>`<button type="button" class="group inline-flex font-semibold border items-center justify-center whitespace-nowrap ring-offset-background transition-colors border-transparent text-foreground hover:bg-background-hover hover:border-background-hover focus:bg-background-hover focus:border-background-hover active:bg-background-hover active:border-background-hover rounded-[8px] size-6">${lucide(inner)}</button>`).join('');
// Assistant avatar: primary-subtle (mint) circle with the AgentIcon in primary-subtle-foreground.
const AGENT_AVATAR=`<div class="flex items-center justify-center rounded-full bg-primary-subtle text-primary-subtle-foreground" style="width:36px;height:36px;flex-shrink:0" aria-hidden="true">${AGENT_ICON_SVG}</div>`;
const CLAUDE_ICON=`<svg viewBox="0 0 256 257" class="size-5 flex-shrink-0" xmlns="http://www.w3.org/2000/svg"><path fill="#D97757" d="m50.228 170.321l50.357-28.257l.843-2.463l-.843-1.361h-2.462l-8.426-.518l-28.775-.778l-24.952-1.037l-24.175-1.296l-6.092-1.297L0 125.796l.583-3.759l5.12-3.434l7.324.648l16.202 1.101l24.304 1.685l17.629 1.037l26.118 2.722h4.148l.583-1.685l-1.426-1.037l-1.101-1.037l-25.147-17.045l-27.22-18.017l-14.258-10.37l-7.713-5.25l-3.888-4.925l-1.685-10.758l7-7.713l9.397.649l2.398.648l9.527 7.323l20.35 15.75L94.817 91.9l3.889 3.24l1.555-1.102l.195-.777l-1.75-2.917l-14.453-26.118l-15.425-26.572l-6.87-11.018l-1.814-6.61c-.648-2.723-1.102-4.991-1.102-7.778l7.972-10.823L71.42 0l10.63 1.426l4.472 3.888l6.61 15.101l10.694 23.786l16.591 32.34l4.861 9.592l2.592 8.879l.973 2.722h1.685v-1.556l1.36-18.211l2.528-22.36l2.463-28.776l.843-8.1l4.018-9.722l7.971-5.25l6.222 2.981l5.12 7.324l-.713 4.73l-3.046 19.768l-5.962 30.98l-3.889 20.739h2.268l2.593-2.593l10.499-13.934l17.628-22.036l7.778-8.749l9.073-9.657l5.833-4.601h11.018l8.1 12.055l-3.628 12.443l-11.342 14.388l-9.398 12.184l-13.48 18.147l-8.426 14.518l.778 1.166l2.01-.194l30.46-6.481l16.462-2.982l19.637-3.37l8.88 4.148l.971 4.213l-3.5 8.62l-20.998 5.184l-24.628 4.926l-36.682 8.685l-.454.324l.519.648l16.526 1.555l7.065.389h17.304l32.21 2.398l8.426 5.574l5.055 6.805l-.843 5.184l-12.962 6.611l-17.498-4.148l-40.83-9.721l-14-3.5h-1.944v1.167l11.666 11.406l21.387 19.314l26.767 24.887l1.36 6.157l-3.434 4.86l-3.63-.518l-23.526-17.693l-9.073-7.972l-20.545-17.304h-1.36v1.814l4.73 6.935l25.017 37.59l1.296 11.536l-1.814 3.76l-6.481 2.268l-7.13-1.297l-14.647-20.544l-15.1-23.138l-12.185-20.739l-1.49.843l-7.194 77.448l-3.37 3.953l-7.778 2.981l-6.48-4.925l-3.436-7.972l3.435-15.749l4.148-20.544l3.37-16.333l3.046-20.285l1.815-6.74l-.13-.454l-1.49.194l-15.295 20.999l-23.267 31.433l-18.406 19.702l-4.407 1.75l-7.648-3.954l.713-7.064l4.277-6.286l25.47-32.405l15.36-20.092l9.917-11.6l-.065-1.686h-.583L44.07 198.125l-12.055 1.555l-5.185-4.86l.648-7.972l2.463-2.593l20.35-13.999z"></path></svg>`;
function mkAssistantDOM(){
  const model=esc(activeAgentName()||'Assistant');
  const w=document.createElement('div');
  w.innerHTML=`<div class="relative" style="min-height:0px">
    <div class="flex flex-col items-start py-4 lg:py-0" style="gap:8px">
      <div class="flex items-center gap-3">
        ${studioHeaderAvatar()}
        <div class="border-b w-fit border-none">
          <div class="inline-flex flex-col justify-start gap-x-1 p-0 md:flex-row">
            <div class="flex items-center gap-1">
              <p class="caption-regular text-foreground opacity-secondary">${model}</p>
              <span class="text-sm opacity-secondary" aria-hidden="true">\u2022</span>
            </div>
            <div class="flex items-start gap-1 p-1">
              <span class="text-left text-xs font-normal opacity-secondary a-status"></span>
            </div>
          </div>
        </div>
      </div>
      <div class="a-prep" style="display:none"></div>
      <div class="prose relative break-words dark:prose-invert prose-p:leading-relaxed text-wrap message-assistant max-w-full a-content"></div>
      <div class="mt-2 flex flex-row gap-3 a-foot" style="visibility:hidden">${RESP_ACTIONS_HTML}</div>
    </div>
  </div>`;
  const root=w.firstElementChild;
  return {root, status:root.querySelector('.a-status'), content:root.querySelector('.a-content'),
          prep:root.querySelector('.a-prep'), foot:root.querySelector('.a-foot')};
}
const PREP_CHECK=lucide('<path d="M20 6 9 17l-5-5"></path>','');  // green check
function studioPrepRow(text){
  const row=document.createElement('div'); row.className='a-prep-step';
  row.innerHTML='<span class="a-prep-ic"><span class="a-prep-spin"></span></span><span class="a-prep-tx"></span>';
  row.querySelector('.a-prep-tx').textContent=text;
  return row;
}
// Play the "Mempersiapkan Jawaban" steps one by one: each shows a spinner, then a check.
async function studioRunPrepSteps(a){
  const steps=studio.brand.prepSteps||[];
  if(!steps.length){ await sleep(420+spd('studioTurnGap',40)); return; }
  a.prep.style.display=''; a.prep.innerHTML='';
  for(let i=0;i<steps.length;i++){
    if(studioAbort) return;
    const row=studioPrepRow(steps[i].text); a.prep.appendChild(row); scrollChat();
    await sleep(560+spd('studioTurnGap',55));
    if(studioAbort) return;
    row.querySelector('.a-prep-ic').innerHTML=PREP_CHECK;  // spinner -> check
  }
  await sleep(spd('studioTurnGap',30));
}
function clockHM(){const d=new Date();return String(d.getHours()).padStart(2,'0')+'.'+String(d.getMinutes()).padStart(2,'0');}

async function studioPlay(){
  if(studioPlaying){studioAbort=true;return;}
  studioReset(); await sleep(60);
  studioPlaying=true; studioAbort=false;
  document.getElementById('studioPlayBtn').textContent='\u25A0 Stop';
  const list=document.querySelector('[data-msg-list]');
  const composer=document.querySelector('[data-claudia-composer]');

  for(let ti=0; ti<studio.turns.length; ti++){
    const turn=studio.turns[ti];
    if(studioAbort) break;
    const ptext=turn.prompt||'';
    // USER — type the prompt into the real composer (which lives on the landing
    // for turn 1), then enter the conversation view and submit as a bubble.
    const cform=composer?composer.closest('form'):null;   // the prompt box (not the text)
    if(composer){ composer.value=''; composer.classList.add('studio-caret'); }
    if(cform) cform.classList.add('studio-typing');        // green focus ring on the box
    for(let i=0;i<ptext.length;i++){ if(studioAbort) break; if(composer) composer.value=ptext.slice(0,i+1); await sleep(spd('studioTypeSpeed',9)); }
    if(composer) composer.classList.remove('studio-caret');
    if(cform) cform.classList.remove('studio-typing');
    await sleep(spd('studioTurnGap',40));
    if(studioAbort) break;
    if(ti===0 && studioScreen==='first'){ studioShowConvo(); await sleep(spd('studioTurnGap',30)); }
    // submit: empty composer, append user bubble
    if(composer) composer.value='';
    const u=mkUserDOM();
    list.appendChild(u.root); u.body.textContent=ptext; u.time.textContent=clockHM();
    scrollChat();
    await sleep(spd('studioTurnGap',60));
    if(studioAbort) break;

    // ASSISTANT — header + thinking + stream
    const t0=performance.now();
    const a=mkAssistantDOM();
    list.appendChild(a.root); scrollChat();
    a.status.textContent='Mempersiapkan Jawaban';
    await studioRunPrepSteps(a);    // steps one by one: spinner -> check
    if(studioAbort) break;
    await streamInto(a.content, turn);
    a.prep.style.display='none'; a.prep.innerHTML='';   // response shown -> hide the steps
    const secs=((performance.now()-t0)/1000).toFixed(2).replace('.',',');
    a.status.textContent=`Selesai Mempersiapkan Jawaban (${secs} detik)`;
    a.foot.style.visibility='visible';
    await sleep(spd('studioTurnGap',80));
  }
  studioPlaying=false;
  document.getElementById('studioPlayBtn').textContent='\u25B6 Play';
}

async function streamInto(el, turn){
  el.innerHTML='';
  const blocks=turnBlocks(turn);
  for(let bi=0; bi<blocks.length; bi++){
    if(studioAbort) break;
    const sub=document.createElement('div'); if(bi>0) sub.style.marginTop='14px'; el.appendChild(sub);
    await streamBlock(sub, blocks[bi]);
  }
}
async function streamBlock(el, b){
  const type=b.type, src=b.content||'';
  if(type==='markdown'){
    for(let i=0;i<src.length;i++){
      if(studioAbort) break;
      el.innerHTML=renderMarkdown(src.slice(0,i+1)); scrollChat();
      await sleep(spd('studioStreamSpeed',6));
    }
    el.innerHTML=renderMarkdown(src);
  } else if(type==='table'){
    await sleep(spd('studioStreamSpeed',40)*2);
    el.innerHTML=pipeTable(src); scrollChat();
  } else if(type==='buttons'){
    await sleep(spd('studioStreamSpeed',40));
    el.innerHTML=buttonsHTML(src); scrollChat();
  } else if(type==='a2ui'){
    let env; try{env=parseEnvelopes(src);}catch(e){el.innerHTML=`<div class="a2-err">A2UI parse error:\n${esc(e.message)}</div>`;return;}
    for(let i=1;i<=env.length;i++){
      if(studioAbort) break;
      el.innerHTML=renderA2UI(JSON.stringify(env.slice(0,i))); scrollChat();
      await sleep(280+spd('studioStreamSpeed',20));
    }
    el.innerHTML=renderA2UI(JSON.stringify(env)); scrollChat();
  }
}

/* ---------- import (.xlsx) ---------- */
// Multi-block cases: a row with a User Prompt starts a case; following rows with an
// empty User Prompt add more response blocks (Response Type + Response) to that case.
function studioImportXlsx(ev){
  const f=ev.target.files[0]; if(!f) return;
  if(typeof XLSX==='undefined'){alert('Spreadsheet parser not loaded — open this file with internet access once, then it caches.');return;}
  const r=new FileReader();
  r.onload=()=>{try{
    const wb=XLSX.read(r.result,{type:'array'});
    const cs=wb.SheetNames.find(n=>/case/i.test(n))||wb.SheetNames[0];
    const rows=XLSX.utils.sheet_to_json(wb.Sheets[cs],{defval:""});
    const norm=k=>k.toLowerCase().replace(/[^a-z]/g,'');
    const find=(row,...ns)=>{const ks=Object.keys(row);
      for(const n of ns){const ek=ks.find(k=>norm(k)===n); if(ek) return row[ek];}      // exact first ("Response" != "Response Type")
      for(const n of ns){const k=ks.find(k=>norm(k).includes(n)); if(k) return row[k];}   // then substring
      return "";};
    const turns=[]; let cur=null;
    rows.forEach(row=>{
      const prompt=String(find(row,'userprompt','prompt')).trim();
      const resp=String(find(row,'response'));
      let ty=String(find(row,'responsetype','type')).trim().toLowerCase(); if(!RESP_TYPES.includes(ty)) ty='markdown';
      const notes=String(find(row,'expectedbehavior','expected','notes','behavior'));
      if(prompt!==''){
        cur={id:uid(),prompt:prompt,blocks:[{id:uid(),type:ty,content:resp}],notes:notes}; turns.push(cur);
      } else if(resp.trim()!==''){
        if(cur){ cur.blocks.push({id:uid(),type:ty,content:resp}); if(notes&&!cur.notes) cur.notes=notes; }
        else { cur={id:uid(),prompt:'',blocks:[{id:uid(),type:ty,content:resp}],notes:notes}; turns.push(cur); }
      }
    });
    if(turns.length) studio.turns=turns;
    const th=wb.SheetNames.find(n=>/theme|brand/i.test(n));
    if(th){
      const tr=XLSX.utils.sheet_to_json(wb.Sheets[th],{header:1});
      const b={...DEFAULT_BRAND};
      const JSONKEYS=['profile','agents','conversations','shortcuts','prepSteps'];
      tr.forEach(r=>{const k=String(r[0]||'').trim(); const v=r[1]; if(!k) return;
        if(JSONKEYS.includes(k)){ try{ if(v!=null&&String(v)!=='') b[k]=JSON.parse(v); }catch(e){} }
        else if(k in b && v!=null && String(v)!==''){ b[k]=String(v); }
      });
      studio.brand=freshBrand(b);
    }
    studioRender(); studioApplyBrand();
  }catch(e){alert('Could not import xlsx: '+e.message);}};
  r.readAsArrayBuffer(f); ev.target.value='';
}

/* ---------- export (.xlsx) — same template as import, with studio changes ---------- */
function studioExportXlsx(){
  if(typeof XLSX==='undefined'){alert('Spreadsheet library not loaded — open this file with internet access once, then it caches.');return;}
  // Cases: one row per block; a row with a User Prompt starts a case, blank-prompt rows add blocks.
  const cases=[['#','Title','User Prompt','Response Type','Response','Expected Behavior (for devs)']];
  studio.turns.forEach((t,i)=>{
    const blocks=turnBlocks(t);
    blocks.forEach((b,bi)=>{
      const title=bi===0?(t.prompt||'').replace(/\s+/g,' ').slice(0,40):'';
      cases.push([ bi===0?(i+1):'', title, bi===0?(t.prompt||''):'', b.type, b.content||'', bi===0?(t.notes||''):'' ]);
    });
  });
  // Theme: full brand. Lists/objects are JSON-encoded so import can round-trip them.
  const b=studio.brand;
  const theme=[['Setting (key)','Value','Notes'],
    ['proyekName',b.proyekName||'','Sidebar project name'],
    ['proyekDesc',b.proyekDesc||'','Description under the hero (screen 1)'],
    ['llmName',b.llmName||'','Model shown/used when no Agen AI is active'],
    ['activeAgent',b.activeAgent||'','Active agent id ("" = use the LLM)'],
    ['activeConversation',b.activeConversation||'','Active conversation id'],
    ['primaryHsl',b.primaryHsl||'','Optional primary override "H S% L%"'],
    ['profile',JSON.stringify(b.profile||{}),'JSON {name,email,picture}'],
    ['agents',JSON.stringify(b.agents||[]),'JSON [{id,name}] (max 3)'],
    ['conversations',JSON.stringify(b.conversations||[]),'JSON [{id,title}] (left sidebar)'],
    ['shortcuts',JSON.stringify(b.shortcuts||[]),'JSON [{id,text}] (screen-1 chips, max 4)'],
    ['prepSteps',JSON.stringify(b.prepSteps||[]),'JSON [{id,text}] (loader steps)']
  ];
  const howto=[
    ['Static Chat Generator — authoring template (Claudia skin)'],[null],
    ["1. One row per response block on the 'Cases' sheet."],
    ['     • User Prompt = what the user types (starts a new case).'],
    ['     • Response Type = markdown / table / buttons / a2ui.'],
    ["     • Response = the assistant's output for that block."],
    ['     • Expected Behavior = acceptance criteria for developers.'],[null],
    ['2. Multi-part answers (e.g. text → table → text):'],
    ["     • Add extra rows below a case and LEAVE 'User Prompt' BLANK."],
    ['     • Each blank-prompt row adds another block (its own Response Type + Response).'],
    ['     • Blocks play in order, top to bottom, within that one answer.'],[null],
    ["3. The 'Theme' sheet holds the studio settings. List fields (agents,"],
    ['     conversations, shortcuts, prepSteps, profile) are stored as JSON.'],[null],
    ['4. Open index.html → Import .xlsx → choose this file. Press Play to preview/record.']
  ];
  const wb=XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(cases), 'Cases');
  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(theme), 'Theme');
  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(howto), 'How to use');
  XLSX.writeFile(wb, 'chat-cases.xlsx');
}

/* ---------- boot ---------- */
studioSeedFromDOM(); studioRender(); studioApplyBrand();
"""

# Inject style at end of head
style_tag = soup.new_tag("style"); style_tag.string = STUDIO_CSS
soup.head.append(style_tag)

# Inject toolbar/drawer HTML at end of body
tb_soup = BeautifulSoup(TOOLBAR_HTML, "lxml")
for el in list((tb_soup.body or tb_soup).children):
    soup.body.append(el)

# Inject SheetJS and the engine
sj = soup.new_tag("script", src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js")
sj["data-studio"] = "1"
soup.body.append(sj)
eng = soup.new_tag("script"); eng["data-studio"] = "1"; eng.string = ENGINE_JS
soup.body.append(eng)

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(str(soup), encoding="utf-8")
print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
