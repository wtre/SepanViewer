import pytest
from sepan.engine import Engine,Note,Result,clock_text,estimate_shift
from sepan.vision import Detection as D


def ready(**kwargs):
    e=Engine(**kwargs)
    e.frame(0,4,[D('1',450),D('2',350)])
    e.frame(100,4,[D('1',550),D('2',450)])
    return e


def test_shared_speed_and_offset():
    e=ready(offset=5)
    assert e.velocity==1
    assert [n.due for n in e.notes]==[305,405]
    r=e.press(304,'1')[0]
    assert r.text()=='[4] LANE 1 | notetime 0000305 | keypress early 001ms'


def test_nearest_and_single_consumption():
    e=ready()
    e.notes.append(Note(99,4,'1',0,100,310,hits=2))
    assert e.press(309,'1')[0].note_id==99
    assert e.press(309,'1')[0].note_id==1
    assert e.press(309,'1')==[]
    assert e.tick(600)[0].text()=='[4] LANE 1 | keypress 0000309'


def test_window_boundary_and_miss_once():
    e=ready(window=150)
    assert e.press(150,'1')[0].due==300
    assert e.press(550.001,'2')==[]
    results=e.tick(800)
    assert len(results)==2
    assert any(r.text()=='[4] LANE 2 | notetime 0000400 | keypress none' for r in results)
    assert e.tick(1000)==[]


def test_rollover_internal_unwrapped():
    e=Engine();e.reset(6)
    e.notes=[Note(1,6,'B',0,0,10_000_002,hits=2)]
    r=e.press(9_999_999,'B')[0]
    assert r.text()=='[6] LANE B | notetime 0000002 | keypress early 003ms'
    assert clock_text(10_000_014)=='0000014'
    assert Result(6,'1',1.4,1.49).text().endswith('just  000ms')


def test_pending_input_can_match_late_frame():
    e=Engine(window=150)
    e.frame(0,4,[D('1',500)])
    assert e.press(200,'1')==[]
    r=e.frame(100,4,[D('1',600)])
    assert len(r)==1 and r[0].due==250 and r[0].press==200


def test_speed_change_and_no_duplicate_head():
    e=ready()
    e.frame(200,4,[D('1',700),D('2',600)])
    assert e.velocity==1.5
    assert len(e.notes)==2
    assert e.notes[0].due==pytest.approx(233.3333,abs=.001)
    e.frame(300,4,[])
    assert len(e.notes)==2


def test_new_single_frame_head_uses_global_speed():
    e=ready()
    e.frame(200,4,[D('2',550),D('B',605)])
    n=next(n for n in e.notes if n.lane=='B')
    assert n.hits>=2 and n.due==345
    assert e.press(345,'B')[0].due==345


def test_reset_cancels_old_notes_without_false_misses():
    e=ready();e.frame(110,0,[])
    assert not e.notes and not e.press(300,'1') and not e.tick(1000)
    e=ready();e.frame(1000,4,[D('1',10)])
    assert len(e.notes)==1 and e.notes[0].due is None


def test_ambiguous_repetition_is_not_guessed():
    old=[D('1',100),D('1',200)];new=[D('1',250)]
    assert estimate_shift(old,new,100,None,.2,8) is None


def test_stationary_scene_does_not_create_misses():
    e=ready();e.frame(200,4,[D('1',550),D('2',450)])
    assert e.velocity is None
    assert e.tick(2000)==[]
