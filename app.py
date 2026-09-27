"""Windows GUI entry point. Run from this directory with Python 3.11+ x64."""
import sys
import os
import time
import json
import multiprocessing as mp
from pathlib import Path
from queue import Empty
from dataclasses import asdict

ROOT = Path(__file__).resolve().parent


def main():
    if sys.platform != 'win32':
        raise SystemExit('Live capture requires Windows 11. Use replay.py for offline verification.')
    import ctypes
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    import tkinter as tk
    from tkinter import ttk,messagebox
    import win32gui
    from sepan.config import load,Config,requires_restart
    from sepan.keys import identify
    from sepan.engine import Engine
    from sepan.capture import capture_worker
    from sepan.wininput import input_worker
    from sepan.viewer import ViewerState,ViewerServer

    class App:
        def __init__(self):
            self.root = tk.Tk(); self.root.title('세판뷰어 0.5 — Timing monitor')
            self.root.geometry('1060x620')
            self.origin = time.perf_counter_ns()
            self.processes=[]; self.running=False; self.logfile=None; self.jsonfile=None
            self.history=[]; self.cfg=Config()
            self.viewer_state=ViewerState(self.cfg); self.viewer_server=None
            self.viewer_url=tk.StringVar(value="시각화 초기화 중")
            self.viewer_size=tk.StringVar(value="51 × 301 px")
            self.mode_value=tk.StringVar(value='auto'); self.diagnostics=tk.BooleanVar(value=False)
            self.status=tk.StringVar(value='게임을 전체 창 모드로 실행하고 창을 선택하세요.')
            top=ttk.Frame(self.root,padding=10); top.pack(fill='x')
            self.windows=ttk.Combobox(top,state='readonly',width=60); self.windows.grid(row=0,column=0,columnspan=3,sticky='ew')
            self.refresh_button=ttk.Button(top,text='창 새로고침',command=self.refresh); self.refresh_button.grid(row=0,column=3,padx=5)
            self.mode_box=ttk.Combobox(top,textvariable=self.mode_value,values=['auto','4','5','6'],state='readonly',width=8)
            self.mode_box.grid(row=1,column=0,sticky='w',pady=8)
            self.start_button=ttk.Button(top,text='시작',command=self.start); self.start_button.grid(row=1,column=1)
            self.stop_button=ttk.Button(top,text='정지',command=self.stop); self.stop_button.grid(row=1,column=2)
            ttk.Button(top,text='config.ini 열기',command=lambda:os.startfile(ROOT/'config.ini')).grid(row=1,column=3)
            ttk.Button(top,text='config.ini 적용',command=self.apply_config).grid(row=1,column=4,padx=5)
            ttk.Button(top,text='진단 이미지 저장',command=self.save_snapshot).grid(row=2,column=0,sticky='w')
            ttk.Checkbutton(top,text='키 코드 확인 (선택한 게임에서 입력)',variable=self.diagnostics).grid(row=2,column=1,columnspan=3,sticky='w')
            viewer_bar=ttk.Frame(self.root,padding=(10,0));viewer_bar.pack(fill='x')
            ttk.Label(viewer_bar,text='OBS URL:').pack(side='left')
            ttk.Entry(viewer_bar,textvariable=self.viewer_url,width=34,state='readonly').pack(side='left',padx=5)
            ttk.Button(viewer_bar,text='주소 복사',command=self.copy_viewer_url).pack(side='left',padx=3)
            ttk.Button(viewer_bar,text='뷰어 열기',command=self.open_viewer).pack(side='left',padx=3)
            ttk.Button(viewer_bar,text='표시 지우기',command=self.viewer_state.clear).pack(side='left',padx=3)
            ttk.Label(viewer_bar,textvariable=self.viewer_size).pack(side='left',padx=8)
            ttk.Label(self.root,textvariable=self.status,padding=10).pack(fill='x')
            panel=ttk.Frame(self.root);panel.pack(fill='both',expand=True,padx=10,pady=5)
            self.text=tk.Text(panel,font=('Consolas',11),wrap='none',state='disabled')
            scrollbar=ttk.Scrollbar(panel,command=self.text.yview);self.text.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side='right',fill='y');self.text.pack(fill='both',expand=True)
            ttk.Label(self.root,text='시작 후 게임으로 돌아가세요. 게임이 활성화된 동안만 측정합니다. 로그: logs/').pack(pady=6)
            try:
                self.cfg=load(ROOT/'config.ini')
                self.mode_value.set(self.cfg.mode)
                self.configure_colors()
            except Exception as e:self.write(f'CONFIG: {e}')
            try:self.prepare_viewer(self.cfg)
            except Exception as e:
                self.viewer_url.set('시각화 서버 시작 실패')
                self.write(f'VIEWER: {e}. [viewer] port를 변경하고 config.ini 적용을 누르세요.')
            self.refresh(); self.root.protocol('WM_DELETE_WINDOW',self.close)
            self.root.after(5,self.poll)

        def prepare_viewer(self,cfg):
            old=self.viewer_server
            new=old
            if old is None or old.port!=cfg.viewer.port:
                # Bind the replacement before closing the working server.
                new=ViewerServer(self.viewer_state,cfg.viewer.port)
                if new.font_warning:self.write("VIEWER: "+new.font_warning)
            self.viewer_state.configure(cfg)
            self.viewer_server=new
            if old is not None and old is not new:old.close()
            self.viewer_url.set(new.url)
            self.viewer_size.set(f'51 × {2*int(cfg.maxWindow)+1} px')

        def copy_viewer_url(self):
            if self.viewer_server:
                self.root.clipboard_clear()
                self.root.clipboard_append(self.viewer_server.url)

        def open_viewer(self):
            if self.viewer_server:os.startfile(self.viewer_server.url)

        def refresh(self):
            self.targets=[]
            def add(hwnd,_):
                title=win32gui.GetWindowText(hwnd)
                if title and win32gui.IsWindowVisible(hwnd) and hwnd!=self.root.winfo_id():
                    self.targets.append((hwnd,title))
            win32gui.EnumWindows(add,None)
            self.targets.sort(key=lambda x:x[1].lower())
            self.windows['values']=[f'{title} [0x{hwnd:X}]' for hwnd,title in self.targets]
            if self.targets:self.windows.current(0)

        def configure_colors(self):
            for tag,color in self.cfg.customization.palette().items():
                self.text.tag_configure(tag,foreground=color)
            self.text.configure(state='normal')
            self.text.delete('1.0','end')
            for line,error in self.history:
                tag=self.cfg.customization.tag(error)
                self.text.insert('end',line+'\n',(tag,) if tag else ())
            self.text.see('end');self.text.configure(state='disabled')

        def write(self,line,error_ms=None):
            self.history.append((line,error_ms))
            self.text.configure(state='normal')
            tag=self.cfg.customization.tag(error_ms)
            self.text.insert('end',line+'\n',(tag,) if tag else ())
            if len(self.history)>2000:
                del self.history[:200]
                self.text.delete('1.0','201.0')
            self.text.see('end');self.text.configure(state='disabled')
            print(line,flush=True)
            if self.logfile:self.logfile.write(line+'\n');self.logfile.flush()

        def output(self,results):
            for result in results:
                self.viewer_state.resolve(result)
                self.write(result.text(),result.error_ms)
                self.jsonfile.write(json.dumps(asdict(result),ensure_ascii=False)+'\n');self.jsonfile.flush()

        def apply_config(self):
            try:
                new=load(ROOT/'config.ini')
                self.prepare_viewer(new)
            except Exception as e:
                messagebox.showerror('설정 적용 실패',f'{e}\n기존 설정을 유지합니다.')
                return
            restart=self.running and requires_restart(self.cfg,new)
            if restart:self.stop()
            self.cfg=new
            self.mode_value.set(new.mode)
            self.configure_colors()
            if restart:
                self.start(new)
                if self.running:self.write('CONFIG — 설정 적용 완료. 캡처 변경으로 추적을 다시 시작합니다.')
            else:
                if self.running:
                    self.engine.reconfigure(new)
                    stamp=time.perf_counter_ns()
                    (self.session_folder/f'config_applied_{stamp}.ini').write_bytes((ROOT/'config.ini').read_bytes())
                self.write('CONFIG — 설정 적용 완료.')

        def start(self,cfg=None):
            if self.running:return
            try:
                if cfg is None:
                    cfg=load(ROOT/'config.ini');cfg.mode=self.mode_value.get()
                index=self.windows.current()
                if index<0:raise ValueError('게임 창을 선택하세요.')
                self.hwnd=self.targets[index][0]
                self.prepare_viewer(cfg)
                self.cfg=cfg
                self.configure_colors()
                self.engine=Engine(cfg.globalOffset,cfg.maxWindow,cfg.judgeY,cfg.fps,cfg.minSpeed,cfg.maxSpeed,cfg.initialSpeed)
                folder=ROOT/'logs'/(time.strftime('%Y%m%d_%H%M%S')+f'_{time.perf_counter_ns()%1_000_000:06d}')
                self.session_folder=folder
                folder.mkdir(parents=True,exist_ok=True)
                self.logfile=(folder/'events.txt').open('a',encoding='utf-8')
                self.jsonfile=(folder/'events.jsonl').open('a',encoding='utf-8')
                (folder/'config.ini').write_bytes((ROOT/'config.ini').read_bytes())
                (folder/'session.json').write_text(json.dumps({'version':'0.5.0', 'origin_qpc_ns':self.origin,
                    'selected_hwnd':self.hwnd, 'mode_override':cfg.mode, 'python':sys.version},indent=2),encoding='utf-8')
                self.stop_event=mp.Event();self.snapshot_event=mp.Event()
                self.frame_events=mp.Queue();self.key_events=mp.Queue()
                self.processes=[mp.Process(target=input_worker,args=(self.key_events,self.stop_event,self.hwnd,self.origin),daemon=True),
                    mp.Process(target=capture_worker,args=(self.frame_events,self.stop_event,self.snapshot_event,self.hwnd,self.origin,cfg,str(folder)),daemon=True)]
                for p in self.processes:p.start()
                self.running=True;self.last_frame=time.perf_counter();self.key_backlog=[]
                self.start_button.configure(state='disabled');self.windows.configure(state='disabled');self.mode_box.configure(state='disabled');self.refresh_button.configure(state='disabled')
                self.write('START — 게임으로 돌아가면 측정이 시작됩니다.')
                self.status.set('캡처 / 입력 장치 초기화 중')
            except Exception as e:
                self.stop();messagebox.showerror('시작 실패',str(e))

        def stop(self):
            if hasattr(self,'stop_event'):self.stop_event.set()
            for p in self.processes:
                if p.pid is None:continue
                p.join(timeout=.35)
                if p.is_alive():p.terminate();p.join(timeout=.35)
            self.processes=[];self.running=False
            for name in ('frame_events','key_events'):
                q=getattr(self,name,None)
                if q is not None:q.close()
            if self.logfile:self.logfile.close();self.logfile=None
            if self.jsonfile:self.jsonfile.close();self.jsonfile=None
            self.start_button.configure(state='normal');self.windows.configure(state='readonly');self.mode_box.configure(state='readonly');self.refresh_button.configure(state='normal')
            self.status.set('정지됨')

        def save_snapshot(self):
            if self.running:
                self.snapshot_event.set();self.write('INFO — 게임으로 돌아가면 다음 프레임의 진단 이미지를 저장합니다.')

        def poll(self):
            if self.running:
                try:
                    # Process frames first so an already captured note is
                    # available before matching queued keyboard events.
                    for source in (self.frame_events,self.key_events):
                        for _ in range(512):
                            try:event=source.get_nowait()
                            except Empty:break
                            kind=event[0]
                            if kind=='error':raise RuntimeError(event[1])
                            if kind=='info':self.write('INFO — '+event[1])
                            elif kind=='inactive':self.engine.reset();self.key_backlog=[]
                            elif kind=='frame':
                                _,t,mode,notes,cost,age,conf=event
                                now=(time.perf_counter_ns()-self.origin)/1e6
                                if now-t>max(500,3000/self.cfg.fps):continue
                                self.last_frame=time.perf_counter()
                                self.output(self.engine.frame(t,mode,notes))
                                speed='?' if self.engine.velocity is None else f'{self.engine.velocity:.3f}'
                                self.status.set(f'{mode or "비플레이"} lane | {speed} px/ms | 인식 {cost:.1f} ms | 프레임 나이 {age:.1f} ms | {self.engine.quality}')
                            elif kind=='key':
                                _,t,vk,scan=event
                                if self.diagnostics.get():self.write(f'KEY vk{vk:02X} sc{scan:03X} at {t:.3f}ms')
                                if self.engine.mode and win32gui.GetForegroundWindow()==self.hwnd:
                                    lane=identify(self.cfg.bindings[self.engine.mode],vk,scan)
                                    if lane:
                                        self.viewer_state.keypress(self.engine.mode,lane,t)
                                        self.output(self.engine.press(t,lane))
                    if win32gui.GetForegroundWindow()!=self.hwnd:
                        self.engine.reset()
                        self.status.set('대기 — 선택한 게임을 활성화하세요.')
                    elif time.perf_counter()-self.last_frame>max(.5,3/self.cfg.fps):
                        self.engine.reset();self.status.set('대기 — 새 게임 프레임 없음')
                    else:self.output(self.engine.tick((time.perf_counter_ns()-self.origin)/1e6))
                    if self.stop_event.is_set():raise RuntimeError('작업 프로세스가 중지됐습니다. 위 오류를 확인하세요.')
                    if any(p.exitcode is not None for p in self.processes):raise RuntimeError('작업 프로세스가 종료됐습니다.')
                except Exception as e:
                    self.write('ERROR — '+str(e));self.stop()
            self.root.after(5,self.poll)

        def close(self):
            self.stop()
            if self.viewer_server:self.viewer_server.close()
            self.root.destroy()

    app=App();app.root.mainloop()


if __name__=='__main__':
    mp.freeze_support()
    main()
