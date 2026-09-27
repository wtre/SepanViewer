import configparser
import math
import re
from dataclasses import dataclass, field
from .keys import parse_key


@dataclass
class Customization:
    colorThresholdS1: float = 22
    colorThresholdS2: float = 42
    colorEarlyS1: str = '#000080'
    colorLateS1: str = '#800000'
    colorEarlyS2: str = '#0000FF'
    colorLateS2: str = '#FF0000'

    def tag(self, error_ms):
        if error_ms is None or abs(error_ms) <= self.colorThresholdS1:
            return ''
        level = 2 if abs(error_ms) > self.colorThresholdS2 else 1
        return f'{"early" if error_ms < 0 else "late"}_s{level}'

    def palette(self):
        return {'early_s1':self.colorEarlyS1,'late_s1':self.colorLateS1,
                'early_s2':self.colorEarlyS2,'late_s2':self.colorLateS2}


@dataclass
class ViewerConfig:
    opacityStep: int = 20
    port: int = 8765


@dataclass
class Config:
    fps: int = 12
    globalOffset: float = 0
    maxWindow: float = 150
    judgeY: float = 750
    mode: str = 'auto'
    triggerColor: str = 'orange'
    sideColor: str = 'teal'
    deviceIndex: int = 0
    outputIndex: int = 0
    minSpeed: float = .2
    maxSpeed: float = 8
    initialSpeed: float = 0
    noteThreshold: float = .82
    maxDetectY: int = 610
    bindings: dict = field(default_factory=dict)
    customization: Customization = field(default_factory=Customization)
    viewer: ViewerConfig = field(default_factory=ViewerConfig)


CAPTURE_SETTINGS = ('fps','mode','judgeY','deviceIndex','outputIndex',
                    'minSpeed','maxSpeed','initialSpeed','noteThreshold','maxDetectY','triggerColor','sideColor')


def requires_restart(old, new):
    return any(getattr(old,k) != getattr(new,k) for k in CAPTURE_SETTINGS)


def parse_color(value):
    value = value.strip()
    if re.fullmatch(r'#[0-9a-fA-F]{6}',value): return value.upper()
    if re.fullmatch(r'\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}',value):
        rgb = [int(x.strip()) for x in value.split(',')]
        if all(0 <= x <= 255 for x in rgb):
            return '#' + ''.join(f'{x:02X}' for x in rgb)
    raise ValueError(f'Invalid RGB color: {value}. Use 0,0,128 or #000080.')


def load(path):
    # Full-line comments permit hexadecimal RGB values after '='.
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    if not parser.read(path,encoding='utf-8-sig'):
        raise ValueError(f'Config file not found: {path}')
    cfg = Config()
    if not parser.has_section('general'):
        raise ValueError('Missing [general] section')
    allowed = set(cfg.__dict__)-{'bindings','customization','viewer'}
    for name,value in parser['general'].items():
        if name not in allowed: raise ValueError(f'Unknown general setting: {name}')
        value = re.split(r'\s[;#]',value,maxsplit=1)[0].strip()
        setattr(cfg,name,Config.__dataclass_fields__[name].type(value))
    for name in allowed:
        v = getattr(cfg,name)
        if isinstance(v,(float,int)) and not math.isfinite(v):
            raise ValueError(f'{name} must be finite')
    if not 2 <= cfg.fps <= 120: raise ValueError('fps must be 2..120')
    if cfg.maxWindow != int(cfg.maxWindow):raise ValueError('maxWindow must be a whole number of ms for the 1px/ms viewer')
    if not 0 <= cfg.maxWindow <= 2000: raise ValueError('maxWindow must be 0..2000')
    if cfg.deviceIndex < 0 or cfg.outputIndex < 0: raise ValueError('Monitor indexes must be non-negative')
    if not 0 < cfg.minSpeed < cfg.maxSpeed <= 100: raise ValueError('Invalid speed range')
    if cfg.initialSpeed and not cfg.minSpeed <= cfg.initialSpeed <= cfg.maxSpeed:
        raise ValueError('initialSpeed must be zero or within minSpeed..maxSpeed')
    if cfg.sideColor not in ('teal','default'): raise ValueError('sideColor must be teal or default')
    if cfg.triggerColor not in ('orange','default'): raise ValueError('triggerColor must be orange or default')
    if cfg.mode not in ('auto','4','5','6'): raise ValueError('mode must be auto, 4, 5 or 6')
    if not .5 <= cfg.noteThreshold < 1: raise ValueError('noteThreshold must be .5..<1')
    if not 100 <= cfg.maxDetectY <= 640: raise ValueError('maxDetectY must be 100..640')
    if not 650 <= cfg.judgeY <= 800: raise ValueError('judgeY must be 650..800')
    if parser.has_section('customization'):
        c = cfg.customization
        for name,value in parser['customization'].items():
            if name not in c.__dict__:raise ValueError(f'Unknown customization setting: {name}')
            value = re.split(r'\s[;#]',value,maxsplit=1)[0].strip()
            setattr(c,name,float(value) if name.startswith('colorThreshold') else parse_color(value))
        if not (math.isfinite(c.colorThresholdS1) and math.isfinite(c.colorThresholdS2)
                and 0 <= c.colorThresholdS1 < c.colorThresholdS2):
            raise ValueError('Require 0 <= colorThresholdS1 < colorThresholdS2 (finite ms)')
    if parser.has_section('viewer'):
        for name,value in parser['viewer'].items():
            if name not in cfg.viewer.__dict__:raise ValueError(f'Unknown viewer setting: {name}')
            setattr(cfg.viewer,name,int(re.split(r'\s[;#]',value,maxsplit=1)[0].strip()))
    if not 1 <= cfg.viewer.opacityStep <= 10000:raise ValueError('opacityStep must be 1..10000')
    if not 1024 <= cfg.viewer.port <= 65535:raise ValueError('viewer port must be 1024..65535')
    for mode in (4,5,6):
        section = f'{mode}LANE'
        required = {str(i) for i in range(1,mode+1)} | set('LRAB')
        if not parser.has_section(section): raise ValueError(f'Missing [{section}]')
        supplied = set(parser[section])
        alternate = (required-{'3'}) | {'3a','3b'}
        if supplied != required and not (mode == 5 and supplied == alternate):
            raise ValueError(f'[{section}] must contain {sorted(required)}' +
                             (' or replace 3 with both 3a and 3b' if mode == 5 else ''))
        cfg.bindings[mode] = {k:parse_key(re.split(r'\s[;#]',v,maxsplit=1)[0].strip())
                              for k,v in parser[section].items()}
        if len(set(cfg.bindings[mode].values())) != len(supplied):
            raise ValueError(f'Duplicate keys in [{section}]')
    return cfg
