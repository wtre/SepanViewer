"""Event-driven transparent OBS overlay, served on loopback only."""
from collections import OrderedDict
from html import escape
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit


def marker_side(mode,lane):
    if lane in ('L','A','1','2'):
        return 'left'
    if (mode == 5 and lane == '3a') or (mode == 6 and lane == '3'):
        return 'left'
    return 'right'


class ViewerState:
    def __init__(self,cfg):
        self.condition=threading.Condition()
        self.revision=0
        self.sequence=0
        self.presses=OrderedDict()
        self.configure(cfg)

    def _changed(self):
        self.revision+=1
        self.condition.notify_all()

    def _prune(self):
        # Delete expired records, including unmatched/pending keypresses.
        while self.presses:
            first=next(iter(self.presses.values()))
            if self.sequence-first['sequence'] < self.steps:
                break
            self.presses.popitem(last=False)

    def configure(self,cfg):
        with self.condition:
            self.steps=cfg.viewer.opacityStep
            self.window=int(cfg.maxWindow)
            self.customization=cfg.customization
            self._prune()
            self._changed()

    def keypress(self,mode,lane,timestamp):
        with self.condition:
            self.sequence+=1
            self._prune()
            self.presses[(mode,lane,timestamp)]={
                'sequence':self.sequence,'mode':mode,'lane':lane,'error':None}
            self._changed()

    def resolve(self,result):
        # Results never age markers. Aging happens once, at the actual input.
        if result.press is None or result.due is None:
            return
        with self.condition:
            record=self.presses.get((result.mode,result.lane,result.press))
            if record is None:
                return
            record['error']=result.error_ms
            self._changed()

    def clear(self):
        with self.condition:
            self.presses.clear()
            self._changed()

    def _snapshot_unlocked(self):
        markers=[]
        for p in self.presses.values():
            age=self.sequence-p['sequence']
            if p['error'] is not None and age < self.steps:
                markers.append({'id':p['sequence'],'mode':p['mode'],'lane':p['lane'],
                    'error':p['error'],'y':self.window+p['error'],
                    'side':marker_side(p['mode'],p['lane']),
                    'opacity':(self.steps-age)/self.steps})
        c=self.customization
        return {'revision':self.revision,'width':51,'height':2*self.window+1,
                'centerY':self.window,'opacityStep':self.steps,'markers':markers,
                'thresholds':[
                    {'error':-c.colorThresholdS1,'color':c.colorEarlyS1},
                    {'error': c.colorThresholdS1,'color':c.colorLateS1},
                    {'error':-c.colorThresholdS2,'color':c.colorEarlyS2},
                    {'error': c.colorThresholdS2,'color':c.colorLateS2}]}

    def snapshot(self):
        with self.condition:
            return self._snapshot_unlocked()

    def wait(self,revision,closed):
        with self.condition:
            self.condition.wait_for(lambda:self.revision!=revision or closed.is_set(),timeout=10)
            return self._snapshot_unlocked()


def render_svg(state,labels=None):
    """Coordinates are zero-based; pixel row centerY is the just line."""
    labels=labels or {}
    height,center=state['height'],state['centerY']
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="51" height="{height}" '
           f'viewBox="0 0 51 {height}" role="img" aria-label="Keypress timing">',
           '<g shape-rendering="crispEdges">',
           f'<rect x="25" y="0" width="1" height="{height}" fill="#C0C0C0"/>']
    for offset in range(-(center//10)*10,center+1,10):
        parts.append(f'<rect x="22" y="{center+offset}" width="7" height="1" fill="#C0C0C0"/>')
    for line in state['thresholds']:
        y=center+line['error']
        if 0 <= y < height:
            parts.append(f'<rect x="0" y="{y:g}" width="51" height="1" fill="{escape(line["color"],quote=True)}"/>')
    parts.extend([f'<rect x="0" y="{center}" width="51" height="1" fill="#FFFFFF"/>','</g>'])
    for marker in state['markers']:
        y=marker['y']+.5
        if not 0 <= marker['y'] < height:
            continue
        left=marker['side']=='left'
        tip,base=(23.5,18.5) if left else (27.5,32.5)
        parts.extend([
            f'<g opacity="{marker["opacity"]:.6f}" data-marker="{marker["id"]}">',
            f'<polygon points="{tip},{y:g} {base},{y-4:g} {base},{y+4:g}" '
            'fill="white" stroke="black" stroke-width="1" stroke-linejoin="round"/>'])
        bitmap=labels.get(marker['lane'])
        if bitmap:
            x=18-bitmap['width'] if left else 33
            top=max(0,min(height-bitmap['height'],marker['y']-bitmap['height']//2))
            parts.append(f'<image x="{x}" y="{top}" width="{bitmap["width"]}" height="{bitmap["height"]}" '
                         f'href="{bitmap["uri"]}" style="image-rendering:pixelated"/>')
        else:
            label_x,anchor=(17,'end') if left else (34,'start')
            label_y=max(8,min(height-8,y))
            for dx,dy,color in ((-1,0,'black'),(1,0,'black'),(0,-1,'black'),(0,1,'black'),(0,0,'white')):
                parts.append(f'<text x="{label_x+dx}" y="{label_y+dy:g}" text-anchor="{anchor}" dominant-baseline="central" '
                             f'font-family="Fixedsys, Courier New, monospace" font-size="16" fill="{color}">'
                             f'{escape(marker["lane"])}</text>')
        parts.append('</g>')
    parts.append('</svg>')
    return ''.join(parts)


class ViewerServer:
    def __init__(self,state,port=8765):
        self.state=state
        self.closed=threading.Event()
        owner=self
        from .fixedsys import label_images
        self.labels,self.font_warning=label_images()
        html=(Path(__file__).resolve().parent.parent/'viewer'/'index.html').read_bytes()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):
                pass

            def do_GET(self):
                path=urlsplit(self.path).path
                if path=='/events':
                    self.send_response(200)
                    self.send_header('Content-Type','text/event-stream; charset=utf-8')
                    self.send_header('Cache-Control','no-store')
                    self.send_header('X-Content-Type-Options','nosniff')
                    self.end_headers()
                    self.connection.settimeout(5)
                    revision=-1
                    try:
                        while not owner.closed.is_set():
                            snapshot=owner.state.wait(revision,owner.closed)
                            if owner.closed.is_set():break
                            if snapshot['revision']!=revision:
                                revision=snapshot['revision']
                                payload=json.dumps({'width':51,'height':snapshot['height'],
                                                    'svg':render_svg(snapshot,owner.labels)},ensure_ascii=False)
                                data=f'id: {revision}\ndata: {payload}\n\n'
                            else:data=': heartbeat\n\n'
                            self.wfile.write(data.encode('utf-8'));self.wfile.flush()
                    except (OSError,TimeoutError):
                        pass
                    return
                if path in ('/','/index.html'):
                    body,mime=html,'text/html; charset=utf-8'
                elif path=='/state.json':
                    body=json.dumps(owner.state.snapshot()).encode();mime='application/json'
                elif path=='/view.svg':
                    body=render_svg(owner.state.snapshot(),owner.labels).encode();mime='image/svg+xml'
                else:
                    self.send_error(404);return
                self.send_response(200)
                self.send_header('Content-Type',mime)
                self.send_header('Content-Length',str(len(body)))
                self.send_header('Cache-Control','no-store')
                self.send_header('X-Content-Type-Options','nosniff')
                self.end_headers()
                try:self.wfile.write(body)
                except OSError:pass

        self.httpd=ThreadingHTTPServer(('127.0.0.1',port),Handler)
        self.httpd.daemon_threads=True
        self.port=self.httpd.server_address[1]
        self.thread=threading.Thread(target=lambda:self.httpd.serve_forever(poll_interval=.1),daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f'http://127.0.0.1:{self.port}/'

    def close(self):
        if self.closed.is_set():return
        self.closed.set()
        with self.state.condition:self.state.condition.notify_all()
        self.httpd.shutdown();self.httpd.server_close()
        self.thread.join(timeout=1)
