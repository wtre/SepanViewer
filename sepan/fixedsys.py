"""Rasterise the installed Windows Fixedsys font once, without browser fallback."""
import base64
import ctypes as C
from ctypes import wintypes as W
from functools import lru_cache
import sys


@lru_cache(maxsize=1)
def label_images():
    if sys.platform != 'win32':
        return {},'Native Fixedsys labels require Windows; using the SVG fallback for this platform.'
    import cv2
    import numpy as np
    g=C.WinDLL('gdi32',use_last_error=True)
    class BIH(C.Structure):
        _fields_=[('size',W.DWORD),('width',W.LONG),('height',W.LONG),
                  ('planes',W.WORD),('bitcount',W.WORD),('compression',W.DWORD),
                  ('image_size',W.DWORD),('xppm',W.LONG),('yppm',W.LONG),
                  ('colors_used',W.DWORD),('colors_important',W.DWORD)]
    def api(name,args,result):
        f=getattr(g,name);f.argtypes=args;f.restype=result;return f
    create_dc=api('CreateCompatibleDC',[W.HDC],W.HDC)
    create_font=api('CreateFontW',[C.c_int]*5+[W.DWORD]*8+[W.LPCWSTR],W.HANDLE)
    select=api('SelectObject',[W.HDC,W.HANDLE],W.HANDLE)
    delete=api('DeleteObject',[W.HANDLE],W.BOOL)
    delete_dc=api('DeleteDC',[W.HDC],W.BOOL)
    create_dib=api('CreateDIBSection',[W.HDC,C.POINTER(BIH),W.UINT,C.POINTER(C.c_void_p),W.HANDLE,W.DWORD],W.HANDLE)
    face=api('GetTextFaceW',[W.HDC,C.c_int,W.LPWSTR],C.c_int)
    extent=api('GetTextExtentPoint32W',[W.HDC,W.LPCWSTR,C.c_int,C.POINTER(W.SIZE)],W.BOOL)
    textout=api('TextOutW',[W.HDC,C.c_int,C.c_int,W.LPCWSTR,C.c_int],W.BOOL)
    bk=api('SetBkMode',[W.HDC,C.c_int],C.c_int)
    color=api('SetTextColor',[W.HDC,W.DWORD],W.DWORD)
    flush=api('GdiFlush',[],W.BOOL)
    dc=font=bitmap=old_font=old_bitmap=None
    try:
        dc=create_dc(None)
        # Positive height is the 16-pixel character cell, not a point size.
        font=create_font(16,8,0,0,400,0,0,0,1,6,0,3,0x31,'Fixedsys')
        if not dc or not font:raise OSError('Unable to create the Fixedsys font')
        old_font=select(dc,font)
        actual=C.create_unicode_buffer(128)
        if not face(dc,128,actual) or actual.value.casefold()!='fixedsys':
            raise OSError(f'Fixedsys was substituted with {actual.value!r}')
        w,h=64,40
        header=BIH(C.sizeof(BIH),w,-h,1,32,0,w*h*4,0,0,0,0)
        bits=C.c_void_p()
        bitmap=create_dib(dc,C.byref(header),0,C.byref(bits),None,0)
        if not bitmap or not bits.value:raise OSError('Unable to create the font bitmap')
        old_bitmap=select(dc,bitmap)
        bk(dc,1);color(dc,0xFFFFFF)
        pixels=np.ctypeslib.as_array((C.c_ubyte*(w*h*4)).from_address(bits.value)).reshape(h,w,4)
        labels={}
        kernel=np.array([[0,1,0],[1,1,1],[0,1,0]],np.uint8)
        for label in ('1','2','3','4','5','6','3a','3b','L','R','A','B'):
            size=W.SIZE()
            if not extent(dc,label,len(label),C.byref(size)):raise OSError('Unable to measure Fixedsys')
            if size.cx>16 or size.cy>16:
                raise OSError(f'Fixedsys cell is larger than 8x16: {size.cx}x{size.cy} for {label}')
            pixels[:]=0
            if not textout(dc,1,1,label,len(label)):raise OSError('Unable to draw Fixedsys')
            flush()
            mask=(pixels[:size.cy+2,:size.cx+2,:3].max(axis=2)>127).astype(np.uint8)*255
            rgba=np.zeros((*mask.shape,4),np.uint8)
            rgba[:,:,:3]=mask[:,:,None]
            rgba[:,:,3]=cv2.dilate(mask,kernel)
            ok,png=cv2.imencode('.png',rgba)
            if not ok:raise OSError('Unable to encode Fixedsys labels')
            labels[label]={'width':mask.shape[1],'height':mask.shape[0],
                           'uri':'data:image/png;base64,'+base64.b64encode(png).decode('ascii')}
        return labels,''
    except Exception as e:
        return {},f'Native Fixedsys unavailable ({e}); using the SVG font fallback.'
    finally:
        if dc and old_bitmap:select(dc,old_bitmap)
        if dc and old_font:select(dc,old_font)
        if bitmap:delete(bitmap)
        if font:delete(font)
        if dc:delete_dc(dc)
