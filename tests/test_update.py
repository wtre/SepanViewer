from copy import deepcopy
from pathlib import Path
import cv2
import pytest
from sepan.config import Config,Customization,load,parse_color,requires_restart
from sepan.engine import Engine,Result
from sepan.vision import Detector,Detection as D,detect_mode
ROOT=Path(__file__).resolve().parents[1]


def middle():
    e=Engine()
    e.frame(0,5,[D('3',450)])
    e.frame(100,5,[D('3',550)])
    return e


def test_middle_keys_share_one_note_but_keep_input_name():
    e=middle()
    r=e.press(392,'3a')[0]
    assert r.lane=='3a' and r.note_id==1
    assert r.text()=='[5] LANE 3a| notetime 0000300 | keypress late  092ms'
    assert not e.press(393,'3b')
    assert e.tick(700)[0].text()=='[5] LANE 3b| keypress 0000393'
    assert middle().press(280,'3b')[0].lane=='3b'


def test_middle_pending_input_and_unplayed_note():
    e=Engine()
    e.frame(0,5,[D('3',450)])
    e.press(280,'3b')
    assert e.frame(100,5,[D('3',550)])[0].lane=='3b'
    r=middle().tick(700)
    assert len(r)==1 and r[0].lane=='3' and r[0].press is None


@pytest.mark.parametrize('error,tag',[(None,''),(0,''),(-22,''),(22,''),
    (-23,'early_s1'),(23,'late_s1'),(-42,'early_s1'),(42,'late_s1'),
    (-43,'early_s2'),(43,'late_s2')])
def test_strict_color_thresholds(error,tag):
    assert Customization().tag(error)==tag


def test_color_uses_printed_error():
    r=Result(5,'3a',1000.0,977.4)
    assert r.error_ms==-23 and Customization().tag(r.error_ms)=='early_s1'
    assert Result(5,'3',1000,None).error_ms is None


def test_updated_user_config_and_backward_compatibility(tmp_path):
    path=ROOT/'config.ini';cfg=load(path)
    assert cfg.globalOffset==-5 and cfg.customization.colorEarlyS1=='#000080'
    assert set(cfg.bindings[5])=={'1','2','3a','3b','4','5','L','R','A','B'}
    s=path.read_text().replace('3a=Hangeul\n3b=Right','3=Right')
    p=tmp_path/'old.ini';p.write_text(s)
    assert '3' in load(p).bindings[5]
    p.write_text(s.replace('3=Right\n4=Numpad7','3a=Right\n4=Numpad7'))
    with pytest.raises(ValueError):load(p)


@pytest.mark.parametrize('value',['256,0,0','-1,0,0','#GG0000','red','0,0'])
def test_invalid_color(value):
    with pytest.raises(ValueError):parse_color(value)


def test_valid_hex_and_bad_threshold(tmp_path):
    assert parse_color(' 0, 0, 128 ')=='#000080'
    s=(ROOT/'config.ini').read_text().replace('colorEarlyS1=0,0,128','colorEarlyS1=#1122aa')
    p=tmp_path/'config.ini';p.write_text(s)
    assert load(p).customization.colorEarlyS1=='#1122AA'
    p.write_text(s.replace('colorThresholdS2=42','colorThresholdS2=22'))
    with pytest.raises(ValueError):load(p)


def test_live_change_preserves_tracks_and_consumption():
    e=middle();e.notes[0].consumed=True
    e.notes.append(deepcopy(e.notes[0]));e.notes[1].id=2;e.notes[1].consumed=False
    cfg=Config(globalOffset=5,maxWindow=80)
    e.reconfigure(cfg)
    assert e.notes[0].due==300 and e.notes[0].consumed
    assert e.notes[1].due==305 and e.window==80
    before=Config();after=deepcopy(before)
    after.globalOffset=5;after.customization.colorThresholdS1=10
    assert not requires_restart(before,after)
    after.fps=30
    assert requires_restart(before,after)


@pytest.fixture(scope='module')
def video_observations():
    cv2.setNumThreads(1)
    cap=cv2.VideoCapture(str(ROOT/'examples/ex5.mp4'));detector=Detector();rows=[]
    assert cap.isOpened()
    i=0
    while True:
        ok,im=cap.read()
        if not ok:break
        roi=im[:900,720:1200]
        mode,_=detect_mode(roi)
        rows.append((i,mode,detector.detect(roi,mode)))
        i+=1
    cap.release()
    assert len(rows)==300
    return rows


def test_five_lane_mode_including_occluded_separator(video_observations):
    assert all(mode==5 for _,mode,_ in video_observations)
    notes=video_observations[60][2]
    expected=[('1',126),('1',480),('2',215),('2',569),('3',303),('4',392),('5',126),('5',480)]
    assert len(notes)==len(expected)
    for d,(lane,y) in zip(notes,expected):
        assert d.lane==lane and abs(d.y-y)<2


def test_shimmer_never_becomes_an_extra_side_head(video_observations):
    # Every capture phase at 12/30/60 fps must produce exactly one A and one B.
    for stride in (1,2,5):
        for phase in range(stride):
            e=Engine(fps=60/stride);seen=set();sides=[]
            for i,mode,notes in video_observations[phase::stride]:
                e.frame(i*1000/60,mode,notes);e.tick(i*1000/60)
                for n in e.notes:
                    if n.id not in seen and n.lane in ('A','B'):sides.append(n.lane)
                    seen.add(n.id)
            assert sides==['A','B'],(stride,phase,sides)


def test_side_filter_does_not_merge_separate_tap_heads():
    import numpy as np
    roi=np.zeros((900,480,3),np.uint8)
    roi[100:120,:240]=[200,185,95]
    roi[145:165,:240]=[200,185,95]
    roi[200:220,240:]=[200,185,95]
    sides=[d for d in Detector().detect(roi,5) if d.lane in ('A','B')]
    assert [d.lane for d in sides]==['A','A','B']
