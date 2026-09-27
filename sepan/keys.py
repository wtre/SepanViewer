"""AHK-style names, with explicit Windows VK/scan-code escape hatches."""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Binding:
    kind: str
    code: int

    def matches(self, vk, scan):
        return (vk if self.kind == 'vk' else scan) == self.code


VK = {
    'hangeul':0x15,'hangul':0x15,'kana':0x15,'hanja':0x19,
    'space':0x20,'tab':9,'escape':27,'esc':27,'backspace':8,
    'capslock':0x14,'numlock':0x90,'scrolllock':0x91,
    'printscreen':0x2c,'pause':0x13,
}
SC = {
    'enter':0x01c,'numpadenter':0x11c,
    'lalt':0x038,'ralt':0x138,'lctrl':0x01d,'rctrl':0x11d,
    'lshift':0x02a,'rshift':0x036,'lwin':0x15b,'rwin':0x15c,
    'up':0x148,'down':0x150,'left':0x14b,'right':0x14d,
    'home':0x147,'end':0x14f,'pgup':0x149,'pgdn':0x151,
    'insert':0x152,'delete':0x153,
    'numpad0':0x052,'numpad1':0x04f,'numpad2':0x050,'numpad3':0x051,
    'numpad4':0x04b,'numpad5':0x04c,'numpad6':0x04d,'numpad7':0x047,
    'numpad8':0x048,'numpad9':0x049,'numpadadd':0x04e,
    'numpadsub':0x04a,'numpadmult':0x037,'numpaddiv':0x135,'numpaddot':0x053,
    "'":0x028,';':0x027,',':0x033,'.':0x034,'/':0x035,
    '[':0x01a,']':0x01b,'\\':0x02b,'-':0x00c,'=':0x00d,'`':0x029,
}


def parse_key(name):
    s = name.strip().lower()
    if s in SC: return Binding('sc', SC[s])
    if s in VK: return Binding('vk', VK[s])
    if re.fullmatch(r'[a-z0-9]',s): return Binding('vk',ord(s.upper()))
    if re.fullmatch(r'f(?:[1-9]|1[0-9]|2[0-4])',s): return Binding('vk',0x6f+int(s[1:]))
    if re.fullmatch(r'vk[0-9a-f]{2}',s): return Binding('vk',int(s[2:],16))
    if re.fullmatch(r'sc[0-9a-f]{3}',s): return Binding('sc',int(s[2:],16))
    raise ValueError(f'Unknown key name: {name}. Use Right, RAlt, NumpadAdd, Hangeul, vk15 or sc138.')


def identify(mapping,vk,scan):
    lanes = [lane for lane,b in mapping.items() if b.matches(vk,scan)]
    if len(lanes)>1:
        raise ValueError(f'Overlapping bindings for vk{vk:02X}/sc{scan:03X}: {lanes}')
    return lanes[0] if lanes else None
