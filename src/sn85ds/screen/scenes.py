"""Screen-content scenes as self-contained HTML pages with a deterministic renderFrame(t).

Every page is offline (no network, no external fonts or images); all content is generated
from the scene seed (see content.py). The renderer sets t = k / fps for frame k, so the
motion is exact and repeatable. Subcategories: spreadsheet, code, terminal, dashboard,
document (document scroll or UI animation; portrait = phone-like layout).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np

from sn85ds.screen import content as C

THEMES = {
    "light": {"bg": "#ffffff", "fg": "#1f2328", "muted": "#6e7781", "panel": "#f6f8fa", "line": "#d0d7de", "accent": "#0969da", "sel": "#cfe3ff", "warn": "#9a6700", "err": "#cf222e", "ok": "#1a7f37"},
    "dark": {"bg": "#0d1117", "fg": "#e6edf3", "muted": "#8b949e", "panel": "#161b22", "line": "#30363d", "accent": "#58a6ff", "sel": "#1f3a5f", "warn": "#d29922", "err": "#f85149", "ok": "#3fb950"},
    "solar": {"bg": "#fdf6e3", "fg": "#586e75", "muted": "#93a1a1", "panel": "#eee8d5", "line": "#d6cfb6", "accent": "#268bd2", "sel": "#e3dcc4", "warn": "#b58900", "err": "#dc322f", "ok": "#859900"},
    "midnight": {"bg": "#1e1e2e", "fg": "#cdd6f4", "muted": "#7f849c", "panel": "#181825", "line": "#313244", "accent": "#89b4fa", "sel": "#45475a", "warn": "#f9e2af", "err": "#f38ba8", "ok": "#a6e3a1"},
    "paper": {"bg": "#fbfbf8", "fg": "#222222", "muted": "#777777", "panel": "#efefea", "line": "#cfcfc8", "accent": "#b5432f", "sel": "#f3dcd5", "warn": "#a66a00", "err": "#b00020", "ok": "#2e7d32"},
}
SYNTAX = {
    "light": {"kw": "#cf222e", "string": "#0a3069", "comment": "#6e7781", "number": "#0550ae", "fn": "#8250df", "bi": "#953800", "op": "#1f2328", "id": "#1f2328"},
    "dark": {"kw": "#ff7b72", "string": "#a5d6ff", "comment": "#8b949e", "number": "#79c0ff", "fn": "#d2a8ff", "bi": "#ffa657", "op": "#e6edf3", "id": "#e6edf3"},
    "solar": {"kw": "#859900", "string": "#2aa198", "comment": "#93a1a1", "number": "#d33682", "fn": "#268bd2", "bi": "#cb4b16", "op": "#586e75", "id": "#586e75"},
    "midnight": {"kw": "#cba6f7", "string": "#a6e3a1", "comment": "#6c7086", "number": "#fab387", "fn": "#89b4fa", "bi": "#f9e2af", "op": "#cdd6f4", "id": "#cdd6f4"},
    "paper": {"kw": "#7a1fa2", "string": "#1b5e20", "comment": "#8d8d8d", "number": "#0d47a1", "fn": "#b5432f", "bi": "#6d4c41", "op": "#222222", "id": "#222222"},
}
MONO = ["DejaVu Sans Mono", "Liberation Mono", "Ubuntu Mono"]
SANS = ["DejaVu Sans", "Liberation Sans", "Ubuntu"]
SERIF = ["DejaVu Serif", "Liberation Serif"]


@dataclass
class Scene:
    subcategory: str
    variant: str
    width: int          # output pixels
    height: int
    device_scale: float  # CSS px -> device px
    params: dict = field(default_factory=dict)
    html: str = ""

    @property
    def viewport(self) -> tuple[int, int]:
        return int(round(self.width / self.device_scale)), int(round(self.height / self.device_scale))


def _page(theme: dict, css: str, body: str, data: dict, js: str) -> str:
    root = ";".join(f"--{k}:{v}" for k, v in theme.items())
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
:root{{{root}}}
*{{box-sizing:border-box}} html,body{{margin:0;padding:0;overflow:hidden;background:var(--bg);color:var(--fg);width:100%;height:100%}}
{css}</style></head><body>{body}
<script>const D={json.dumps(data).replace("</", "<\\/")};
function rnd(s){{return function(){{s|=0;s=s+0x6D2B79F5|0;let t=Math.imul(s^s>>>15,1|s);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296;}}}}
function ease(x){{return x<0?0:x>1?1:x*x*(3-2*x);}}
{js}
window.renderFrame=renderFrame;</script></body></html>"""


def _pick(rng, seq):
    return seq[int(rng.integers(len(seq)))]


# ---------------------------------------------------------------------------------------- spreadsheet

def spreadsheet(seed: int, width: int, height: int) -> Scene:
    rng = np.random.default_rng(seed)
    tname = _pick(rng, ["light", "light", "paper", "dark", "solar"])
    th = THEMES[tname]
    font = _pick(rng, SANS + MONO[:1])
    fs = int(rng.integers(11, 15))
    rowh = fs + int(rng.integers(6, 10))
    nrows = 600
    kinds, colw = [], []
    while sum(colw) < width * 1.08:  # enough columns to fill the window (plus a partial one)
        k = _pick(rng, ["int", "dec", "pct", "date", "cur", "name", "code", "dec", "int"]) if kinds else ("date" if rng.random() < 0.5 else "name")
        kinds.append(k)
        colw.append(int({"int": 70, "dec": 86, "pct": 62, "date": 88, "cur": 96, "name": 118, "code": 80}[k] * rng.uniform(0.9, 1.25) * fs / 12.0))
    ncols = len(kinds)
    cells = []
    for r in range(nrows):
        row = []
        for k in kinds:
            if k == "int":
                row.append(f"{int(rng.integers(-5000, 250000)):,}")
            elif k == "dec":
                row.append(f"{rng.normal(500, 900):,.2f}")
            elif k == "pct":
                row.append(f"{rng.normal(3, 8):.1f}%")
            elif k == "date":
                row.append(f"2026-{int(rng.integers(1, 13)):02d}-{int(rng.integers(1, 29)):02d}")
            elif k == "cur":
                row.append(f"${rng.gamma(2, 4000):,.2f}")
            elif k == "name":
                row.append(C.name(rng))
            else:
                row.append(f"{_pick(rng, ['AX', 'BQ', 'KM', 'ZT', 'RL'])}-{int(rng.integers(1000, 99999))}")
        cells.append(row)
    numeric = [j for j, k in enumerate(kinds) if k in ("int", "dec", "pct", "cur")] or [0]
    live = [[int(rng.integers(2, 60)), int(numeric[int(rng.integers(len(numeric)))]), float(rng.uniform(0.5, 4))] for _ in range(int(rng.integers(20, 80)))]
    speed = float(_pick(rng, [0.0, 2.0, 5.0, 9.0, 16.0, 28.0]))  # rows per second
    jumps = sorted(float(x) for x in rng.uniform(0.5, 9.5, int(rng.integers(0, 3))))
    data = {"cells": cells, "colw": colw, "rowh": rowh, "live": live, "speed": speed, "jumps": jumps, "kinds": kinds,
            "seed": int(rng.integers(1, 2**31)), "selrate": float(rng.uniform(1.2, 4.0)), "ncols": ncols}
    css = f"""body{{font:{fs}px '{font}'}}
#tb{{height:38px;background:var(--panel);border-bottom:1px solid var(--line);display:flex;gap:14px;align-items:center;padding:0 12px;color:var(--muted)}}
#tb b{{color:var(--fg);font-weight:600}} .btn{{border:1px solid var(--line);padding:2px 8px;border-radius:3px}}
#fx{{height:26px;border-bottom:1px solid var(--line);display:flex;align-items:center;padding:0 8px;gap:10px;font-family:'{MONO[0]}';font-size:{fs}px}}
#fx .ref{{width:70px;border-right:1px solid var(--line)}}
#grid{{position:absolute;top:64px;left:0;right:0;bottom:24px;overflow:hidden}}
#sb{{position:absolute;bottom:0;left:0;right:0;height:24px;background:var(--panel);border-top:1px solid var(--line);color:var(--muted);padding:3px 10px;font-size:{max(10, fs - 1)}px}}
table{{border-collapse:collapse;table-layout:fixed;position:absolute;left:0}}
td,th{{border:1px solid var(--line);height:{rowh}px;padding:0 4px;white-space:nowrap;overflow:hidden;text-align:right}}
th{{background:var(--panel);color:var(--muted);font-weight:500;text-align:center}}
td.l{{text-align:left}} td.sel{{outline:2px solid var(--accent);outline-offset:-2px;background:var(--sel)}}
td.up{{color:var(--ok)}} td.dn{{color:var(--err)}} td.flash{{background:var(--sel)}}
#hdr{{position:absolute;top:0;left:0;z-index:2}}"""
    body = """<div id="tb"><b>Quarterly_ledger.ods</b><span class="btn">File</span><span class="btn">Edit</span><span class="btn">View</span>
<span class="btn">Insert</span><span class="btn">Format</span><span class="btn">Data</span><span>Σ</span><span>%</span><span>0.00</span></div>
<div id="fx"><span class="ref" id="ref">A1</span><span id="fv"></span></div><div id="grid"><table id="hdr"></table><table id="t"></table></div><div id="sb"></div>"""
    js = """const L="ABCDEFGHIJKLMNOPQRSTUVWXYZ";
function colname(j){return j<26?L[j]:L[Math.floor(j/26)-1]+L[j%26];}
const grid=document.getElementById('grid'),T=document.getElementById('t'),H=document.getElementById('hdr');
let cg='<colgroup><col style="width:46px">'+D.colw.map(w=>'<col style="width:'+w+'px">').join('')+'</colgroup>';
H.innerHTML=cg+'<tr><th></th>'+D.colw.map((w,j)=>'<th>'+colname(j)+'</th>').join('')+'</tr>';
const liveMap={};D.live.forEach(([r,c,rate])=>{liveMap[r+','+c]=rate;});
function cellv(r,c,t){let v=D.cells[r][c];const rate=liveMap[r+','+c];if(rate===undefined)return [v,''];
 const step=Math.floor(t*rate);const R=rnd(D.seed+r*977+c*131+step);const x=(R()*2-1);
 const num=parseFloat(v.replace(/[^0-9.\\-]/g,''));if(isNaN(num))return [v,''];
 const nv=num*(1+x*0.03);const s=v.indexOf('$')>=0?'$'+nv.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):v.endsWith('%')?nv.toFixed(1)+'%':v.indexOf('.')>=0?nv.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):Math.round(nv).toLocaleString('en-US');
 const fl=(t*rate-step)<0.25;return [s,(x>=0?'up':'dn')+(fl?' flash':'')];}
function renderFrame(t){let pos=D.speed*t;D.jumps.forEach(j=>{if(t>j)pos+=40*ease((t-j)/0.35);});
 const first=Math.floor(pos),frac=pos-first;const vis=Math.ceil(grid.clientHeight/D.rowh)+2;
 const selStep=Math.floor(t*D.selrate);const R=rnd(D.seed+selStep*7);const sr=first+2+Math.floor(R()*Math.max(1,vis-6)),sc=Math.floor(R()*D.ncols);
 let h=cg;for(let i=0;i<vis;i++){const r=(first+i)%D.cells.length;h+='<tr><th>'+(r+1)+'</th>';
  for(let c=0;c<D.ncols;c++){const [v,cls]=cellv(r,c,t);const left=['date','name','code'].indexOf(D.kinds[c])>=0;
   h+='<td class="'+(left?'l ':'')+cls+(r===sr%D.cells.length&&c===sc?' sel':'')+'">'+v+'</td>';}h+='</tr>';}
 T.innerHTML=h;T.style.top=(D.rowh+2-frac*D.rowh)+'px';
 document.getElementById('ref').textContent=colname(sc)+(sr+1);
 document.getElementById('fv').textContent='='+(sc%3==0?'SUM(':sc%3==1?'AVERAGE(':'ROUND(')+colname(sc)+(sr-4)+':'+colname(sc)+(sr)+')';
 document.getElementById('sb').textContent='Sheet 1 of 3   |   Sum='+(1234.5+selStep*17.25).toFixed(2)+'   Count='+(8+selStep%9)+'   |   Default   English (USA)   100%';}"""
    sc = Scene("spreadsheet", f"{tname}/{font}/{fs}px/{ncols}cols/{speed}rps", width, height, 1.0,
               {"theme": tname, "font": font, "font_px": fs, "cols": ncols, "scroll_rows_per_s": speed, "jumps": len(jumps)})
    sc.html = _page(th, css, body, data, js)
    return sc


# ---------------------------------------------------------------------------------------- code editor

def code_editor(seed: int, width: int, height: int) -> Scene:
    rng = np.random.default_rng(seed)
    tname = _pick(rng, ["dark", "dark", "midnight", "light", "solar"])
    th, sy = THEMES[tname], SYNTAX[tname]
    files = C.own_source_files()
    f = files[int(rng.integers(len(files)))]
    lines = C.highlight_python(f.read_text(encoding="utf-8"))
    raw = f.read_text(encoding="utf-8").split("\n")
    type_src = files[int(rng.integers(len(files)))].read_text(encoding="utf-8").split("\n")
    k0 = int(rng.integers(0, max(1, len(type_src) - 40)))
    typed = [ln for ln in type_src[k0:k0 + 40] if ln.strip()][:12]
    font = _pick(rng, MONO)
    fs = int(rng.integers(12, 17))
    lh = int(round(fs * rng.uniform(1.35, 1.6)))
    tree = sorted({str(p.relative_to(files[0].parents[1])) for p in files})
    data = {"lines": lines, "raw": raw, "typed": typed, "lh": lh, "cursor": int(rng.integers(8, max(9, len(lines) - 10))),
            "cps": float(rng.uniform(9, 22)), "scroll": float(_pick(rng, [0.0, 0.0, 3.0, 8.0, 20.0])), "tree": tree,
            "fname": f.name, "showmini": bool(rng.random() < 0.85), "seed": int(rng.integers(1, 2**31))}
    syn = "".join(f".{k}{{color:{v}}}" for k, v in sy.items())
    css = f"""body{{font:{fs}px '{font}'}} {syn}
#side{{position:absolute;left:0;top:0;bottom:24px;width:250px;background:var(--panel);border-right:1px solid var(--line);font:{max(11, fs - 2)}px '{SANS[0]}';padding:8px 0;color:var(--muted)}}
#side div{{padding:2px 14px;white-space:nowrap}} #side .cur{{background:var(--sel);color:var(--fg)}}
#tabs{{position:absolute;left:250px;right:0;top:0;height:34px;background:var(--panel);border-bottom:1px solid var(--line);display:flex;font:{max(11, fs - 2)}px '{SANS[0]}'}}
#tabs div{{padding:9px 16px;border-right:1px solid var(--line);color:var(--muted)}} #tabs .on{{background:var(--bg);color:var(--fg)}}
#ed{{position:absolute;left:250px;top:34px;bottom:24px;right:{120}px;overflow:hidden}}
#code{{position:absolute;left:0;right:0}} .ln{{height:{lh}px;line-height:{lh}px;white-space:pre;display:flex}}
.no{{width:56px;text-align:right;padding-right:14px;color:var(--muted);flex:none}} .cl{{background:var(--sel)}}
.caret{{display:inline-block;width:2px;height:{lh - 4}px;background:var(--accent);vertical-align:middle}}
#mini{{position:absolute;right:0;top:34px;bottom:24px;width:120px;overflow:hidden;border-left:1px solid var(--line);background:var(--bg)}}
#mini .m{{font-size:2px;line-height:3px;height:3px;white-space:pre;transform-origin:0 0}}
#mview{{position:absolute;left:0;right:0;background:rgba(128,128,128,.18)}}
#st{{position:absolute;bottom:0;left:0;right:0;height:24px;background:var(--accent);color:#fff;font:{max(11, fs - 3)}px '{SANS[0]}';padding:4px 12px;display:flex;gap:24px}}"""
    body = """<div id="side"></div><div id="tabs"></div><div id="ed"><div id="code"></div></div><div id="mini"><div id="mc"></div><div id="mview"></div></div><div id="st"></div>"""
    js = """const S=document.getElementById('side'),CODE=document.getElementById('code'),ED=document.getElementById('ed');
S.innerHTML='<div style="font-weight:600;color:var(--fg)">EXPLORER</div>'+D.tree.map(p=>'<div class="'+(p.endsWith(D.fname)?'cur':'')+'">'+'&nbsp;&nbsp;'.repeat(p.split('/').length-1)+p.split('/').pop()+'</div>').join('');
document.getElementById('tabs').innerHTML='<div class="on">'+D.fname+'</div><div>README.md</div><div>degradation.yaml</div><div>test_pipeline.py</div>';
if(D.showmini){document.getElementById('mc').innerHTML=D.lines.map(l=>'<div class="m">'+l+'</div>').join('');}else{document.getElementById('mini').style.display='none';ED.style.right='0';}
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;');}
function renderFrame(t){const chars=Math.floor(t*D.cps);let left=chars,done=[],cur='';
 for(const ln of D.typed){if(left>=ln.length+1){done.push(ln);left-=ln.length+1;}else{cur=ln.slice(0,left);left=-1;break;}}
 const ins=done.map(x=>'<span class="id">'+esc(x)+'</span>');const caretOn=Math.floor(t*2)%2==0||left>=0;
 const curHtml='<span class="id">'+esc(cur)+'</span>'+(caretOn?'<span class="caret"></span>':'');
 const all=D.lines.slice(0,D.cursor).concat(ins,[curHtml],D.lines.slice(D.cursor));
 const vis=Math.ceil(ED.clientHeight/D.lh)+2;const curLine=D.cursor+ins.length;
 let pos=D.scroll>0?D.scroll*t:Math.max(0,curLine-Math.floor(vis*0.6));const first=Math.floor(pos),frac=pos-first;
 let h='';for(let i=0;i<vis;i++){const k=first+i;if(k>=all.length)break;h+='<div class="ln'+(k===curLine?' cl':'')+'"><span class="no">'+(k+1)+'</span><span>'+all[k]+'</span></div>';}
 CODE.innerHTML=h;CODE.style.top=(-frac*D.lh)+'px';
 const mv=document.getElementById('mview');mv.style.top=(first*3)+'px';mv.style.height=(vis*3)+'px';
 document.getElementById('st').innerHTML='<span>main*</span><span>Ln '+(curLine+1)+', Col '+(cur.length+1)+'</span><span>Spaces: 4</span><span>UTF-8</span><span>LF</span><span>Python 3.12</span>';}"""
    sc = Scene("code", f"{tname}/{font}/{fs}px/{f.name}", width, height, 1.0,
               {"theme": tname, "font": font, "font_px": fs, "file": f.name, "scroll_lines_per_s": data["scroll"], "minimap": data["showmini"]})
    sc.html = _page(th, css, body, data, js)
    return sc


# ---------------------------------------------------------------------------------------- terminal / logs

def terminal(seed: int, width: int, height: int) -> Scene:
    rng = np.random.default_rng(seed)
    tname = _pick(rng, ["dark", "midnight", "dark", "light"])
    th = THEMES[tname]
    font = _pick(rng, MONO)
    fs = int(rng.integers(12, 18))
    lh = int(round(fs * rng.uniform(1.2, 1.4)))
    t_start = float(rng.uniform(0, 80000))
    logs = [C.log_line(rng, t_start, i) for i in range(3000)]
    data = {"logs": logs, "lh": lh, "rate": float(_pick(rng, [6.0, 15.0, 35.0, 70.0, 140.0])), "split": bool(rng.random() < 0.35),
            "cmd": _pick(rng, ["tail -f /var/log/pipeline/worker.log", "python -m pipeline.run --resume --workers 8", "make test 2>&1 | tee build.log", "journalctl -fu ingest.service"]),
            "seed": int(rng.integers(1, 2**31))}
    css = f"""body{{font:{fs}px '{font}';}}
.pane{{position:absolute;top:0;bottom:0;overflow:hidden;padding:6px 10px}} .r{{height:{lh}px;line-height:{lh}px;white-space:pre}}
.ts{{color:var(--muted)}} .INFO{{color:var(--ok)}} .DEBUG{{color:var(--accent)}} .WARN{{color:var(--warn)}} .ERROR{{color:var(--err);font-weight:700}}
.cm{{color:var(--accent)}} .bar{{color:var(--fg)}} #b{{border-left:1px solid var(--line)}}"""
    body = """<div class="pane" id="a"></div><div class="pane" id="b"></div>"""
    js = """const A=document.getElementById('a'),B=document.getElementById('b');
if(D.split){A.style.left='0';A.style.right='50%';B.style.left='50%';B.style.right='0';}else{A.style.left='0';A.style.right='0';B.style.display='none';}
function row(l){return '<div class="r"><span class="ts">'+l.ts+'</span> <span class="'+l.level+'">'+l.level.padEnd(5)+'</span> ['+l.comp+'] '+l.msg+'</div>';}
function bar(t){const p=Math.min(100,(t*13)%100);const n=Math.floor(p/2.5);return '<div class="r bar">encoding  ['+'#'.repeat(n)+'.'.repeat(40-n)+'] '+p.toFixed(1).padStart(5)+'%  '+(120+t*37).toFixed(0)+' MB  eta '+Math.max(0,(100-p)/13).toFixed(1)+'s</div>';}
function pane(el,t,rate,off){const n=Math.floor(t*rate)+off+Math.floor((el.clientHeight-12)/D.lh);const vis=Math.floor((el.clientHeight-12)/D.lh)-2;
 const typed=Math.min(D.cmd.length,Math.floor(t*25));let h='<div class="r"><span class="cm">user@build:~/sn85$</span> '+D.cmd.slice(0,typed)+(Math.floor(t*2)%2?'':'█')+'</div>';
 const start=Math.max(0,n-vis);for(let i=start;i<n;i++)h+=row(D.logs[i%D.logs.length]);h+=bar(t);el.innerHTML=h;}
function renderFrame(t){pane(A,t,D.rate,4);if(D.split)pane(B,t,D.rate*0.37,40);}"""
    sc = Scene("terminal", f"{tname}/{font}/{fs}px/{data['rate']}lps", width, height, 1.0,
               {"theme": tname, "font": font, "font_px": fs, "lines_per_s": data["rate"], "split": data["split"]})
    sc.html = _page(th, css, body, data, js)
    return sc


# ---------------------------------------------------------------------------------------- dashboard

def dashboard(seed: int, width: int, height: int) -> Scene:
    rng = np.random.default_rng(seed)
    tname = _pick(rng, ["light", "dark", "midnight", "paper"])
    th = THEMES[tname]
    font = _pick(rng, SANS)
    fs = int(rng.integers(11, 15))
    nser = int(rng.integers(2, 5))
    series = []
    for _ in range(nser):  # random walks rescaled to 0..1 (each stays inside the plot)
        s = np.cumsum(rng.normal(0, 1, 2000))
        series.append(((s - s.min()) / max(1e-9, np.ptp(s)) * 0.8 + 0.1).round(4).tolist())
    trows = int(rng.integers(14, 22))
    kpi_defs = [("Throughput", " req/s", 200, 9000), ("Latency p95", " ms", 20, 900), ("Error rate", "%", 0.05, 4.0),
                ("Active users", " k", 1, 900), ("Revenue", " $k", 10, 5000), ("Queue depth", "", 0, 4000),
                ("Cache hit", "%", 60, 99.5), ("Uptime", "%", 99.0, 99.999), ("Open tickets", "", 3, 400), ("Disk used", " TB", 1, 80)]
    order = rng.permutation(len(kpi_defs))[: int(rng.integers(4, 7))]
    kpis = [{"label": kpi_defs[i][0], "unit": kpi_defs[i][1], "base": float(rng.uniform(kpi_defs[i][2], kpi_defs[i][3]))} for i in order]
    table = [[C.name(rng), _pick(rng, ["eu-west", "us-east", "ap-south", "sa-east"]), float(rng.uniform(0, 100)), int(rng.integers(10, 9999))] for _ in range(40)]
    bars = int(rng.integers(8, 24))
    data = {"series": series, "kpis": kpis, "table": table, "bars": bars, "trows": trows, "speed": float(_pick(rng, [4.0, 10.0, 25.0, 60.0])), "seed": int(rng.integers(1, 2**31))}
    css = f"""body{{font:{fs}px '{font}';background:var(--panel)}}
#top{{height:46px;display:flex;align-items:center;gap:22px;padding:0 18px;background:var(--bg);border-bottom:1px solid var(--line)}} #top b{{font-size:{fs + 4}px}}
#kp{{display:flex;gap:12px;padding:12px 16px}} .k{{flex:1;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:10px 12px}}
.k .v{{font-size:{fs + 14}px;font-weight:700;margin-top:4px}} .k .d{{font-size:{fs - 1}px}}
#charts{{display:grid;grid-template-columns:2fr 1fr;gap:12px;padding:0 16px}} .c{{background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:8px}}
.c h4{{margin:0 0 4px 0;font-size:{fs}px;color:var(--muted);font-weight:500}} svg text{{fill:var(--muted);font-size:{max(9, fs - 3)}px}}
#tbl{{margin:12px 16px;background:var(--bg);border:1px solid var(--line);border-radius:6px;overflow:hidden}}
table{{width:100%;border-collapse:collapse}} td,th{{padding:3px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}} th{{color:var(--muted);font-weight:500}}
.pill{{display:inline-block;height:8px;background:var(--accent);border-radius:4px;vertical-align:middle}}"""
    body = """<div id="top"><b>Operations overview</b><span>Last 24 h</span><span>Region: all</span><span>Refresh: live</span></div><div id="kp"></div>
<div id="charts"><div class="c"><h4>Requests per second by service</h4><svg id="lc"></svg></div><div class="c"><h4>Jobs by hour</h4><svg id="bc"></svg></div></div><div id="tbl"></div>"""
    js = """const COLS=['var(--accent)','var(--ok)','var(--warn)','var(--err)'];
function lineChart(svg,t){const W=svg.parentNode.clientWidth-16,H=Math.max(260,Math.round(window.innerHeight*0.30));svg.setAttribute('width',W);svg.setAttribute('height',H);
 const off=Math.floor(t*D.speed),n=160;let g='';for(let i=0;i<=5;i++){const y=20+i*(H-40)/5;g+='<line x1="40" x2="'+W+'" y1="'+y+'" y2="'+y+'" stroke="var(--line)" stroke-width="1"/><text x="2" y="'+(y+4)+'">'+(1000-i*200)+'</text>';}
 for(let i=0;i<8;i++){const x=40+i*(W-40)/8;g+='<text x="'+x+'" y="'+(H-4)+'">'+String((off/10+i*3)%24|0).padStart(2,'0')+':00</text>';}
 D.series.forEach((s,k)=>{let p='';for(let i=0;i<n;i++){const v=s[(off+i)%s.length];const x=40+i*(W-40)/(n-1),y=20+(1-v)*(H-44);p+=(i?'L':'M')+x.toFixed(1)+','+y.toFixed(1);}
  g+='<path d="'+p+'" fill="none" stroke="'+COLS[k%4]+'" stroke-width="1.3"/>';});svg.innerHTML=g;}
function barChart(svg,t){const W=svg.parentNode.clientWidth-16,H=Math.max(260,Math.round(window.innerHeight*0.30));svg.setAttribute('width',W);svg.setAttribute('height',H);const R=rnd(D.seed+Math.floor(t*3));let g='';
 for(let i=0;i<D.bars;i++){const v=0.2+0.8*R();const bw=(W-30)/D.bars;const h=v*(H-40);g+='<rect x="'+(24+i*bw)+'" y="'+(H-20-h)+'" width="'+(bw*0.7)+'" height="'+h+'" fill="var(--accent)" opacity="'+(0.55+0.4*v)+'"/><text x="'+(24+i*bw)+'" y="'+(H-6)+'">'+i+'</text>';}svg.innerHTML=g;}
function renderFrame(t){const R=rnd(D.seed+Math.floor(t*4));
 document.getElementById('kp').innerHTML=D.kpis.map(k=>{const d=(R()-0.5)*0.06;return '<div class="k"><div>'+k.label+'</div><div class="v">'+(k.unit==='%'?Math.min(99.999,k.base*(1+d)):k.base*(1+d)).toLocaleString('en-US',{maximumFractionDigits:k.unit==='%'?3:1})+k.unit+'</div><div class="d" style="color:'+(d>=0?'var(--ok)':'var(--err)')+'">'+(d>=0?'▲ ':'▼ ')+(Math.abs(d)*100).toFixed(2)+'% vs prev</div></div>';}).join('');
 lineChart(document.getElementById('lc'),t);barChart(document.getElementById('bc'),t);
 const off=Math.floor(t*2);let h='<table><tr><th>Owner</th><th>Region</th><th>Load</th><th>Jobs</th><th>Trend</th></tr>';
 for(let i=0;i<D.trows;i++){const r=D.table[(i+off)%D.table.length];const l=(r[2]+t*3*(i%3-1)+100)%100;h+='<tr><td>'+r[0]+'</td><td>'+r[1]+'</td><td>'+l.toFixed(1)+'%</td><td>'+(r[3]+Math.floor(t*(i+1))).toLocaleString('en-US')+'</td><td><span class="pill" style="width:'+(l*1.2).toFixed(0)+'px"></span></td></tr>';}
 document.getElementById('tbl').innerHTML=h+'</table>';}"""
    sc = Scene("dashboard", f"{tname}/{font}/{fs}px/{nser}series", width, height, 1.0,
               {"theme": tname, "font": font, "font_px": fs, "series": nser, "chart_speed": data["speed"]})
    sc.html = _page(th, css, body, data, js)
    return sc


# ---------------------------------------------------------------------------------------- documents / UI

def document(seed: int, width: int, height: int) -> Scene:
    """Scrolling document (landscape) or a phone-like reader/chat layout (portrait)."""
    rng = np.random.default_rng(seed)
    portrait = height > width
    tname = _pick(rng, ["light", "paper", "dark", "solar"])
    th = THEMES[tname]
    font = _pick(rng, SERIF + SANS)
    fs = int(rng.integers(13, 18)) if not portrait else int(rng.integers(14, 18))
    blocks = []
    for _ in range(60):
        r = rng.random()
        if r < 0.12:
            blocks.append({"h": C.sentence(rng, 3, 7).rstrip(".;:")})
        elif r < 0.2:
            blocks.append({"ul": [C.sentence(rng, 4, 10) for _ in range(int(rng.integers(3, 6)))]})
        elif r < 0.26:
            blocks.append({"tbl": [[C.name(rng), f"{rng.uniform(0, 1000):.2f}", f"{rng.uniform(-9, 9):+.1f}%"] for _ in range(int(rng.integers(4, 9)))]})
        elif portrait and r < 0.55:
            blocks.append({"msg": C.sentence(rng, 4, 16), "me": bool(rng.random() < 0.5)})
        else:
            blocks.append({"p": C.paragraph(rng)})
    # scroll: reading pace with occasional flicks (eased), in px/s
    flicks = sorted(float(x) for x in rng.uniform(0.3, 9.5, int(rng.integers(0, 4))))
    data = {"blocks": blocks, "speed": float(_pick(rng, [20.0, 45.0, 90.0, 180.0, 400.0])), "flicks": flicks,
            "flickpx": float(rng.uniform(300, 1200)), "portrait": portrait, "ui": bool((not portrait) and rng.random() < 0.4),
            "seed": int(rng.integers(1, 2**31))}
    colw = 760 if not portrait else 340
    css = f"""body{{font:{fs}px/1.55 '{font}'}}
#bar{{position:absolute;top:0;left:0;right:0;height:{44 if not portrait else 52}px;background:var(--panel);border-bottom:1px solid var(--line);display:flex;align-items:center;padding:0 16px;gap:{16 if not portrait else 10}px;z-index:3;font-family:'{SANS[0]}';font-size:{fs - 1 if not portrait else 13}px;white-space:nowrap;overflow:hidden}}
#doc{{position:absolute;top:{44 if not portrait else 52}px;left:0;right:0;bottom:0;overflow:hidden}}
#col{{position:absolute;left:50%;width:{colw}px;margin-left:-{colw // 2}px}} h2{{font-family:'{SANS[0]}';font-size:{fs + 7}px;margin:26px 0 8px}}
p{{margin:0 0 12px}} ul{{margin:0 0 12px 18px;padding:0}} table{{border-collapse:collapse;margin:6px 0 14px;font-family:'{MONO[0]}';font-size:{fs - 2}px}}
td{{border:1px solid var(--line);padding:2px 8px}} .msg{{max-width:78%;padding:8px 12px;border-radius:14px;margin:6px 0;background:var(--panel)}}
.me{{margin-left:auto;background:var(--accent);color:#fff}} .row{{display:flex}}
#ui{{position:absolute;right:24px;top:70px;width:380px;background:var(--bg);border:1px solid var(--line);border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.18);padding:12px;z-index:4;font-family:'{SANS[0]}';font-size:{fs - 1}px}}
.tg{{display:flex;justify-content:space-between;align-items:center;padding:7px 4px;border-bottom:1px solid var(--line)}}
.sw{{width:38px;height:20px;border-radius:10px;background:var(--line);position:relative}} .sw i{{position:absolute;top:2px;width:16px;height:16px;border-radius:8px;background:#fff}}"""
    body = ("""<div id="bar"><b>Notes</b><span>Edit</span><span id="pg"></span></div>""" if portrait else
            """<div id="bar"><b>Field notes — draft 7</b><span>Edit</span><span>View</span><span>Comments (12)</span><span id="pg"></span></div>""") + """<div id="doc"><div id="col"></div></div><div id="ui"></div>"""
    js = """const COL=document.getElementById('col');
COL.innerHTML=D.blocks.map(b=>b.h?'<h2>'+b.h+'</h2>':b.ul?'<ul>'+b.ul.map(x=>'<li>'+x+'</li>').join('')+'</ul>':b.tbl?'<table>'+b.tbl.map(r=>'<tr>'+r.map(c=>'<td>'+c+'</td>').join('')+'</tr>').join('')+'</table>':b.msg?'<div class="row"><div class="msg'+(b.me?' me':'')+'">'+b.msg+'</div></div>':'<p>'+b.p+'</p>').join('');
const UI=document.getElementById('ui');if(!D.ui)UI.style.display='none';
const labels=['Sync automatically','Show line numbers','Compact density','High-contrast mode','Spell check','Track changes','Smart quotes','Autosave every minute'];
function renderFrame(t){let y=D.speed*t;D.flicks.forEach(f=>{y+=D.flickpx*ease((t-f)/0.45);});const maxy=COL.scrollHeight-400;y=y%Math.max(1,maxy);
 COL.style.top=(-y)+'px';document.getElementById('pg').textContent='Page '+(1+Math.floor(y/900))+' of '+(1+Math.floor(maxy/900));
 if(D.ui){const R=rnd(D.seed);const a=ease((t%3.2)/0.5)*(1-ease(((t%3.2)-2.6)/0.5));UI.style.opacity=a.toFixed(3);UI.style.transform='translateY('+((1-a)*-30).toFixed(1)+'px) scale('+(0.96+0.04*a).toFixed(3)+')';
  UI.innerHTML='<b>Preferences</b>'+labels.map((l,i)=>{const on=((Math.floor(t*1.5)+i)%3)==0;const k=ease(((t*1.5)%1)/0.4);const x=on?2+18*k:20-18*k;return '<div class="tg"><span>'+l+'</span><span class="sw" style="background:'+(on?'var(--accent)':'var(--line)')+'"><i style="left:'+x.toFixed(1)+'px"></i></span></div>';}).join('');}}"""
    sc = Scene("document", f"{'phone' if portrait else ('ui' if data['ui'] else 'doc')}/{tname}/{font}/{fs}px/{data['speed']}pxps",
               width, height, 3.0 if portrait else 1.0,
               {"theme": tname, "font": font, "font_px": fs, "scroll_px_per_s": data["speed"], "flicks": len(flicks), "ui_overlay": data["ui"], "portrait": portrait})
    sc.html = _page(th, css, body, data, js)
    return sc


# ---------------------------------------------------------------------------------------- Phase B layouts

def notebook(seed: int, width: int, height: int) -> Scene:
    """Jupyter-like notebook: code cells (syntax-highlighted own source), numeric output tables
    and small SVG plots; scrolls and 'executes' cells (counter + spinner)."""
    rng = np.random.default_rng(seed)
    tname = _pick(rng, ["light", "light", "dark", "paper", "midnight"])
    th, sy = THEMES[tname], SYNTAX[tname]
    font = _pick(rng, MONO)
    fs = int(rng.integers(11, 15))
    files = C.own_source_files()
    cells = []
    for i in range(24):
        f = files[int(rng.integers(len(files)))]
        hl = C.highlight_python(f.read_text(encoding="utf-8"))
        k0 = int(rng.integers(0, max(1, len(hl) - 14)))
        code = [l for l in hl[k0:k0 + int(rng.integers(4, 14))]]
        r = rng.random()
        if r < 0.4:
            out = {"tbl": [[f"{rng.normal(0, 1):.4f}" for _ in range(int(rng.integers(4, 9)))] for _ in range(int(rng.integers(4, 10)))]}
        elif r < 0.75:
            ys = np.cumsum(rng.normal(0, 1, 120))
            out = {"plot": ((ys - ys.min()) / max(1e-9, np.ptp(ys))).round(3).tolist(), "scatter": bool(rng.random() < 0.4)}
        else:
            out = {"txt": [C.sentence(rng, 3, 10) for _ in range(int(rng.integers(1, 4)))]}
        cells.append({"code": code, "out": out})
    data = {"cells": cells, "speed": float(_pick(rng, [25.0, 60.0, 120.0, 260.0])), "seed": int(rng.integers(1, 2**31)), "fs": fs}
    syn = "".join(f".{k}{{color:{v}}}" for k, v in sy.items())
    css = f"""body{{font:{fs}px '{SANS[0]}'}} {syn}
#top{{height:56px;background:var(--panel);border-bottom:1px solid var(--line);display:flex;align-items:center;gap:18px;padding:0 16px;color:var(--muted)}}
#side{{position:absolute;left:0;top:56px;bottom:0;width:220px;border-right:1px solid var(--line);background:var(--panel);padding:8px;color:var(--muted);font-size:{fs - 1}px}}
#nb{{position:absolute;left:220px;right:0;top:56px;bottom:0;overflow:hidden}} #in{{position:absolute;left:40px;right:60px}}
.cell{{display:flex;margin:10px 0}} .pr{{width:70px;color:var(--muted);font-family:'{font}';flex:none;text-align:right;padding-right:8px}}
.src{{flex:1;background:var(--panel);border:1px solid var(--line);border-radius:3px;padding:6px 8px;font-family:'{font}';white-space:pre;overflow:hidden}}
.out{{flex:1;padding:4px 8px;font-family:'{font}';font-size:{fs - 1}px}} .run{{border-left:3px solid var(--accent)}}
table{{border-collapse:collapse}} td,th{{padding:1px 8px;text-align:right;border-bottom:1px solid var(--line)}} th{{color:var(--muted)}}
svg text{{fill:var(--muted);font-size:10px}}"""
    body = """<div id="top"><b>analysis.ipynb</b><span>File</span><span>Edit</span><span>View</span><span>Run</span><span>Kernel</span><span id="kn"></span></div>
<div id="side"></div><div id="nb"><div id="in"></div></div>"""
    js = """const IN=document.getElementById('in');
document.getElementById('side').innerHTML=['data/','notebooks/','analysis.ipynb','calibration.ipynb','features.parquet','README.md','splits.json','report.html'].map(x=>'<div style="padding:3px 6px">'+x+'</div>').join('');
function plot(o,w,h){let p='';const n=o.plot.length;let g='<svg width="'+w+'" height="'+h+'">';for(let i=0;i<=4;i++){const y=10+i*(h-30)/4;g+='<line x1="34" x2="'+w+'" y1="'+y+'" y2="'+y+'" stroke="var(--line)"/><text x="0" y="'+(y+3)+'">'+(1-i/4).toFixed(2)+'</text>';}
 for(let i=0;i<n;i++){const x=34+i*(w-40)/(n-1),y=10+(1-o.plot[i])*(h-30);if(o.scatter)g+='<circle cx="'+x.toFixed(1)+'" cy="'+y.toFixed(1)+'" r="1.6" fill="var(--accent)"/>';else p+=(i?'L':'M')+x.toFixed(1)+','+y.toFixed(1);}
 if(!o.scatter)g+='<path d="'+p+'" fill="none" stroke="var(--accent)" stroke-width="1.2"/>';return g+'</svg>';}
IN.innerHTML=D.cells.map((c,i)=>'<div class="cell"><div class="pr">In ['+(i+1)+']:</div><div class="src" id="s'+i+'">'+c.code.join('\\n')+'</div></div>'+
 '<div class="cell"><div class="pr">Out['+(i+1)+']:</div><div class="out">'+(c.out.tbl?'<table><tr>'+c.out.tbl[0].map((_,j)=>'<th>c'+j+'</th>').join('')+'</tr>'+c.out.tbl.map(r=>'<tr>'+r.map(v=>'<td>'+v+'</td>').join('')+'</tr>').join('')+'</table>':c.out.plot?plot(c.out,520,190):c.out.txt.map(x=>'<div>'+x+'</div>').join(''))+'</div></div>').join('');
function renderFrame(t){const y=D.speed*t;IN.style.top=(-y%Math.max(1,IN.scrollHeight-600))+'px';const k=Math.floor(t*0.8)%D.cells.length;
 for(let i=0;i<D.cells.length;i++)document.getElementById('s'+i).className='src'+(i===k?' run':'');
 document.getElementById('kn').textContent='Python 3 (ipykernel) '+(['◐','◓','◑','◒'][Math.floor(t*6)%4])+' busy';}"""
    sc = Scene("code", f"notebook/{tname}/{font}/{fs}px", width, height, 1.0, {"layout": "notebook", "theme": tname, "font": font, "font_px": fs, "scroll_px_per_s": data["speed"]})
    sc.html = _page(th, css, body, data, js)
    return sc


def sysmon(seed: int, width: int, height: int) -> Scene:
    """htop-like terminal monitor: per-core meters, memory bars and a sorted process table."""
    rng = np.random.default_rng(seed)
    tname = _pick(rng, ["dark", "midnight", "dark", "light"])
    th = THEMES[tname]
    font = _pick(rng, MONO)
    fs = int(rng.integers(11, 16))
    lh = int(round(fs * 1.25))
    cores = int(_pick(rng, [8, 16, 24, 32, 48, 64]))
    procs = [{"pid": int(rng.integers(100, 99999)), "user": _pick(rng, ["root", "build", "www", "postgres", "ml", "ci"]),
              "cmd": _pick(rng, ["python -m train --cfg a.yaml", "ffmpeg -i in.mkv -c:v libx265", "postgres: writer", "nginx: worker process",
                                 "node server.js", "rsync -a data/ backup/", "gcc -O2 -c module.c", "java -jar app.jar", "redis-server *:6379",
                                 "make -j16", "blender -b scene.blend -a", "sshd: build@pts/3", "chrome --type=renderer", "dockerd", "cargo build --release"]),
              "base": float(rng.gamma(1.2, 6.0)), "mem": float(rng.gamma(1.5, 1.2))} for _ in range(120)]
    data = {"procs": procs, "cores": cores, "lh": lh, "seed": int(rng.integers(1, 2**31)), "rate": float(_pick(rng, [2.0, 4.0, 10.0]))}
    css = f"""body{{font:{fs}px '{font}'}} .r{{height:{lh}px;line-height:{lh}px;white-space:pre}}
#m{{padding:6px 10px;display:grid;grid-template-columns:repeat({2 if cores <= 16 else 4},1fr);column-gap:22px}}
.g{{color:var(--ok)}} .y{{color:var(--warn)}} .rd{{color:var(--err)}} .c{{color:var(--accent)}} .mu{{color:var(--muted)}}
#hd{{background:var(--ok);color:var(--bg);padding:0 10px}} #pt{{padding:0 10px}} .sel{{background:var(--sel)}}
#fk{{position:absolute;bottom:0;left:0;right:0;background:var(--panel);padding:0 10px}}"""
    body = """<div id="m"></div><div id="sum" style="padding:0 10px"></div><div class="r" id="hd"></div><div id="pt"></div><div class="r" id="fk"></div>"""
    js = """function bar(p,w){const n=Math.round(p/100*w);const a=Math.round(n*0.6),b=Math.round(n*0.3),c=n-a-b;return '[<span class="g">'+'|'.repeat(a)+'</span><span class="y">'+'|'.repeat(Math.max(0,b))+'</span><span class="rd">'+'|'.repeat(Math.max(0,c))+'</span>'+' '.repeat(Math.max(0,w-n))+'<span class="mu">'+p.toFixed(1).padStart(5)+'%</span>]';}
function renderFrame(t){const R=rnd(D.seed+Math.floor(t*D.rate));let m='';for(let i=0;i<D.cores;i++){const p=Math.min(100,Math.abs(30+40*Math.sin(t*0.7+i)+R()*45));m+='<div class="r"><span class="c">'+String(i).padStart(3)+'</span>'+bar(p,D.cores<=16?48:22)+'</div>';}
 document.getElementById('m').innerHTML=m;const mem=40+20*Math.sin(t*0.3);document.getElementById('sum').innerHTML='<div class="r"><span class="c">Mem</span>'+bar(mem,60)+' '+(mem*2.56).toFixed(1)+'G/256G   <span class="c">Tasks:</span> '+(412+Math.floor(t*3)%40)+', 1893 thr; <span class="c">Load average:</span> '+(18+R()*4).toFixed(2)+' '+(17.5+R()).toFixed(2)+' 16.9   <span class="c">Uptime:</span> 32 days, 11:'+String(17+Math.floor(t/60)).padStart(2,'0')+':'+String(Math.floor(t)%60).padStart(2,'0')+'</div>';
 document.getElementById('hd').textContent='    PID USER      PRI  NI  VIRT   RES   SHR S CPU% MEM%   TIME+  Command';
 const rows=D.procs.map(p=>({...p,cpu:Math.max(0,p.base*(0.5+R()*1.2))})).sort((a,b)=>b.cpu-a.cpu);const vis=Math.floor((window.innerHeight-document.getElementById('pt').offsetTop-20)/D.lh);
 const sel=Math.floor(t*1.3)%Math.max(1,vis);document.getElementById('pt').innerHTML=rows.slice(0,vis).map((p,i)=>'<div class="r'+(i===sel?' sel':'')+'">'+String(p.pid).padStart(7)+' '+p.user.padEnd(9)+' 20   0 '+(p.mem*900).toFixed(0).padStart(5)+'M '+(p.mem*300).toFixed(0).padStart(4)+'M '+(p.mem*40).toFixed(0).padStart(4)+'M '+(p.cpu>5?'R':'S')+' '+p.cpu.toFixed(1).padStart(4)+' '+p.mem.toFixed(1).padStart(4)+' '+(Math.floor(p.base*30+t)+':'+String(Math.floor(t*7+p.pid)%60).padStart(2,'0')).padStart(7)+'  '+p.cmd+'</div>').join('');
 document.getElementById('fk').innerHTML='<span class="c">F1</span>Help <span class="c">F2</span>Setup <span class="c">F3</span>Search <span class="c">F4</span>Filter <span class="c">F5</span>Tree <span class="c">F6</span>SortBy <span class="c">F9</span>Kill <span class="c">F10</span>Quit';}"""
    sc = Scene("terminal", f"sysmon/{tname}/{font}/{fs}px/{cores}cores", width, height, 1.0, {"layout": "sysmon", "theme": tname, "font": font, "font_px": fs, "cores": cores})
    sc.html = _page(th, css, body, data, js)
    return sc


def multiples(seed: int, width: int, height: int) -> Scene:
    """Monitoring wall: grid of small-multiple time-series panels with thin lines, dense axis
    labels, a status heatmap and a scrolling alert list."""
    rng = np.random.default_rng(seed)
    tname = _pick(rng, ["dark", "midnight", "light", "paper"])
    th = THEMES[tname]
    font = _pick(rng, SANS)
    fs = int(rng.integers(10, 14))
    cols = int(_pick(rng, [3, 4, 4, 5])) if width > height else 2
    rows = int(_pick(rng, [2, 3, 3])) if width > height else 5
    panels = []
    for i in range(cols * rows):
        k = int(rng.integers(1, 4))
        ser = []
        for _ in range(k):
            s = np.cumsum(rng.normal(0, 1, 1500)) + rng.normal(0, 0.5, 1500).cumsum() * 0.1
            ser.append(((s - s.min()) / max(1e-9, np.ptp(s)) * 0.8 + 0.1).round(3).tolist())
        panels.append({"title": f"{_pick(rng, ['cpu', 'mem', 'net.rx', 'net.tx', 'disk.io', 'gc.pause', 'queue', 'p99', 'errors', 'qps'])}.{_pick(rng, ['api', 'db', 'cache', 'worker', 'edge'])}-{int(rng.integers(1, 40)):02d}", "ser": ser,
                       "unit": _pick(rng, ["%", "ms", "MB/s", "req/s", "ops"]), "max": float(_pick(rng, [1, 10, 100, 1000, 5000]))})
    heat = rng.random((12, 48)).round(3).tolist()
    data = {"panels": panels, "cols": cols, "heat": heat, "speed": float(_pick(rng, [3.0, 8.0, 20.0])), "seed": int(rng.integers(1, 2**31))}
    css = f"""body{{font:{fs}px '{font}'}} #g{{position:absolute;left:8px;right:8px;top:40px;display:grid;grid-template-columns:repeat({cols},1fr);gap:8px}}
#top{{height:34px;display:flex;gap:20px;align-items:center;padding:0 12px;border-bottom:1px solid var(--line);color:var(--muted)}}
.p{{border:1px solid var(--line);border-radius:4px;padding:4px;background:var(--panel)}} .p h5{{margin:0;font-size:{fs}px;font-weight:600;display:flex;justify-content:space-between}}
svg text{{fill:var(--muted);font-size:{max(8, fs - 3)}px}} #hm{{position:absolute;left:8px;right:8px;bottom:8px}}"""
    body = """<div id="top"><b style="color:var(--fg)">infra / overview</b><span>last 15 minutes</span><span>auto-refresh 5s</span><span id="clk"></span></div><div id="g"></div><svg id="hm"></svg>"""
    js = """const G=document.getElementById('g');const COLS=['var(--accent)','var(--ok)','var(--warn)'];
G.innerHTML=D.panels.map((p,i)=>'<div class="p"><h5><span>'+p.title+'</span><span id="v'+i+'"></span></h5><svg id="p'+i+'"></svg></div>').join('');
function renderFrame(t){const off=Math.floor(t*D.speed);const W=G.clientWidth/D.cols-14;const rows=Math.ceil(D.panels.length/D.cols);const H=Math.max(90,(window.innerHeight-40-190)/rows-30);
 D.panels.forEach((p,i)=>{const n=120;let g='';for(let j=0;j<=3;j++){const y=6+j*(H-18)/3;g+='<line x1="30" x2="'+W+'" y1="'+y+'" y2="'+y+'" stroke="var(--line)"/><text x="0" y="'+(y+3)+'">'+(p.max*(1-j/3)).toFixed(0)+'</text>';}
  for(let j=0;j<6;j++){const x=30+j*(W-30)/6;g+='<text x="'+x+'" y="'+(H-1)+'">-'+(15-j*2.5).toFixed(1)+'m</text>';}
  p.ser.forEach((s,k)=>{let d='';for(let j=0;j<n;j++){const v=s[(off+j)%s.length];d+=(j?'L':'M')+(30+j*(W-30)/(n-1)).toFixed(1)+','+(6+(1-v)*(H-18)).toFixed(1);}g+='<path d="'+d+'" fill="none" stroke="'+COLS[k]+'" stroke-width="1"/>';});
  const s=document.getElementById('p'+i);s.setAttribute('width',W);s.setAttribute('height',H);s.innerHTML=g;document.getElementById('v'+i).textContent=(p.ser[0][(off+n-1)%p.ser[0].length]*p.max).toFixed(1)+' '+p.unit;});
 const hm=document.getElementById('hm');const HW=G.clientWidth,HH=170;hm.setAttribute('width',HW);hm.setAttribute('height',HH);let h='';const cw=(HW-60)/48,ch=(HH-10)/12;
 for(let r=0;r<12;r++){h+='<text x="0" y="'+(r*ch+ch*0.8)+'">node'+String(r+1).padStart(2,'0')+'</text>';for(let c=0;c<48;c++){const v=D.heat[r][(c+off)%48];const col=v>0.92?'var(--err)':v>0.75?'var(--warn)':'var(--ok)';h+='<rect x="'+(60+c*cw)+'" y="'+(r*ch)+'" width="'+(cw-1)+'" height="'+(ch-1)+'" fill="'+col+'" opacity="'+(0.35+0.6*v).toFixed(2)+'"/>';}}
 hm.innerHTML=h;document.getElementById('clk').textContent='12:'+String(30+Math.floor(t/60)).padStart(2,'0')+':'+String(Math.floor(t)%60).padStart(2,'0')+' UTC';}"""
    sc = Scene("dashboard", f"multiples/{tname}/{font}/{fs}px/{cols}x{rows}", width, height, 1.0, {"layout": "small_multiples", "theme": tname, "font": font, "font_px": fs, "grid": [cols, rows]})
    sc.html = _page(th, css, body, data, js)
    return sc


def mail(seed: int, width: int, height: int) -> Scene:
    """Three-pane mail/messaging client: folders, a message list whose selection moves, and a
    reading pane that scrolls; unread bold rows, small timestamps, avatars."""
    rng = np.random.default_rng(seed)
    tname = _pick(rng, ["light", "light", "dark", "solar", "paper"])
    th = THEMES[tname]
    font = _pick(rng, SANS)
    fs = int(rng.integers(12, 15))
    msgs = [{"from": C.name(rng), "subj": C.sentence(rng, 3, 9).rstrip("."), "snip": C.sentence(rng, 6, 14), "time": f"{int(rng.integers(7, 19)):02d}:{int(rng.integers(0, 60)):02d}",
             "unread": bool(rng.random() < 0.35), "col": f"hsl({int(rng.integers(0, 360))},55%,55%)", "body": [C.paragraph(rng) for _ in range(int(rng.integers(3, 8)))]} for _ in range(80)]
    data = {"msgs": msgs, "step": float(rng.uniform(0.6, 1.6)), "speed": float(_pick(rng, [30.0, 70.0, 140.0])), "seed": int(rng.integers(1, 2**31))}
    css = f"""body{{font:{fs}px '{font}'}} #f{{position:absolute;left:0;top:0;bottom:0;width:200px;background:var(--panel);border-right:1px solid var(--line);padding:10px 0}}
#f div{{padding:5px 16px;color:var(--muted)}} #f .on{{background:var(--sel);color:var(--fg);font-weight:600}}
#l{{position:absolute;left:200px;top:0;bottom:0;width:{min(520, width // 3)}px;border-right:1px solid var(--line);overflow:hidden}}
.m{{display:flex;gap:10px;padding:8px 12px;border-bottom:1px solid var(--line);height:64px;overflow:hidden}} .m.sel{{background:var(--sel)}}
.av{{width:32px;height:32px;border-radius:16px;flex:none;color:#fff;text-align:center;line-height:32px;font-weight:700}}
.m .t{{color:var(--muted);font-size:{fs - 2}px;margin-left:auto}} .m .s{{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}} .u{{font-weight:700}}
#r{{position:absolute;left:{200 + min(520, width // 3)}px;right:0;top:0;bottom:0;overflow:hidden;padding:0 28px}} #rb{{position:absolute;left:28px;right:28px}}
#r h2{{font-size:{fs + 8}px;margin:18px 0 6px}} #r p{{line-height:1.55;margin:0 0 12px}}"""
    body = """<div id="f"></div><div id="l"><div id="li" style="position:absolute;left:0;right:0"></div></div><div id="r"><div id="rb"></div></div>"""
    js = """document.getElementById('f').innerHTML=['Inbox (24)','Starred','Snoozed','Sent','Drafts (3)','Archive','Spam','Trash','— Labels','builds','invoices','team','travel'].map((x,i)=>'<div class="'+(i===0?'on':'')+'">'+x+'</div>').join('');
function renderFrame(t){const sel=Math.floor(t/D.step)%D.msgs.length;const vis=Math.floor(document.getElementById('l').clientHeight/65);const top=Math.max(0,sel-Math.floor(vis/2));
 document.getElementById('li').style.top=(-top*65)+'px';document.getElementById('li').innerHTML=D.msgs.map((m,i)=>'<div class="m'+(i===sel?' sel':'')+'"><div class="av" style="background:'+m.col+'">'+m.from[0]+'</div><div style="min-width:0;flex:1"><div style="display:flex"><span class="'+(m.unread&&i>sel?'u':'')+'">'+m.from+'</span><span class="t">'+m.time+'</span></div><div class="s '+(m.unread&&i>sel?'u':'')+'">'+m.subj+'</div><div class="s" style="color:var(--muted)">'+m.snip+'</div></div></div>').join('');
 const m=D.msgs[sel];const lt=t-Math.floor(t/D.step)*D.step;const rb=document.getElementById('rb');rb.innerHTML='<h2>'+m.subj+'</h2><div style="color:var(--muted);margin-bottom:14px">'+m.from+' &lt;'+m.from.toLowerCase().replace(/[^a-z]/g,'.')+'@example.org&gt; · '+m.time+'</div>'+m.body.map(p=>'<p>'+p+'</p>').join('');rb.style.top=(-lt*D.speed)+'px';}"""
    sc = Scene("document", f"mail/{tname}/{font}/{fs}px", width, height, 1.0, {"layout": "mail_client", "theme": tname, "font": font, "font_px": fs, "select_every_s": data["step"]})
    sc.html = _page(th, css, body, data, js)
    return sc


def ledger(seed: int, width: int, height: int) -> Scene:
    """Financial ledger sheet: frozen header with merged group headers, conditional-format cell
    colours, in-cell bars, totals rows; values recalculate in waves and the view pans."""
    rng = np.random.default_rng(seed)
    tname = _pick(rng, ["light", "paper", "light", "dark"])
    th = THEMES[tname]
    font = _pick(rng, SANS + MONO[:1])
    fs = int(rng.integers(9, 13))
    rowh = fs + int(rng.integers(5, 8))
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    groups = int(rng.integers(3, 6))
    accounts = [f"{int(rng.integers(1000, 9999))} {C.name(rng)}" for _ in range(300)]
    vals = (rng.gamma(2, 3000, (300, 12 * groups)) * rng.choice([-1, 1], (300, 12 * groups), p=[0.15, 0.85])).round(2).tolist()
    data = {"acc": accounts, "vals": vals, "groups": groups, "months": months, "rowh": rowh, "seed": int(rng.integers(1, 2**31)),
            "vspeed": float(_pick(rng, [0.0, 3.0, 8.0, 18.0])), "hspeed": float(_pick(rng, [0.0, 0.0, 20.0, 60.0]))}
    css = f"""body{{font:{fs}px '{font}'}} #wrap{{position:absolute;top:30px;left:0;right:0;bottom:0;overflow:hidden}}
#tb{{height:30px;background:var(--panel);border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:center;padding:0 10px;color:var(--muted)}}
table{{border-collapse:collapse;table-layout:fixed;position:absolute}} td,th{{border:1px solid var(--line);height:{rowh}px;padding:0 3px;white-space:nowrap;overflow:hidden;text-align:right}}
th{{background:var(--panel);font-weight:600}} td.a{{text-align:left;background:var(--panel)}} .neg{{color:var(--err)}} .hi{{background:rgba(26,127,55,.18)}} .lo{{background:rgba(207,34,46,.16)}}
.bar{{display:inline-block;height:{max(3, rowh - 8)}px;background:var(--accent);opacity:.45;vertical-align:middle;margin-right:3px}} tr.tot td{{font-weight:700;border-top:2px solid var(--fg)}}"""
    body = """<div id="tb"><b style="color:var(--fg)">ledger_2026.xlsx</b><span>Sheet: Consolidated</span><span id="cell"></span><span id="calc"></span></div><div id="wrap"><table id="t"></table></div>"""
    js = """const T=document.getElementById('t');const cw=Math.round(D.rowh*4.6);
function renderFrame(t){const R=rnd(D.seed+Math.floor(t*2));const r0=Math.floor(t*D.vspeed),c0=Math.floor(t*D.hspeed/cw);const vis=Math.ceil(window.innerHeight/D.rowh)+2;const ncols=Math.ceil(window.innerWidth/cw)+2;
 let h='<tr><th style="width:'+(cw*2.4)+'px" rowspan="2">Account</th>';for(let g=0;g<Math.ceil(ncols/12)+1;g++)h+='<th colspan="12">FY'+(2024+((g+Math.floor(c0/12))%D.groups))+'</th>';h+='</tr><tr>';
 for(let c=0;c<ncols;c++)h+='<th style="width:'+cw+'px">'+D.months[(c+c0)%12]+'</th>';h+='</tr>';const wave=(t*6)%vis;
 for(let i=0;i<vis;i++){const r=(i+r0)%D.acc.length;const tot=(r%17)===16;h+='<tr'+(tot?' class="tot"':'')+'><td class="a">'+(tot?'Subtotal':D.acc[r])+'</td>';
  for(let c=0;c<ncols;c++){let v=D.vals[r][(c+c0)%D.vals[r].length];if(Math.abs(i-wave)<1.5)v*=1+(R()-0.5)*0.1;const cls=(v<0?'neg ':'')+(v>9000?'hi':v<-2000?'lo':'');const bar=(c%5===4)?'<span class="bar" style="width:'+Math.min(cw-40,Math.abs(v)/400).toFixed(0)+'px"></span>':'';
   h+='<td class="'+cls+'">'+bar+v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})+'</td>';}h+='</tr>';}
 T.innerHTML=h;T.style.left=(-(t*D.hspeed)%cw)+'px';document.getElementById('cell').textContent='R'+(r0+3)+'C'+(c0+2);document.getElementById('calc').textContent=Math.floor(t*3)%4?'Ready':'Calculating (4 threads)...';}"""
    sc = Scene("spreadsheet", f"ledger/{tname}/{font}/{fs}px", width, height, 1.0, {"layout": "ledger", "theme": tname, "font": font, "font_px": fs,
                                                                                 "rows_per_s": data["vspeed"], "pan_px_per_s": data["hspeed"]})
    sc.html = _page(th, css, body, data, js)
    return sc


BUILDERS = {"spreadsheet": spreadsheet, "code": code_editor, "terminal": terminal, "dashboard": dashboard, "document": document,
            "notebook": notebook, "sysmon": sysmon, "multiples": multiples, "mail": mail, "ledger": ledger}
