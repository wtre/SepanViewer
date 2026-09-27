"""A separate Windows Raw Input process; never suppresses or injects keys."""
import ctypes as C
from ctypes import wintypes as W
import time
import traceback


class RAWINPUTDEVICE(C.Structure):
    _fields_ = [('usUsagePage',W.USHORT),('usUsage',W.USHORT),('dwFlags',W.DWORD),('hwndTarget',W.HWND)]


class RAWINPUTHEADER(C.Structure):
    _fields_ = [('dwType',W.DWORD),('dwSize',W.DWORD),('hDevice',W.HANDLE),('wParam',W.WPARAM)]


class RAWKEYBOARD(C.Structure):
    _fields_ = [('MakeCode',W.USHORT),('Flags',W.USHORT),('Reserved',W.USHORT),
                ('VKey',W.USHORT),('Message',W.UINT),('ExtraInformation',W.ULONG)]


def input_worker(events,stop,target_hwnd,origin_ns):
    import win32gui
    import win32api
    user = C.WinDLL('user32',use_last_error=True)
    user.RegisterRawInputDevices.argtypes = [C.POINTER(RAWINPUTDEVICE),W.UINT,W.UINT]
    user.RegisterRawInputDevices.restype = W.BOOL
    user.GetRawInputData.argtypes = [W.HANDLE,W.UINT,C.c_void_p,C.POINTER(W.UINT),W.UINT]
    user.GetRawInputData.restype = W.UINT
    user.SetTimer.argtypes = [W.HWND,C.c_size_t,W.UINT,C.c_void_p]
    user.SetTimer.restype = C.c_size_t
    user.KillTimer.argtypes = [W.HWND,C.c_size_t]
    pressed = set()
    def wndproc(hwnd,msg,wp,lp):
        timestamp = (time.perf_counter_ns()-origin_ns)/1_000_000
        if msg == 0x00ff:
            try:
                size = W.UINT()
                header_size = C.sizeof(RAWINPUTHEADER)
                if user.GetRawInputData(lp,0x10000003,None,C.byref(size),header_size) == 0xffffffff:
                    raise C.WinError(C.get_last_error())
                buf = C.create_string_buffer(size.value)
                if user.GetRawInputData(lp,0x10000003,buf,C.byref(size),header_size) == 0xffffffff:
                    raise C.WinError(C.get_last_error())
                header = RAWINPUTHEADER.from_buffer(buf)
                if header.dwType == 1 and size.value >= header_size+C.sizeof(RAWKEYBOARD):
                    key = RAWKEYBOARD.from_buffer(buf,header_size)
                    vk = int(key.VKey)
                    scan = int(key.MakeCode) | (0x100 if key.Flags & 2 else 0)
                    token = (int(header.hDevice or 0),scan if scan else vk, bool(key.Flags & 4))
                    if key.Flags & 1:
                        pressed.discard(token)
                    elif vk != 255 and key.MakeCode != 255 and token not in pressed:
                        pressed.add(token)
                        if win32gui.GetForegroundWindow() == target_hwnd:
                            events.put(('key',timestamp,vk,scan))
            except Exception:
                events.put(('error','Raw Input: '+traceback.format_exc()))
                stop.set()
            # Required cleanup for foreground WM_INPUT is handled here as well.
            return win32gui.DefWindowProc(hwnd,msg,wp,lp)
        if msg == 0x0113:
            if stop.is_set(): win32gui.DestroyWindow(hwnd)
            return 0
        if msg == 0x0002:
            win32gui.PostQuitMessage(0); return 0
        return win32gui.DefWindowProc(hwnd,msg,wp,lp)
    hwnd = None
    try:
        wc = win32gui.WNDCLASS()
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.lpszClassName = f'SepanRawInput_{time.perf_counter_ns()}'
        wc.lpfnWndProc = wndproc
        atom = win32gui.RegisterClass(wc)
        hwnd = win32gui.CreateWindowEx(0,atom,'Sepan Raw Input',0,0,0,0,0,0,0,wc.hInstance,None)
        rid = RAWINPUTDEVICE(1,6,0x100,hwnd)
        if not user.RegisterRawInputDevices(C.byref(rid),1,C.sizeof(rid)):
            raise C.WinError(C.get_last_error())
        if not user.SetTimer(hwnd,1,100,None): raise C.WinError(C.get_last_error())
        events.put(('info','Raw Input ready'))
        win32gui.PumpMessages()
    except Exception:
        events.put(('error',traceback.format_exc()))
        stop.set()
    finally:
        if hwnd and win32gui.IsWindow(hwnd): win32gui.DestroyWindow(hwnd)
