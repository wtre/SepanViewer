import time
import traceback
from pathlib import Path


def capture_worker(events,stop,snapshot,target_hwnd,origin_ns,cfg,session_dir):
    import ctypes
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    import cv2
    import dxcam
    import win32gui
    import win32api
    from .vision import Detector,detect_mode
    cv2.setNumThreads(1)
    camera = None
    try:
        camera = dxcam.create(device_idx=cfg.deviceIndex,output_idx=cfg.outputIndex,
                              backend='dxgi',output_color='BGR',max_buffer_len=4)
        # DXcam 0.3.0 has no public monitor-name accessor. This guarded access is
        # intentionally isolated here, and the dependency is pinned accordingly.
        name = camera._output.devicename
        monitor = win32api.MonitorFromWindow(target_hwnd,2)
        info = win32api.GetMonitorInfo(monitor)
        if info['Device'].lower() != name.lower():
            raise RuntimeError(f'Wrong DXcam output: {name}; game is on {info["Device"]}. '
                               'Set deviceIndex/outputIndex in config.ini.\n'+dxcam.output_info())
        left,top,right,bottom = info['Monitor']
        w,h = right-left,bottom-top
        if abs(w/h-16/9) > .01:
            raise RuntimeError('This version needs a 16:9 monitor / borderless game.')
        def check_window():
            if not win32gui.IsWindow(target_hwnd): raise RuntimeError('Selected game window was closed.')
            rect = win32gui.GetClientRect(target_hwnd)
            pos = win32gui.ClientToScreen(target_hwnd,(0,0))
            if abs(pos[0]-left)>2 or abs(pos[1]-top)>2 or abs(rect[2]-w)>2 or abs(rect[3]-h)>2:
                raise RuntimeError('Use borderless fullscreen on the selected monitor, then restart.')
        check_window()
        roi_h = 900 if cfg.mode == 'auto' else 750
        region = (round(w*720/1920),0,round(w*1200/1920),round(h*roi_h/1080))
        detector = Detector(threshold=cfg.noteThreshold,max_y=cfg.maxDetectY,trigger_color=cfg.triggerColor,side_color=cfg.sideColor)
        camera.start(region=region,target_fps=cfg.fps,video_mode=True)
        events.put(('info',f'DXGI ready: {name}, ROI {region}, {cfg.fps} fps'))
        previous_ts = None
        while not stop.is_set():
            packet = camera.get_latest_frame(with_timestamp=True)
            if packet is None: continue
            frame,ts = packet
            if win32gui.GetForegroundWindow() != target_hwnd or win32gui.IsIconic(target_hwnd):
                events.put(('inactive',))
                continue
            check_window()
            if ts is None or ts <= 0: continue
            if abs(time.perf_counter()-ts) > 10:
                raise RuntimeError('DXGI and QPC timestamps disagree; timing measurement stopped.')
            if ts == previous_ts: continue
            previous_ts = ts
            t = ts*1000-origin_ns/1_000_000
            start = time.perf_counter()
            roi = cv2.resize(frame,(480,roi_h),interpolation=cv2.INTER_AREA) if frame.shape[:2] != (roi_h,480) else frame
            mode,confidence = detect_mode(roi) if cfg.mode == 'auto' else (int(cfg.mode),1.0)
            notes = detector.detect(roi,mode)
            elapsed = (time.perf_counter()-start)*1000
            age = (time.perf_counter_ns()-origin_ns)/1_000_000-t
            events.put(('frame',t,mode,notes,elapsed,age,confidence))
            if snapshot.is_set():
                snapshot.clear()
                path = Path(session_dir)/f'frame_{round(t):09d}'
                cv2.imwrite(str(path.with_suffix('.png')),roi)
                cv2.imwrite(str(path)+'_detected.png',detector.annotate(roi,mode,notes))
                import json
                path.with_suffix('.json').write_text(json.dumps({'time_ms':t,'mode':mode,
                    'detections':[d.__dict__ for d in notes]},indent=2),encoding='utf-8')
                events.put(('info',f'Snapshot saved: {path.name}'))
    except Exception:
        events.put(('error','Capture: '+traceback.format_exc()))
        stop.set()
    finally:
        if camera is not None: camera.release()
