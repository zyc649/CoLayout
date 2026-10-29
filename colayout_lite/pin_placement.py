"""Pure PIN placement rules, shared by live feedback and the committing command."""
from .model import LiteError


def center(pin):return tuple((a+b)/2 for a,b in zip(*pin.bbox))


def candidate(region,pin,x,y,grid,*,layer=None):
    from .interface_layers import ANY_METAL,ANY_METAL_LABEL
    if layer==ANY_METAL_LABEL:layer=ANY_METAL
    cx,cy=(round(v/grid)*grid for v in (x,y));(a,b),(c,d)=region.bbox
    cx=max(a,min(c,cx));cy=max(b,min(d,cy))
    side=min(((abs(cx-a),'l'),(abs(cx-c),'r'),(abs(cy-b),'b'),(abs(cy-d),'t')))[1]
    if side=='l':cx=a
    elif side=='r':cx=c
    elif side=='b':cy=b
    else:cy=d
    hx=(pin.bbox[1][0]-pin.bbox[0][0])//2;hy=(pin.bbox[1][1]-pin.bbox[0][1])//2
    return pin.model_copy(update={'bbox':((cx-hx,cy-hy),(cx+hx,cy+hy)),
        'lpp':(pin.lpp[0] if layer in (None,ANY_METAL) else layer,'drawing'),
        'layer_mode':pin.layer_mode if layer is None else ANY_METAL if layer==ANY_METAL else 'single',
        'fixed':True})


def resized_pins(region,bounds,grid):
    """Keep edge and along-edge coordinate; resizing never scales the layout."""
    (a,b),(c,d)=region.bbox;(x,y),(xx,yy)=bounds;updated={}
    for pid,pin in region.pins.items():
        cx,cy=center(pin)
        side=min(((abs(cx-a),'l'),(abs(cx-c),'r'),(abs(cy-b),'b'),(abs(cy-d),'t')))[1]
        cx=x if side=='l' else xx if side=='r' else max(x,min(xx,cx))
        cy=y if side=='b' else yy if side=='t' else max(y,min(yy,cy))
        hx=(pin.bbox[1][0]-pin.bbox[0][0])//2;hy=(pin.bbox[1][1]-pin.bbox[0][1])//2
        updated[pid]=pin.model_copy(update={'bbox':((int(cx)-hx,int(cy)-hy),(int(cx)+hx,int(cy)+hy))})
    return updated
