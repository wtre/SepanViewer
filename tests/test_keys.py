import pytest
from sepan.keys import parse_key,identify
from sepan.config import load
from pathlib import Path


def test_numpad_and_extended_keys():
    assert parse_key('Numpad8').matches(0x68,0x48)
    assert parse_key('Numpad8').matches(0x26,0x48)
    assert not parse_key('Up').matches(0x26,0x48)
    assert parse_key('Up').matches(0x26,0x148)
    assert parse_key('RAlt').matches(0x12,0x138)
    assert not parse_key('LAlt').matches(0x12,0x138)
    assert parse_key('Hangeul').matches(0x15,0x138)
    assert parse_key('Enter')!=parse_key('NumpadEnter')
    assert parse_key('NumpadAdd')==parse_key('sc04E')


def test_alias_overlap_fails_explicitly():
    with pytest.raises(ValueError):
        identify({'1':parse_key('Hangeul'),'2':parse_key('RAlt')},0x15,0x138)


def test_config():
    cfg=load(Path(__file__).resolve().parents[1]/'config.ini')
    assert cfg.fps==12 and len(cfg.bindings[6])==10
    with pytest.raises(ValueError):parse_key('numpadPlus')
