"""Deterministic tracking and matching; all internal times are unwrapped ms."""
from dataclasses import dataclass
import math
import statistics


def ms_round(value):
    return math.floor(value + .5)


def clock_text(value):
    return f'{ms_round(value) % 10_000_000:07d}'


@dataclass
class Note:
    id: int
    mode: int
    lane: str
    y: float
    seen: float
    due: float | None = None
    hits: int = 1
    consumed: bool = False
    ended: bool = False


@dataclass
class Result:
    mode: int
    lane: str
    due: float | None
    press: float | None
    note_id: int | None = None

    @property
    def error_ms(self):
        if self.due is None or self.press is None:
            return None
        return ms_round(self.press)-ms_round(self.due)

    def text(self):
        prefix = f'[{self.mode}] LANE {self.lane:<2}| '
        if self.due is None:
            return prefix + f'keypress {clock_text(self.press)}'
        prefix += f'notetime {clock_text(self.due)} | keypress '
        if self.press is None:
            return prefix + 'none'
        diff = self.error_ms
        name = 'early' if diff < 0 else 'late ' if diff > 0 else 'just '
        return prefix + f'{name} {abs(diff):03d}ms'


def assignments(old, new, shift, tolerance):
    """One-to-one nearest associations, separately constrained by lane."""
    candidates = sorted((abs(b.y-a.y-shift),i,j)
                        for i,a in enumerate(old) for j,b in enumerate(new)
                        if a.lane == b.lane and abs(b.y-a.y-shift) <= tolerance)
    oi, nj, pairs = set(), set(), []
    for error,i,j in candidates:
        if i not in oi and j not in nj:
            oi.add(i); nj.add(j); pairs.append((i,j,error))
    return pairs


def estimate_shift(old, new, dt, velocity, min_speed, max_speed):
    candidates = [b.y-a.y for a in old for b in new
                  if a.lane == b.lane and min_speed*dt <= b.y-a.y <= max_speed*dt]
    if not candidates:
        return None
    hypotheses = []
    for shift in candidates:
        pairs = assignments(old,new,shift,5)
        if pairs:
            exact = statistics.median(new[j].y-old[i].y for i,j,_ in pairs)
            if all(abs(exact-h[1]) > 4 for h in hypotheses):
                hypotheses.append((len(pairs),exact,sum(e for _,_,e in pairs)))
    prior = velocity*dt if velocity is not None else 0
    hypotheses.sort(key=lambda h:(-h[0], abs(h[1]-prior) if velocity is not None else h[2]))
    best = hypotheses[0]
    if len(hypotheses)>1 and best[0] == hypotheses[1][0]:
        # Repeated patterns at low capture rates can produce indistinguishable
        # displacements. Reject an uninitialised or equally plausible solution.
        if velocity is None or abs(abs(best[1]-prior)-abs(hypotheses[1][1]-prior)) < 5:
            return None
    return best[1]


class Engine:
    def __init__(self, offset=0.0, window=150.0, judge_y=750.0,
                 fps=12, min_speed=.2, max_speed=8.0, initial_speed=0):
        self.offset, self.window, self.judge_y = offset,window,judge_y
        self.fps, self.min_speed, self.max_speed = fps,min_speed,max_speed
        self.initial_speed = initial_speed or None
        self.next_id = 1
        self.reset()

    def reconfigure(self, cfg):
        delta = cfg.globalOffset-self.offset
        for note in self.notes:
            if note.due is not None and not note.consumed:
                note.due += delta
        self.offset, self.window = cfg.globalOffset,cfg.maxWindow
        self.judge_y, self.fps = cfg.judgeY,cfg.fps
        self.min_speed, self.max_speed = cfg.minSpeed,cfg.maxSpeed
        self.initial_speed = cfg.initialSpeed or None

    def reset(self, mode=0):
        self.mode, self.previous, self.time = mode,[],None
        self.velocity = self.initial_speed
        self.notes, self.pending = [],[]
        self.quality = 'waiting for two frames'
        self.last_motion = None

    def frame(self, t, mode, detections):
        if mode != self.mode:
            self.reset(mode)
        if mode == 0:
            return []
        if self.time is not None and t <= self.time:
            return []
        dt = t-self.time if self.time is not None else None
        if dt is not None and dt > max(500,3_000/self.fps):
            self.reset(mode)
            dt = None
        shift = None
        if dt is not None:
            shift = estimate_shift(self.previous,detections,dt,self.velocity,self.min_speed,self.max_speed)
            if shift is not None:
                self.velocity = shift/dt
                self.quality = 'measured'
                self.last_motion = t
            else:
                stationary = assignments(self.previous,detections,0,1.0)
                if self.previous and detections and len(stationary) >= min(2,len(self.previous),len(detections)):
                    self.notes = []
                    self.velocity = None
                    self.quality = 'stationary / reacquiring'
                else:
                    self.quality = 'extrapolated' if self.velocity else 'ambiguous / waiting'
                if self.velocity is None:
                    self.notes = []
        movement = shift if shift is not None else (self.velocity or 0)*(dt or 0)
        for note in self.notes:
            if not note.ended:
                note.y += movement
        pairs = assignments(self.notes,detections,0,12 if self.velocity else 4)
        used = set()
        for i,j,_ in pairs:
            note,d = self.notes[i],detections[j]
            note.y, note.seen = d.y,t
            note.hits += 1
            used.add(j)
        for j,d in enumerate(detections):
            if j not in used:
                self.notes.append(Note(self.next_id,mode,d.lane,d.y,t,
                                       hits=2 if self.velocity is not None else 1))
                self.next_id += 1
        # First-frame tracks need the just-measured displacement before matching.
        if self.velocity:
            for note in self.notes:
                if not note.ended:
                    note.due = t+(self.judge_y-note.y)/self.velocity+self.offset
                    if note.y >= self.judge_y:
                        note.ended = True
        # Unconfirmed observations that vanish while still in the detection
        # area are likely false positives. Confirmed occluded heads are retained.
        self.notes = [n for n in self.notes if not
                      (n.hits < 2 and n.y < 600 and t-n.seen > 2_000/self.fps)]
        self.previous, self.time = list(detections),t
        results = []
        waiting = self.pending; self.pending = []
        for press,lane in waiting:
            result = self._match(press,lane)
            if result: results.append(result)
            else: self.pending.append((press,lane))
        return results

    def _match(self, t, lane):
        physical_lane = '3' if self.mode == 5 and lane in ('3a','3b') else lane
        candidates = [n for n in self.notes if n.lane == physical_lane and not n.consumed
                      and n.due is not None and n.hits >= 2 and abs(t-n.due) <= self.window]
        if not candidates:
            return None
        n = min(candidates,key=lambda n:(abs(t-n.due),n.due,n.id))
        n.consumed = True
        return Result(self.mode,lane,n.due,t,n.id)

    def press(self, t, lane):
        if not self.mode:
            return []
        result = self._match(t,lane)
        if result: return [result]
        self.pending.append((t,lane))
        return []

    def tick(self, now):
        results = []
        # Allow newly captured heads and queued input events to arrive before
        # finalising misses. This adds output latency, not timestamp error.
        grace = max(50,2_000/self.fps)
        keep = []
        for press,lane in self.pending:
            if now-press > grace:
                results.append(Result(self.mode,lane,None,press))
            else: keep.append((press,lane))
        self.pending = keep
        for n in self.notes:
            if n.due is not None and n.hits >= 2 and not n.consumed and now > n.due+self.window+grace:
                n.consumed = True
                results.append(Result(n.mode,n.lane,n.due,None,n.id))
        self.notes = [n for n in self.notes if n.due is None or now < n.due+self.window+grace+500]
        return results
