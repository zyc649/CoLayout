"""Strict Calibre flat ASCII polygon/edge results, retaining native precision."""
import re
from math import floor,ceil
from shapely.geometry import Polygon,LineString,GeometryCollection,box
from shapely.ops import unary_union
from shapely import make_valid
from ..model import digest,LiteError
from .models import Marker

_coordinate=re.compile(r'-?\d+').fullmatch

def parse(text,region,scale,*,max_markers=10000,geometries=None):
    """Optionally retain accepted spatial witnesses for object association.

    The sink follows the retained markers exactly; limits, ROI and raw native
    walks are unchanged. This avoids reconstructing native walks, repairing
    hole bridges and unioning edge records again after validating the report.
    """
    lines=text.splitlines();pos=0
    def line():
        nonlocal pos
        if pos>=len(lines):raise LiteError('DRC_RESULTS_TRUNCATED',f'line {pos+1}')
        value=lines[pos].strip();pos+=1;return value
    while pos<len(lines) and not lines[pos].strip():pos+=1
    header=line().split()
    if len(header)!=2 or not header[1].isdigit() or int(header[1])<=0:raise LiteError('DRC_RESULTS_HEADER')
    top,precision=header[0],int(header[1]);factor=scale/precision;roi=box(*region.bbox[0],*region.bbox[1])
    markers=[];rule_counts={};total=0;truncated=False
    while pos<len(lines):
        name=line()
        if not name:continue
        count=line().split()
        if len(count)<3 or not all(x.isdigit() for x in count[:3]):raise LiteError('DRC_RULE_HEADER',name)
        stored,original,ntext=map(int,count[:3]);comments=[line() for _ in range(ntext)]
        message='\n'.join(c for c in comments if not c.startswith('Rule File Pathname:'))
        rule_counts[name]={'stored':stored,'reported':original};truncated|=stored<original
        for _ in range(stored):
            record=line().split()
            if len(record)!=3 or record[0] not in ('p','e'):raise LiteError('DRC_UNSUPPORTED_RECORD',' '.join(record))
            typ,ordinal,n=record[0],record[1],int(record[2]);coords=[]
            if n<1 or n>100000:raise LiteError('DRC_INVALID_VERTEX_COUNT')
            for _ in range(n):
                row=line().split();expected=2 if typ=='p' else 4
                if len(row)!=expected or not all(_coordinate(v) for v in row):raise LiteError('DRC_INVALID_COORDINATE')
                coords.append(tuple(int(v)*factor for v in row))
            if typ=='p':
                if n<3:raise LiteError('DRC_INVALID_POLYGON')
                g=Polygon(coords)
                # Calibre encodes holes using a zero-width bridge in a single
                # polygon walk. Keep that native walk for display/export; use
                # linework repair only for spatial predicates (no buffer loss).
                if not g.is_valid:g=make_valid(g)
                if g.is_empty:raise LiteError('DRC_INVALID_POLYGON',name)
            else:g=unary_union([LineString([(a,b),(c,d)]) for a,b,c,d in coords])
            total+=1
            if not g.intersects(roi):continue
            if len(markers)>=max_markers:truncated=True;continue
            x,y,xx,yy=g.bounds
            markers.append(Marker(id=digest([name,ordinal,coords])[:24],rule_id=name,message=message,kind='polygon' if typ=='p' else 'edges',
                points=tuple(coords) if typ=='p' else (),edges=tuple(coords) if typ=='e' else (),
                bbox=((floor(x),floor(y)),(ceil(xx),ceil(yy))),details={'native_ordinal':ordinal,'native_precision':precision,
                    'context_limited':True,'native_cell':top}))
            if geometries is not None:geometries.append(g)
    return markers,{'native_top':top,'native_precision':precision,'rules':rule_counts,'total_context_markers':total,'truncated':truncated}
