"""Exact rectangle broad phase for display-label placement, never physical rules."""
from collections import defaultdict
from math import floor


class ScreenRectIndex:
    def __init__(self,width=128,height=32):
        self.width=width;self.height=height;self.cells=defaultdict(list);self.large=[];self.rects=[]

    def keys(self,rect):
        x,xx=floor(rect.left()/self.width),floor(rect.right()/self.width)
        y,yy=floor(rect.top()/self.height),floor(rect.bottom()/self.height)
        if (xx-x+1)*(yy-y+1)>64:return None
        return [(a,b) for a in range(x,xx+1) for b in range(y,yy+1)]

    def add(self,rect):
        ident=len(self.rects);self.rects.append(rect);keys=self.keys(rect)
        if keys is None:self.large.append(ident)
        else:
            for key in keys:self.cells[key].append(ident)

    def intersects(self,rect):
        keys=self.keys(rect)
        candidates=(range(len(self.rects)) if keys is None else
                    {*self.large,*(ident for key in keys for ident in self.cells.get(key,()))})
        return any(rect.intersects(self.rects[ident]) for ident in candidates)
