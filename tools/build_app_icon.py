"""Package the approved transparent PNG into Windows multi-resolution ICO.

Fits the approved raster's visible bounds with a small transparent margin.
The master, colors, shapes and internal alpha are not modified.
Uses the installed Qt image codecs, so no new build/runtime dependency is needed.
"""
from pathlib import Path
import argparse
import struct
import sys
from PySide6.QtCore import QBuffer,QByteArray,QIODevice,Qt
from PySide6.QtGui import QImage,QPainter

SIZES=(16,20,24,32,40,48,64,96,128,256)
ASSETS=Path(__file__).resolve().parents[1]/'colayout_lite/assets/branding'
sys.path.insert(0,str(ASSETS.parents[2]))
from colayout_lite.app_identity import ICON_PATH


def visible_artwork(original):
    """Ignore almost-invisible alpha noise when measuring exterior padding.

    Keep two source pixels around the measured bounds for antialiasing. Pixels
    inside the crop (including the cutout) retain their original alpha.
    """
    image=original.convertToFormat(QImage.Format.Format_RGBA8888)
    width,height=image.width(),image.height();left,top,right,bottom=width,height,-1,-1
    for y in range(height):
        row=bytes(image.constScanLine(y))[:width*4]
        xs=[x for x,a in enumerate(row[3::4]) if a>=8]
        if xs:left=min(left,xs[0]);right=max(right,xs[-1]);top=min(top,y);bottom=y
    if right<left:raise ValueError('The approved artwork has no visible pixels')
    left=max(0,left-2);top=max(0,top-2);right=min(width,right+3);bottom=min(height,bottom+3)
    return original.copy(left,top,right-left,bottom-top)


def build(source,target,*,keep_canvas=False):
    original=QImage(str(source))
    if original.isNull() or original.width()!=original.height():
        raise ValueError('Use the approved square PNG')
    # Premultiplied-alpha interpolation prevents a white/black matte at edges.
    artwork=original if keep_canvas else visible_artwork(original)
    artwork=artwork.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    payloads=[]
    for size in SIZES:
        margin=0 if keep_canvas else max(1,round(size*.04))
        tile=artwork.scaled(size-2*margin,size-2*margin,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
        frame=QImage(size,size,QImage.Format.Format_ARGB32_Premultiplied);frame.fill(Qt.GlobalColor.transparent)
        painter=QPainter(frame);painter.drawImage((size-tile.width())//2,(size-tile.height())//2,tile);painter.end()
        raw=QByteArray();buffer=QBuffer(raw);buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not frame.save(buffer,'PNG'):raise RuntimeError('PNG encoder failed')
        buffer.close();payloads.append(bytes(raw))
    offset=6+16*len(SIZES);directory=[]
    for size,payload in zip(SIZES,payloads):
        directory.append(struct.pack('<BBBBHHII',size%256,size%256,0,0,1,32,len(payload),offset))
        offset+=len(payload)
    Path(target).write_bytes(struct.pack('<HHH',0,1,len(SIZES))+b''.join(directory)+b''.join(payloads))
    print(f'Packaged {len(SIZES)} icon sizes: '+', '.join(map(str,SIZES)))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=ICON_PATH.with_suffix('.png'))
    parser.add_argument('--out',type=Path,default=ICON_PATH)
    parser.add_argument('--keep-canvas',action='store_true',help='Legacy export: retain the master canvas margins')
    args=parser.parse_args();build(args.source,args.out,keep_canvas=args.keep_canvas)
