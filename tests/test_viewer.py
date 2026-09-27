from copy import deepcopy
from pathlib import Path
import json
from urllib.request import urlopen
import xml.etree.ElementTree as ET
import pytest
from sepan.config import Config,load
from sepan.engine import Result
from sepan.viewer import ViewerState,ViewerServer,render_svg,marker_side
ROOT=Path(__file__).resolve().parents[1]


def press(state,mode,lane,t,due=None):
    state.keypress(mode,lane,t)
    result=Result(mode,lane,due,t)
    state.resolve(result)
    return result


def test_requested_three_input_example():
    cfg=Config();cfg.viewer.opacityStep=5;s=ViewerState(cfg)
    press(s,6,'2',978086,978096)
    press(s,6,'R',978126,978096)
    press(s,6,'5',1253300)
    snapshot=s.snapshot();a,b=snapshot['markers']
    assert (snapshot['width'],snapshot['height'],snapshot['centerY'])==(51,301,150)
    assert (a['lane'],a['y'],a['side'],a['opacity'])==('2',140,'left',.6)
    assert (b['lane'],b['y'],b['side'],b['opacity'])==('R',180,'right',.8)
    assert len(s.presses)==3


def test_expired_marks_really_removed_and_misses_do_not_age():
    cfg=Config();cfg.viewer.opacityStep=5;s=ViewerState(cfg)
    press(s,6,'2',100,110)
    s.resolve(Result(6,'B',120,None))
    assert s.snapshot()['markers'][0]['opacity']==1
    for i in range(4):press(s,6,'5',200+i)
    assert s.snapshot()['markers'][0]['opacity']==.2
    press(s,6,'5',300)
    assert not s.snapshot()['markers']
    assert (6,'2',100) not in s.presses and len(s.presses)==5


def test_delayed_match_uses_actual_input_order_without_double_fade():
    cfg=Config();cfg.viewer.opacityStep=5;s=ViewerState(cfg)
    s.keypress(5,'3a',100)
    press(s,5,'3b',101,101)
    s.resolve(Result(5,'3a',110,100))
    a,b=s.snapshot()['markers']
    assert a['opacity']==.8 and b['opacity']==1
    assert a['side']=='left' and b['side']=='right'
    for t in (102,103,104,105):press(s,5,'4',t)
    s.resolve(Result(5,'3a',110,100))
    assert all(m['lane']!='3a' for m in s.snapshot()['markers'])


@pytest.mark.parametrize('mode,left,right',[
    (4,['L','A','1','2'],['R','B','3','4']),
    (5,['L','A','1','2','3a'],['R','B','3b','4','5']),
    (6,['L','A','1','2','3'],['R','B','4','5','6'])])
def test_all_lane_sides(mode,left,right):
    assert all(marker_side(mode,lane)=='left' for lane in left)
    assert all(marker_side(mode,lane)=='right' for lane in right)


def test_geometry_threshold_colors_and_opacity_groups():
    cfg=Config();cfg.viewer.opacityStep=5;s=ViewerState(cfg)
    press(s,6,'2',100,110);press(s,6,'R',140,110);press(s,6,'5',200)
    root=ET.fromstring(render_svg(s.snapshot()));ns={'s':'http://www.w3.org/2000/svg'}
    assert root.attrib['width']=='51' and root.attrib['height']=='301'
    rects=[r.attrib for r in root.findall('s:g/s:rect',ns)]
    assert {'x':'25','y':'0','width':'1','height':'301','fill':'#C0C0C0'} in rects
    full={float(r['y']):r['fill'] for r in rects if r['width']=='51'}
    assert full=={128:'#000080',172:'#800000',108:'#0000FF',192:'#FF0000',150:'#FFFFFF'}
    assert sorted(int(r['y']) for r in rects if r['width']=='7')==list(range(0,301,10))
    groups=[g for g in root.findall('s:g',ns) if 'data-marker' in g.attrib]
    assert [float(g.attrib['opacity']) for g in groups]==[.6,.8]
    assert groups[0].find('s:polygon',ns).attrib['points'].startswith('23.5,140.5 ')
    assert groups[1].find('s:polygon',ns).attrib['points'].startswith('27.5,180.5 ')


def test_config_reflow_and_bounded_history():
    cfg=Config();s=ViewerState(cfg)
    for t in range(30):press(s,4,'1',t,t)
    assert len(s.presses)==20
    new=deepcopy(cfg);new.viewer.opacityStep=5;new.maxWindow=80
    s.configure(new)
    snap=s.snapshot()
    assert snap['height']==161 and len(s.presses)==5
    assert [m['opacity'] for m in snap['markers']]==[.2,.4,.6,.8,1]
    assert all(m['y']==80 for m in snap['markers'])
    s.clear();assert not s.snapshot()['markers'] and not s.presses


@pytest.mark.parametrize('line',['opacityStep=0','opacityStep=-1','opacityStep=2.5','port=0'])
def test_invalid_viewer_settings(tmp_path,line):
    text=(ROOT/'config.ini').read_text()
    if line.startswith('port'):text=text.replace('port=8765',line)
    else:text=text.replace('opacityStep=20',line)
    p=tmp_path/'bad.ini';p.write_text(text)
    with pytest.raises(ValueError):load(p)


def test_legacy_config_uses_default_steps(tmp_path):
    text=(ROOT/'config.ini').read_text().replace('[viewer]\nopacityStep=20\nport=8765\n\n','')
    p=tmp_path/'old.ini';p.write_text(text)
    assert load(p).viewer.opacityStep==20


def test_http_and_sse_reconnect_receive_current_state():
    state=ViewerState(Config());server=ViewerServer(state,port=0)
    try:
        with urlopen(server.url,timeout=2) as response:
            page=response.read().decode()
            assert "EventSource('/events')" in page and 'background:transparent' in page
        stream=urlopen(server.url+'events',timeout=2)
        def next_data():
            while True:
                line=stream.readline().decode()
                if line.startswith('data: '):return json.loads(line[6:])
        assert 'data-marker' not in next_data()['svg']
        press(state,6,'3',100,100)
        # The keypress and its resolved marker may arrive as separate revisions.
        for _ in range(3):
            data=next_data()
            if 'data-marker' in data['svg']:break
        assert 'data-marker' in data['svg']
        stream.close()
        with urlopen(server.url+'state.json',timeout=2) as response:
            assert json.load(response)['markers'][0]['lane']=='3'
        stream=urlopen(server.url+'events',timeout=2)
        assert 'data-marker' in next_data()['svg']
        stream.close()
    finally:server.close()
