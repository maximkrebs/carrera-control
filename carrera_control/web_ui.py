"""Small local monitoring UI for training and autonomous driving."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from typing import Any
from urllib.parse import urlsplit


@dataclass
class WebState:
    """Thread-safe enough state snapshot for the local read-only dashboard."""

    data: dict[str, Any] = field(default_factory=dict)
    frame_jpeg: bytes = b""
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def update(self, **values: Any) -> None:
        with self._lock:
            self.data.update(values)

    def update_frame(self, frame: Any) -> None:
        import cv2

        success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if success:
            with self._lock:
                self.frame_jpeg = encoded.tobytes()

    def snapshot(self) -> tuple[dict[str, Any], bytes]:
        with self._lock:
            return dict(self.data), self.frame_jpeg


def start_web_ui(state: WebState, port: int = 8090) -> ThreadingHTTPServer:
    """Start the local dashboard in a daemon thread and return its server."""
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535.")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            data, frame = state.snapshot()
            request_path = urlsplit(self.path).path
            if request_path == "/api/status":
                payload = json.dumps(data).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if request_path == "/frame.jpg":
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(frame)))
                self.end_headers()
                self.wfile.write(frame)
                return
            page = """<!doctype html><meta charset='utf-8'><title>Carrera AI</title>
<style>body{font:16px sans-serif;background:#111;color:#eee;margin:2rem}img{max-width:100%;border:1px solid #555}canvas{display:block;width:min(100%,900px);height:auto;background:#191919;border:1px solid #555;margin-top:1rem}pre{background:#222;padding:1rem}</style>
<h1>Carrera AI</h1><section id='laps'></section><section id='problems'><h2>Gefahrenstellen</h2><div id='problem-list'>Keine Vorfälle</div></section><img id='frame'><canvas id='map' width='900' height='600'></canvas><canvas id='profile' width='900' height='300'></canvas><pre id='status'>loading...</pre>
<script>
const canvas=document.getElementById('map'),ctx=canvas.getContext('2d');
const profileCanvas=document.getElementById('profile'),profileCtx=profileCanvas.getContext('2d');
function drawMap(x){const nodes=x.track_nodes||[],spots=x.problem_spots||[],danger=x.danger_segments||[];ctx.clearRect(0,0,canvas.width,canvas.height);if(!nodes.length)return;let xs=nodes.map(p=>p[0]),ys=nodes.map(p=>p[1]),minx=Math.min(...xs),maxx=Math.max(...xs),miny=Math.min(...ys),maxy=Math.max(...ys),scale=Math.min(820/(maxx-minx||1),520/(maxy-miny||1)),tx=p=>40+(p[0]-minx)*scale,ty=p=>40+(p[1]-miny)*scale;ctx.strokeStyle='#58a6ff';ctx.lineWidth=4;ctx.beginPath();nodes.forEach((p,i)=>i?ctx.lineTo(tx(p),ty(p)):ctx.moveTo(tx(p),ty(p)));ctx.closePath();ctx.stroke();const all=[...spots,...danger];all.forEach(s=>{ctx.fillStyle='#ff4d4d';ctx.beginPath();ctx.arc(tx([s.x,s.y]),ty([s.x,s.y]),9,0,Math.PI*2);ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.stroke();ctx.fillStyle='#fff';ctx.font='bold 12px sans-serif';ctx.fillText((s.count||1)+'x',tx([s.x,s.y])+12,ty([s.x,s.y])+4)})}
function drawProfile(x){const stages=x.profile_stages||[],changes=x.profile_changes||[],crashes=x.profile_crashes||[];profileCtx.clearRect(0,0,profileCanvas.width,profileCanvas.height);if(!stages.length)return;const width=profileCanvas.width/stages.length,scale=220/15;stages.forEach((value,i)=>{const h=value*scale;profileCtx.fillStyle=crashes[i]?'#ff5c5c':changes[i]>0?'#57d68d':'#58a6ff';profileCtx.fillRect(i*width+2,250-h,width-4,h);profileCtx.fillStyle='#eee';profileCtx.font='10px sans-serif';profileCtx.fillText(i+1,i*width+3,270);profileCtx.fillText(Math.round(value),i*width+3,245-h);if(changes[i]){profileCtx.fillStyle='#ffd166';profileCtx.fillText((changes[i]>0?'+':'')+changes[i].toFixed(1),i*width+3,235-h)}})}
function renderLaps(x){const f=v=>v==null?'-':v.toFixed(2)+' s';laps.innerHTML='<strong>Aktuelle Runde:</strong> '+f(x.current_lap_s)+' &nbsp; <strong>Letzte:</strong> '+f(x.last_lap_s)+' &nbsp; <strong>Beste:</strong> '+f(x.best_lap_s)+' &nbsp; <strong>Runden:</strong> '+(x.lap_count||0)}
function renderProblems(x){const spots=[...(x.problem_spots||[]),...(x.danger_segments||[])],list=document.getElementById('problem-list');list.innerHTML=spots.length?spots.slice().sort((a,b)=>b.count-a.count).map(s=>'<div>Segment '+(s.segment??s.cause_segment??'-')+' | Position '+Math.round(s.x)+', '+Math.round(s.y)+' | <strong>'+s.count+'x</strong> | '+(s.last_reason||'Profil reduziert')+'</div>').join(''):'Keine Vorfälle'}
setInterval(()=>{frame.src='/frame.jpg?'+Date.now();fetch('/api/status').then(r=>r.json()).then(x=>{status.textContent=JSON.stringify(x,null,2);renderLaps(x);renderProblems(x);drawMap(x);drawProfile(x)})},500)
</script>"""
            payload = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
