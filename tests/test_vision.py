from pathlib import Path
import cv2
import numpy as np
import pytest
from sepan.vision import Detector,detect_mode
from sepan.engine import Engine
ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def detector():
    cv2.setNumThreads(1)
    return Detector()


def roi(i):return cv2.imread(str(ROOT/'examples'/f'ex{i}.png'))[:900,720:1200]


@pytest.mark.parametrize('i,mode,expected',[
    (1,4,[('1',254),('2',318),('3',381),('4',443),('B',192)]),
    (2,4,[('1',371),('2',435),('3',498),('4',559),('B',309)]),
    (3,6,[('1',91),('2',322),('3',91),('B',552),('L',553),('R',91)]),
    (4,6,[('2',292),('2',523),('4',523),('5',446),('6',369),('L',523),('R',523)]),
])
def test_user_examples(detector,i,mode,expected):
    im=roi(i)
    assert detect_mode(im)[0]==mode
    actual=detector.detect(im,mode)
    assert len(actual)==len(expected)
    for d,(lane,y) in zip(actual,expected):
        assert d.lane==lane
        assert abs(d.y-y)<3


def test_motion_and_due_times(detector):
    e=Engine()
    e.frame(0,4,detector.detect(roi(1),4))
    e.frame(83.33,4,detector.detect(roi(2),4))
    assert e.velocity==pytest.approx(1.4014,abs=.002)
    assert len(e.notes)==5
    assert [n.lane for n in sorted(e.notes,key=lambda n:n.due)]==['4','3','2','1','B']


def test_no_play_blank_and_random():
    assert detect_mode(np.zeros((900,480,3),np.uint8))[0]==0
    assert detect_mode(np.full((900,480,3),255,np.uint8))[0]==0
    im=np.random.default_rng(0).integers(0,256,(900,480,3),dtype=np.uint8)
    assert detect_mode(im)[0]==0


def test_five_lane_geometry_synthetic_only():
    im=np.zeros((900,480,3),np.uint8)
    im[825:890]=[60,47,47]
    for x in (96,192,288,384):im[825:890,x]=[100,80,80]
    assert detect_mode(im)[0]==5


def test_default_trigger_skin_and_color_isolation():
    im=roi(6)
    red=Detector(trigger_color='default')
    notes=red.detect(im,6)
    assert detect_mode(im)[0]==6
    assert [(d.lane,d.y) for d in notes if d.kind=='trigger']==[('L',547),('R',107)]
    orange=Detector()
    assert not [d for d in orange.detect(im,6) if d.kind=='trigger']
    assert [(d.lane,d.y) for d in notes if d.kind=='normal']==[
        (d.lane,d.y) for d in orange.detect(im,6) if d.kind=='normal']
    assert not [d for d in red.detect(roi(4),6) if d.kind=='trigger']
    # Translation must move only the leading heads, not produce body edges.
    shifted=np.zeros_like(im);shifted[40:]=im[:-40]
    assert [(d.lane,d.y) for d in red.detect(shifted,6) if d.kind=='trigger']==[('L',587),('R',147)]


def test_trigger_config_compatibility_and_restart(tmp_path):
    from sepan.config import load,requires_restart
    text=(ROOT/'config.ini').read_text().replace('triggerColor=default','triggerColor=orange')
    p=tmp_path/'config.ini'
    p.write_text(text.replace('triggerColor=orange\n',''))
    old=load(p)
    assert old.triggerColor=='orange'
    p.write_text(text.replace('triggerColor=orange','triggerColor=default'))
    new=load(p)
    assert new.triggerColor=='default'
    assert requires_restart(old,new)
    p.write_text(text.replace('triggerColor=orange','triggerColor=red'))
    with pytest.raises(ValueError,match='triggerColor'):
        load(p)


def test_default_side_skin_heads_and_detection_limit():
    im=roi(7)
    detector=Detector(side_color='default',max_y=640)
    assert detect_mode(im)[0]==6
    notes=detector.detect(im,6)
    assert [(d.lane,d.y) for d in notes]==[('A',619),('B',427)]
    assert [(d.lane,d.y) for d in Detector(side_color='default').detect(im,6)]==[('B',427)]
    assert Detector(side_color='teal',max_y=640).detect(im,6)==[]
    # Move both heads into the normal detection region.
    shifted=np.zeros_like(im);shifted[:-80]=im[80:]
    assert [(d.lane,d.y) for d in Detector(side_color='default').detect(shifted,6)]==[('A',539),('B',347)]


def test_default_side_internal_highlight_and_separate_taps():
    im=np.zeros((900,480,3),np.uint8)
    im[20:300,:240]=[220,240,0]
    im[150:155,:240]=[255,255,180]
    im[350:370,:240]=[220,240,0]
    im[100:120,240:]=[220,240,0]
    notes=Detector(side_color='default').detect(im,6)
    assert [(d.lane,d.y) for d in notes if d.kind=='side']==[('A',289),('A',359),('B',109)]


def test_side_config_compatibility_and_restart(tmp_path):
    from sepan.config import load,requires_restart
    text=(ROOT/'config.ini').read_text()
    p=tmp_path/'config.ini'
    p.write_text(text.replace('sideColor=default\n',''))
    old=load(p)
    assert old.sideColor=='teal'
    p.write_text(text)
    new=load(p)
    assert new.sideColor=='default' and requires_restart(old,new)
    p.write_text(text.replace('sideColor=default','sideColor=blue'))
    with pytest.raises(ValueError,match='sideColor'):
        load(p)
