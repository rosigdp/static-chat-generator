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

/* Caret while typing into composer or user bubble */
.studio-caret::after{content:"\u258F";color:hsl(var(--primary));animation:studioCaret 1s steps(1) infinite;margin-left:1px}
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
    <button data-studio="1" onclick="studioExport()">\u2193 Spec JSON</button>
    <button data-studio="1" onclick="document.getElementById('studioImpJ').click()">\u2191 JSON</button>
    <input id="studioImpX" type="file" accept=".xlsx" data-studio="1" onchange="studioImportXlsx(event)" style="display:none">
    <input id="studioImpJ" type="file" accept="application/json" data-studio="1" onchange="studioImportJSON(event)" style="display:none">
  </div>
</div>
<div id="studioConsole" class="studio-console" data-studio="1"></div>
"""

ENGINE_JS = r"""
/* ==== Static Chat Generator — engine bolted onto Claudia DOM ==== */
const VERSION={tool:"2.0.0",uiSkin:"claudia-real-dom",a2uiCatalog:"v0.9"};
const RESP_TYPES=['markdown','table','buttons','a2ui'];
const DEFAULT_BRAND={
  conversationTitle:"Pengajuan Cuti & Pertanyaan HR",
  modelName:"GPT 5.5",
  primaryHsl:"" // optional override "H S% L%"
};
function uid(){return Math.random().toString(36).slice(2,9);}
function defaultA2UI(){
  return JSON.stringify([
    {"version":"v0.9","createSurface":{"surfaceId":"leave","catalogId":"https://a2ui.org/catalogs/basic/catalog.json","theme":{"agentDisplayName":"Employee Assistant"}}},
    {"version":"v0.9","updateComponents":{"surfaceId":"leave","components":[
      {"id":"root","component":"Card","child":"col"},
      {"id":"col","component":"Column","children":["title","type_label","type_picker","reason_label","reason_field","note","submit"]},
      {"id":"title","component":"Text","text":"# Pengajuan Cuti Tahunan","variant":"h2"},
      {"id":"type_label","component":"Text","text":"Jenis cuti","variant":"caption"},
      {"id":"type_picker","component":"ChoicePicker","variant":"mutuallyExclusive","options":[{"label":"Cuti Tahunan","value":"annual"},{"label":"Cuti Penting","value":"important"}],"value":{"path":"/leave/type"}},
      {"id":"reason_label","component":"Text","text":"Alasan","variant":"caption"},
      {"id":"reason_field","component":"TextField","label":"Alasan cuti","value":{"path":"/leave/reason"},"checks":[{"call":"required","args":{"value":{"path":"/leave/reason"}},"message":"Alasan wajib diisi."}]},
      {"id":"note","component":"Text","text":"Pengajuan akan dikirim ke atasan langsung.","variant":"caption"},
      {"id":"submit","component":"Button","child":"submit_label","variant":"primary","action":{"event":{"name":"submit_leave_request","context":{"type":{"path":"/leave/type"},"reason":{"path":"/leave/reason"}}}}},
      {"id":"submit_label","component":"Text","text":"Kirim pengajuan"}
    ]}},
    {"version":"v0.9","updateDataModel":{"surfaceId":"leave","path":"/leave","value":{"type":["annual"],"reason":""}}}
  ],null,2);
}
let studio={
  brand:{...DEFAULT_BRAND},
  turns:[
    {id:uid(),prompt:"Berapa sisa cuti tahunan saya?",type:"markdown",
     notes:"Saldo konsisten (kuota \u2212 terpakai = sisa). Tawarkan tindak lanjut. Jangan mengarang angka tanpa data karyawan.",
     content:"Berikut ringkasan **cuti tahunan** Anda untuk 2026:\n\n- Kuota tahunan: **12 hari**\n- Sudah terpakai: **5 hari**\n- **Sisa: 7 hari**\n\nIngin saya bantu membuat pengajuan cuti?"},
    {id:uid(),prompt:"Jenis cuti apa saja yang tersedia?",type:"table",
     notes:"Sertakan semua jenis cuti aktif beserta kuota dan jalur persetujuan.",
     content:"Jenis Cuti | Kuota | Perlu Persetujuan\nCuti Tahunan | 12 hari/tahun | Atasan langsung\nCuti Sakit | Sesuai surat dokter | HR\nCuti Melahirkan | 90 hari | HR & Atasan\nCuti Penting | 2 hari/kejadian | Atasan langsung"},
    {id:uid(),prompt:"Saya mau mengajukan cuti tahunan",type:"a2ui",
     notes:"Render form pengajuan cuti. Aksi utama 'submit_leave_request'. Field 'alasan' wajib diisi.",
     content:defaultA2UI()},
    {id:uid(),prompt:"Apa yang bisa saya lakukan?",type:"buttons",
     notes:"Empat quick-reply sesuai intent utama Employee Assistant.",
     content:"Ajukan ketidakhadiran | submit_absence\nAjukan koreksi kehadiran | submit_attendance_correction\nCek pengajuan untuk disetujui | view_pending_approvals\nAjukan cuti tahunan | submit_annual_leave"}
  ]
};

/* ---------- editor ---------- */
function studioRender(){
  const w=document.getElementById('studioCases');
  w.innerHTML=studio.turns.map((t,i)=>studioTurn(t,i)).join('')+
    `<button class="studio-add" onclick="studioAdd()">+ Add case</button>`;
  studioRenderBrand();
}
function studioTurn(t,i){
  const pills=RESP_TYPES.map(rt=>{
    const lbl={markdown:'Markdown',table:'Table',buttons:'Buttons',a2ui:'A2UI'}[rt];
    return `<button data-studio="1" class="${t.type===rt?'active':''}" onclick="studioSetType('${t.id}','${rt}')">${lbl}</button>`;
  }).join('');
  const ph={markdown:"Markdown. **bold**, lists, `code`, tables.",table:"One row per line, cells split by | . First line = header.",buttons:"One button per line.  Label | optional_action_name",a2ui:"A2UI v0.9 envelopes as JSON array (or JSONL)."}[t.type];
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
      <div class="studio-fld"><label>Expected response</label>
        <div class="studio-pills">${pills}</div>
        <textarea data-studio="1" class="${t.type==='a2ui'||t.type==='table'||t.type==='buttons'?'code':''}" oninput="studioUpd('${t.id}','content',this.value)" placeholder="${ph}">${esc(t.content)}</textarea>
      </div>
      <div class="studio-fld"><label>Notes / expected behavior (for devs)</label><textarea data-studio="1" oninput="studioUpd('${t.id}','notes',this.value)">${esc(t.notes||'')}</textarea></div>
    </div>
  </div>`;
}
function studioRenderBrand(){
  const b=studio.brand;
  document.getElementById('studioBrand').innerHTML=`
    <div class="studio-fld"><label>Conversation title (shown in the top bar)</label><input data-studio="1" value="${esc(b.conversationTitle)}" oninput="studioBrand('conversationTitle',this.value)"></div>
    <div class="studio-fld"><label>Model label (shown on each answer)</label><input data-studio="1" value="${esc(b.modelName)}" oninput="studioBrand('modelName',this.value)"></div>
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
function studioSetType(id,ty){const t=studio.turns.find(x=>x.id===id);if(t){t.type=ty;studioRender();}}
function studioAdd(){studio.turns.push({id:uid(),prompt:"",type:"markdown",content:"",notes:""});studioRender();}
function studioDel(id){studio.turns=studio.turns.filter(x=>x.id!==id);studioRender();}
function studioMove(id,d){const i=studio.turns.findIndex(x=>x.id===id),j=i+d;if(j<0||j>=studio.turns.length)return;[studio.turns[i],studio.turns[j]]=[studio.turns[j],studio.turns[i]];studioRender();}
function studioBrand(k,v){studio.brand[k]=v;studioApplyBrand();}
function studioApplyBrand(){
  // conversation title
  const t=document.querySelector('[data-convo-title]'); if(t) t.textContent=studio.brand.conversationTitle||'';
  // primary override
  if(studio.brand.primaryHsl){
    document.documentElement.style.setProperty('--primary', studio.brand.primaryHsl);
  } else {
    document.documentElement.style.removeProperty('--primary');
  }
}
function studioToggleDrawer(){document.getElementById('studioDrawer').classList.toggle('open');}
function studioToggleRec(){document.documentElement.classList.toggle('studio-recording');}
function studioToggleConsole(){document.getElementById('studioConsole').classList.toggle('show');}

/* ---------- escape + markdown (compact; prose styles it) ---------- */
function esc(s){return (s==null?'':String(s)).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
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
function tableHTML(h,r){return `<table><thead><tr>${h.map(x=>`<th>${inlineMD(x)}</th>`).join('')}</tr></thead><tbody>${r.map(rw=>`<tr>${rw.map(c=>`<td>${inlineMD(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;}
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
    case 'Card':return `<div class="a2-card">${c.child?renderComponent(c.child,surf,data,scope,sid):renderChildren(c.children)}</div>`;
    case 'Divider':return `<div class="a2-divider"></div>`;
    case 'Image':{const u=resolveDyn(c.url||c.src,data,scope);return `<img class="a2-img" style="max-width:100%;border-radius:8px" src="${esc(u)}" alt="">`;}
    case 'Icon':return `<span style="font-size:18px">${esc(ICONS[c.name]||'\u2022')}</span>`;
    case 'Button':{
      const label=c.child?renderComponent(c.child,surf,data,scope,sid):esc(resolveDyn(c.text,data,scope)||'Button');
      const variant=c.variant==='borderless'?'borderless':'primary';
      const ev=c.action&&c.action.event;
      const handler=ev?` onclick='a2Action(${JSON.stringify(JSON.stringify({sid,name:ev.name,ctx:ev.context||{}}))})'`:'';
      return `<button class="a2-btn ${variant}"${handler}>${label}</button>`;
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
function studioReset(){studioAbort=true;studioPlaying=false;const list=document.querySelector('[data-msg-list]');if(list)list.innerHTML='';const ta=document.querySelector('[data-claudia-composer]');if(ta)ta.value='';document.getElementById('studioPlayBtn').textContent='\u25B6 Play';}
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
function mkAssistantDOM(){
  const model=esc(studio.brand.modelName||'Assistant');
  const w=document.createElement('div');
  w.innerHTML=`<div class="relative" style="min-height:0px">
    <div class="flex flex-col items-start py-4 lg:py-0" style="gap:8px">
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
      <div class="prose relative break-words dark:prose-invert prose-p:leading-relaxed text-wrap message-assistant max-w-full a-content"></div>
      <div class="mt-2 flex items-center gap-2 a-foot" style="visibility:hidden">
        <p class="caption-regular text-foreground opacity-secondary">${model}</p>
        <span class="text-xs tabular-nums opacity-secondary a-time"></span>
      </div>
    </div>
  </div>`;
  const root=w.firstElementChild;
  return {root, status:root.querySelector('.a-status'), content:root.querySelector('.a-content'),
          foot:root.querySelector('.a-foot'), time:root.querySelector('.a-time')};
}
function clockHM(){const d=new Date();return String(d.getHours()).padStart(2,'0')+'.'+String(d.getMinutes()).padStart(2,'0');}

async function studioPlay(){
  if(studioPlaying){studioAbort=true;return;}
  studioReset(); await sleep(60);
  studioPlaying=true; studioAbort=false;
  document.getElementById('studioPlayBtn').textContent='\u25A0 Stop';
  const list=document.querySelector('[data-msg-list]');
  const composer=document.querySelector('[data-claudia-composer]');

  for(const turn of studio.turns){
    if(studioAbort) break;
    // USER — type into the real composer first, then submit as a bubble
    if(composer){ composer.value=''; composer.classList.add('studio-caret'); }
    const ptext=turn.prompt||'';
    for(let i=0;i<ptext.length;i++){
      if(studioAbort) break;
      if(composer) composer.value=ptext.slice(0,i+1);
      await sleep(spd('studioTypeSpeed',9));
    }
    if(composer) composer.classList.remove('studio-caret');
    await sleep(spd('studioTurnGap',40));
    if(studioAbort) break;
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
    a.status.textContent='Mempersiapkan jawaban\u2026';
    a.content.innerHTML='<span class="opacity-secondary">\u25CF\u25CF\u25CF</span>';
    await sleep(520+spd('studioTurnGap',40));
    if(studioAbort) break;
    a.content.innerHTML='';
    await streamInto(a.content, turn);
    const secs=((performance.now()-t0)/1000).toFixed(2).replace('.',',');
    a.status.textContent=`Selesai Mempersiapkan Jawaban (${secs} detik)`;
    a.foot.style.visibility='visible'; a.time.textContent=clockHM();
    await sleep(spd('studioTurnGap',80));
  }
  studioPlaying=false;
  document.getElementById('studioPlayBtn').textContent='\u25B6 Play';
}

async function streamInto(el, turn){
  const type=turn.type, src=turn.content||'';
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

/* ---------- import / export ---------- */
function studioExport(){
  const out={meta:{tool:"Static Chat Generator",toolVersion:VERSION.tool,uiSkin:VERSION.uiSkin,a2uiCatalog:VERSION.a2uiCatalog,exported:new Date().toISOString()},
    brand:studio.brand,
    cases:studio.turns.map((t,i)=>({index:i+1,prompt:t.prompt,responseType:t.type,response:t.content,expectedBehavior:t.notes||""}))};
  const blob=new Blob([JSON.stringify(out,null,2)],{type:'application/json'});
  const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='chat-cases.json'; a.click(); URL.revokeObjectURL(a.href);
}
function studioImportJSON(ev){
  const f=ev.target.files[0]; if(!f) return;
  const r=new FileReader();
  r.onload=()=>{try{
    const j=JSON.parse(r.result);
    if(j.brand) studio.brand=Object.assign({...DEFAULT_BRAND},j.brand);
    if(Array.isArray(j.cases)) studio.turns=j.cases.map(c=>({id:uid(),prompt:c.prompt||'',type:RESP_TYPES.includes(c.responseType)?c.responseType:'markdown',content:c.response||'',notes:c.expectedBehavior||''}));
    studioRender(); studioApplyBrand();
  }catch(e){alert('Could not import: '+e.message);}};
  r.readAsText(f); ev.target.value='';
}
function studioImportXlsx(ev){
  const f=ev.target.files[0]; if(!f) return;
  if(typeof XLSX==='undefined'){alert('Spreadsheet parser not loaded — open this file with internet access once, then it caches.');return;}
  const r=new FileReader();
  r.onload=()=>{try{
    const wb=XLSX.read(r.result,{type:'array'});
    const cs=wb.SheetNames.find(n=>/case/i.test(n))||wb.SheetNames[0];
    const rows=XLSX.utils.sheet_to_json(wb.Sheets[cs],{defval:""});
    const find=(row,...ns)=>{const ks=Object.keys(row);for(const n of ns){const k=ks.find(k=>k.toLowerCase().replace(/[^a-z]/g,'').includes(n));if(k)return row[k];}return "";};
    const turns=rows.filter(r=>String(find(r,'userprompt','prompt')).trim()!=='' || String(find(r,'response')).trim()!=='').map(r=>{
      let ty=String(find(r,'responsetype','type')).trim().toLowerCase(); if(!RESP_TYPES.includes(ty)) ty='markdown';
      return {id:uid(),prompt:String(find(r,'userprompt','prompt')),type:ty,content:String(find(r,'response')),notes:String(find(r,'expectedbehavior','expected','notes','behavior'))};
    });
    if(turns.length) studio.turns=turns;
    const th=wb.SheetNames.find(n=>/theme|brand/i.test(n));
    if(th){const tr=XLSX.utils.sheet_to_json(wb.Sheets[th],{header:1});const b={...DEFAULT_BRAND};tr.forEach(r=>{const k=String(r[0]||'').trim();const v=r[1];if(k&&k in b&&v!=null&&String(v)!=='')b[k]=String(v);});studio.brand=b;}
    studioRender(); studioApplyBrand();
  }catch(e){alert('Could not import xlsx: '+e.message);}};
  r.readAsArrayBuffer(f); ev.target.value='';
}

/* ---------- boot ---------- */
studioRender(); studioApplyBrand();
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
