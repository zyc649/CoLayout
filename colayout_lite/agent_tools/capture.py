"""Read-only isolated use of the APP canvas; never move the human camera."""

from pathlib import Path
from uuid import uuid4
from time import perf_counter
import base64, hashlib
from PySide6.QtCore import Qt, QRectF
from ..model import LiteError


def capture(workspace, profile, region_id, args, folder):
    from ..presentation.snapshot_canvas import SnapshotCanvas
    from .capture_query import prepare
    from ..presentation.capture_overlay import install
    from ..presentation.capture_frame import frame_width,compose,footer_height

    started=perf_counter()
    scale = profile.dbu_per_micron
    data=prepare(workspace,profile,region_id,args)
    bounds=data['bounds']
    x, y, xx, yy = (v * scale for v in bounds)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    # Qt fitInView reserves a few pixels. Render beyond the requested box and
    # only downsample so its long edge really reaches the requested resolution.
    picture_width=frame_width(data,args.width,args.height)
    data['legend_unit']=(max(.8,min(args.height/1400,picture_width/600)) if (xx-x)/(yy-y)<.5 else max(.8,picture_width/1600))
    reserved=min(args.height//2,footer_height(data,picture_width))
    view = SnapshotCanvas(workspace, profile, region_id, args.width+16, args.height-reserved+16)
    try:
        view.show()
        view.layout().activate()
        rect = QRectF(x, -yy, xx - x, yy - y)
        view.canvas.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        view.refresh_overlay()
        display=install(view,args,data)
        image = view.canvas.viewport().grab().toImage()
        mapped = view.canvas.viewportTransform().mapRect(rect)
        ratio = image.devicePixelRatio()
        pixels = (
            QRectF(
                mapped.x() * ratio,
                mapped.y() * ratio,
                mapped.width() * ratio,
                mapped.height() * ratio,
            )
            .toAlignedRect()
            .intersected(image.rect())
        )
        image = image.copy(pixels)
        image.setDevicePixelRatio(1)
        if image.width() > args.width or image.height() > args.height:
            image = image.scaled(
                args.width,
                args.height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        image,geometry_rect,legend=compose(image,data,args,picture_width)
        display['geometry_rect_px']=geometry_rect
        display['legend_lines']=legend
        display['framing']='letterboxed geometry; blank margins and wrapped legend do not expand bounds_um'
        display['pixel_rounding']='geometry_rect_px is the integer pixel envelope; raster edges may round by one pixel'
        display['annotation_coordinates']='rect_fraction is relative to geometry_rect_px; bounds_um applies only to that rectangle'
        path = folder / (uuid4().hex + '.png')
        if image.isNull() or not image.save(str(path)):
            raise LiteError('CAPTURE_FAILED')
        raw = path.read_bytes()
        context=None
        if data.get('location'):
            from .inspection import layout
            context=layout(workspace,profile,region_id,detail='full',bounds_um=bounds,layers=args.layers)
        return {
            **({'context':context} if context is not None else {}),
            'document_id': workspace.id,
            'revision': workspace.revision,
            'region_id': region_id,
            'bounds_um': list(bounds),
            **({'location':data['location']} if data.get('location') else {}),
            'coordinates': 'workspace_um',
            'mime_type': 'image/png',
            'width': image.width(),
            'height': image.height(),
            'image_path': str(path.resolve()),
            'sha256': hashlib.sha256(raw).hexdigest(),
            'image_base64': base64.b64encode(raw).decode('ascii'),
            'preview': args.job_id is not None,
            'display':display,
            'highlight':data['summary'],
            'seconds':perf_counter()-started,
            'size_policy':'width/height bound the original PNG; geometry keeps ROI aspect ratio, legend is outside geometry_rect_px; no upscaling',
        }
    finally:
        view.close()
        view.deleteLater()
