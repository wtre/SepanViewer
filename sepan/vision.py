from dataclasses import dataclass
from pathlib import Path
import cv2
import numpy as np


@dataclass(frozen=True)
class Detection:
    lane: str
    y: float
    confidence: float = 1.0
    kind: str = 'normal'


def detect_mode(roi):
    """Read persistent lane separators, not the number of visible notes."""
    if roi.shape[0] < 890:
        return 0, 0.0
    strip = roi[825:890, :480]
    gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY).astype(np.float32)
    # The supplied skin has dark, low-saturation key panels.
    median = np.median(strip, axis=(0, 1))
    if not (15 < median.mean() < 95 and median.max() - median.min() < 45):
        return 0, 0.0
    edge = np.median(abs(np.diff(gray, axis=1)), axis=0)
    scores = {}
    for n in (4, 5, 6):
        strengths = [float(edge[round(480*i/n)-3:round(480*i/n)+2].max())
                     for i in range(1, n)]
        # A judgement flash may hide one separator. The remaining
        # boundaries must still support the same layout.
        scores[n] = sorted(strengths)[1]
    n = max(scores, key=scores.get)
    return (n, min(1.0, scores[n]/25)) if scores[n] >= 10 else (0, 0.0)


class Detector:
    def __init__(self, assets=None, threshold=0.82, max_y=610, trigger_color='orange', side_color='teal'):
        if side_color not in ('teal','default'):
            raise ValueError('side_color must be teal or default')
        self.side_color = side_color
        if trigger_color not in ('orange','default'):
            raise ValueError('trigger_color must be orange or default')
        self.trigger_color = trigger_color
        self.threshold, self.max_y = threshold, max_y
        assets = Path(assets or Path(__file__).resolve().parent.parent / 'assets')
        self.templates = {}
        for mode in (4, 5, 6):
            self.templates[mode] = []
            for color in ('white', 'blue'):
                base = cv2.imread(str(assets / f'cap{mode}_{color}.png'), 0)
                if base is None:
                    raise FileNotFoundError(f'Missing note templates: {assets}')
                h, w = base.shape
                # Use only the interior of the bottom cap: the same geometry is
                # present on tap notes and on the leading end of hold notes.
                yy, xx = np.mgrid[:h, :w]
                mask = (((xx-(w-1)/2)**2 + yy**2) <= ((w-3)/2)**2).astype(np.uint8)*255
                self.templates[mode].append((base, mask))

    def detect(self, roi, mode):
        if mode not in self.templates:
            return []
        gray = cv2.cvtColor(roi[:750, :480], cv2.COLOR_BGR2GRAY)
        notes = []
        for lane in range(mode):
            center = 480*(lane+0.5)/mode
            candidates = []
            for template, mask in self.templates[mode]:
                h, w = template.shape
                x0 = max(0, round(center-(w-1)/2)-3)
                x1 = min(480, x0+w+6)
                band = gray[:min(750, self.max_y+h+1), x0:x1]
                result = cv2.matchTemplate(band, template, cv2.TM_CCOEFF_NORMED, mask=mask)
                result = np.nan_to_num(result, nan=-1, posinf=-1, neginf=-1)
                scores = result.max(axis=1)
                for y in np.flatnonzero((scores >= self.threshold) &
                                       (scores == cv2.dilate(scores[:,None], np.ones((9,1),np.uint8))[:,0])):
                    if 1 <= y <= self.max_y:
                        # A quadratic peak fit improves subpixel center estimates.
                        delta = 0.0
                        if 0 < y < len(scores)-1:
                            a,b,c = scores[y-1:y+2]
                            den = float(a-2*b+c)
                            if den < -1e-6:
                                delta = float(np.clip(0.5*(a-c)/den, -.5, .5))
                        candidates.append((float(scores[y]), y+delta, w))
            selected = []
            for score,y,w in sorted(candidates, reverse=True):
                if all(abs(y-old.y) > w*.55 for old in selected):
                    selected.append(Detection(str(lane+1),y,score))
            notes.extend(selected)
        hsv = cv2.cvtColor(roi[:750, :480], cv2.COLOR_BGR2HSV)
        # Default skin is saturated crimson/pink; hue wraps at red.
        trigger = (cv2.inRange(hsv, (3,65,135), (22,215,255))
                   if self.trigger_color == 'orange' else
                   cv2.bitwise_or(cv2.inRange(hsv, (155,150,135), (179,255,255)),
                                  cv2.inRange(hsv, (0,150,135), (2,255,255))))
        # Saturated mint is the default skin; custom teal is less saturated.
        side_mask = (cv2.inRange(hsv, (80,55,130), (101,210,255))
                     if self.side_color == 'teal' else
                     cv2.inRange(hsv, (82,220,130), (94,255,255)))
        masks = {
            'trigger': trigger,
            'side': side_mask,
        }
        # The broad envelope tolerates a hold body's animated brightness.
        side_envelope = (cv2.inRange(hsv,(78,20,85),(105,235,255))
                         if self.side_color == 'teal' else
                         cv2.inRange(hsv,(80,150,85),(98,255,255))) > 0
        for kind, mask in masks.items():
            for side in range(2):
                # Normal notes may cover most of a bar's middle. Aggregate many
                # columns, then detect downward-facing edges rather than blobs.
                m = mask[:,side*240+5:side*240+235] > 0
                cs = np.vstack([np.zeros((1,m.shape[1]),dtype=np.int16), np.cumsum(m,axis=0,dtype=np.int16)])
                sums = cs[3:]-cs[:-3]
                support_rows = ((sums[:-3] >= 2) & (sums[3:] <= 1)).mean(axis=1)
                for idx in np.flatnonzero(support_rows >= .32):
                    bottom = int(idx)+3
                    if bottom < 5 or bottom >= min(self.max_y+15,744):
                        continue
                    if kind == 'side':
                        # Text, shimmer and highlights inside a hold can create
                        # mask edges. A head must have clear space below it.
                        below = side_envelope[bottom+4:bottom+13,side*240+5:side*240+235]
                        if below.size == 0 or float(below.mean()) > .32:
                            continue
                    support = float(support_rows[idx])
                    # The head center is half a tap bar above the leading edge.
                    height = 26 if kind == 'trigger' else 20
                    y = bottom-height/2
                    lane = ('L','R')[side] if kind == 'trigger' else ('A','B')[side]
                    if not 0 < y <= self.max_y:
                        continue
                    d = Detection(lane, float(y), support, kind)
                    same = [a for a in notes if a.lane == lane and abs(a.y-y)<8]
                    if not same:
                        notes.append(d)
                    elif support > same[0].confidence:
                        notes.remove(same[0]); notes.append(d)
        return sorted(notes, key=lambda d:(d.lane,d.y))

    def annotate(self, roi, mode, notes):
        out = roi.copy()
        cv2.line(out,(0,750),(479,750),(0,255,255),1)
        for d in notes:
            x = int((int(d.lane)-.5)*480/mode) if d.lane.isdigit() else (120 if d.lane in ('L','A') else 360)
            cv2.drawMarker(out,(x,round(d.y)),(0,255,0),cv2.MARKER_CROSS,14,1)
            cv2.putText(out,f'{d.lane} y={d.y:.1f}',(max(0,x-40),max(14,round(d.y)-8)),cv2.FONT_HERSHEY_SIMPLEX,.4,(0,255,0),1)
        return out
