"""Shared layout scene construction for the editor and read-only capture host."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPen, QPainterPath
from ..scene import figures_by_owner
from ..geometry import ORIENT, compose, transform, shape_figure, via_figures
from ..render import (
    NativeFigureItem,
    box_rect,
    add_label,
    decode_display,
    PreviewRectItem,
    MissingMasterOutline,
)
from .owner_graphics import OwnerGraphics, qt_transform


def draw_owner(self, uid, figures=None):
    # New Qt groups start visible/selectable. Reapply scope protection even
    # when only display preferences changed and Workspace stayed identical.
    self._overlay_context = None
    if uid in self.groups:
        self.groups.pop(uid).remove()
    obj = self._visible_objects.get(uid)
    if obj is None:
        return
    group = OwnerGraphics(
        self.scene, uid, obj.bbox if obj.kind in ('inst', 'mosaic', 'mpp') else None
    )
    self.groups[uid] = group
    group.native_box = False
    figures = figures if figures is not None else self.base_figures.get(uid, [])
    if not figures and obj.shape:
        figures = (
            via_figures(obj.shape, self.editor.profile)
            if obj.kind == 'stdVia'
            else [shape_figure(obj.shape)]
        )
    for index, f in enumerate(figures):
        if (
            f.get('interface')
            and f['kind'] in ('label', 'textDisplay')
            and f.get('style') in ('__module_frame__', '__pin_name__')
        ):
            continue  # Synthetic titles/PIN labels use one screen-sized overlay, never native world-text scaling.
        if 'style' not in f:
            key = '/'.join(f['lpp'])
            f = {
                **f,
                'id': uid + ':' + str(index),
                'owner_id': uid,
                'style': key,
                'inside_instance': False,
            }
        style = self.styles.get(f['style'])
        if not style:
            # Old offline caches may lack unused layers. Visible magenta
            # outline is explicit fallback, never silently drop geometry.
            lpp = f.get('lpp') or tuple(f['style'].split('/', 1))
            material = next(
                (
                    l.get('material')
                    for l in self.editor.profile.layers
                    if (l['layer'], l['purpose']) == tuple(lpp)
                ),
                None,
            )
            row = [lpp, None, 0, True, material, None, None, None, None, None]
            style = decode_display(
                ['colayout-display-0.1', '', '', '', [[0, 0], [0, 0]], [], [[f['style'], row]], []]
            )['styles'][f['style']]
            self.styles[f['style']] = style
        if (
            f.get('interface')
            and f['style'] == '__module_frame__'
            and f['kind'] == 'rect'
            and not f.get('pin_name')
        ):
            group.native_box = True
            from PySide6.QtGui import QBrush

            item = PreviewRectItem(box_rect(f['bbox']))
            from ..theme import palette
            from ..module_chrome import native_frame_pen

            colors = palette(self.canvas)
            pen = native_frame_pen(colors)
            item.setPen(pen)
            item.setBrush(QBrush(QColor(colors.native_fill)))
            item.setData(0, uid)
            group.addToGroup(item, -90000)
        elif f['kind'] in ('label', 'textDisplay'):
            item = add_label(self.scene, f, style)
            if item:
                group.addToGroup(item)
        else:
            item = NativeFigureItem(
                f, style, texture=self.textures.get(f['style']), patterned=self.pattern.isChecked()
            )
            group.addToGroup(item)
        if item and f.get('interface'):
            item.setData(1, 'interface')
    has_interface_frame = any(
        f.get('interface') and f.get('style') == '__module_frame__' and f['kind'] == 'rect'
        for f in figures
    )
    if obj.bbox and not has_interface_frame and (obj.kind in ('inst', 'mosaic') or not figures):
        outline = (
            MissingMasterOutline if obj.read_only_reason == 'master_unresolved' else PreviewRectItem
        )(box_rect(obj.bbox))
        outline.setPen(QPen(QColor('#bfc8d4')))
        self.scene.addItem(outline)
        pen = outline.pen()
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.DashLine)
        outline.setPen(pen)
        outline.setData(1, 'instance_outline')
        group.addToGroup(outline, 100000)
    group.setToolTip(
        f'{obj.attributes.get("name", obj.kind)}\n{uid}\n' + (obj.read_only_reason or '')
    )
    if obj.mpp:
        label = (
            ('保护环' if obj.attributes.get('form') == 'guardring' else 'Multipart Path')
            + ' · '
            + obj.mpp.name
            + '\n整体对象：'
            + uid
        )
        for item in group.childItems():
            item.setToolTip(label)
    if obj.shape or obj.mpp:
        # QGraphicsItemGroup's default shape is its bounding rectangle.
        # Layer containers must not intercept the empty interior of a bend;
        # selection, drag and net inspection all use the scene hit ordering.
        for part in group.parts.values():
            pick = QPainterPath()
            pick.setFillRule(Qt.FillRule.WindingFill)
            for child in part.childItems():
                pick.addPath(child.mapToParent(child.shape()))
            part.exact_pick_shape = pick
    if obj.read_only_reason == 'master_unresolved':
        for part in group.parts.values():
            part.border_only = True
    for item in group.childItems():
        if item.data(1) not in ('instance_outline', 'interface'):
            item.setVisible(self.internal.isChecked() or obj.kind not in ('inst', 'mosaic'))
        if isinstance(item, NativeFigureItem):
            item.setVisible(
                (
                    item.data(1) == 'interface'
                    or self.internal.isChecked()
                    or obj.kind not in ('inst', 'mosaic')
                )
                and (self.cuts.isChecked() or not item.style['is_cut'])
            )


def refresh_graphics(self, changed, objects, *, force=False):
    deferred = getattr(self, '_deferred_graphics', set()) & objects.keys()
    self._deferred_graphics = deferred
    for uid in changed:
        obj = objects.get(uid)
        # Hidden child owners do not need new Qt paths/transforms on parent drag.
        # Materialize them before the overlay exposes that level again.
        if not force and not getattr(self,'_painting',False) and obj and uid in self.groups and uid not in getattr(self, '_displayed_uids', self.groups):
            deferred.add(uid)
            continue
        deferred.discard(uid)
        if (
            obj
            and (obj.kind in ('inst', 'mpp') or uid in self.editor.w.baseline.text_owners)
            and uid in self.groups
            and uid in self.editor.w.baseline.objects
        ):
            parent = self.editor.w.baseline.text_owners.get(uid, uid)
            before = self.editor.w.baseline.objects[parent].placement
            after = objects[parent].placement
            a, b, c, d = ORIENT[before.orientation]
            x, y = before.origin
            inverse = (a, c, b, d, -a * x - c * y, -b * x - d * y)
            self.groups[uid].setTransform(
                qt_transform(compose(transform(after.origin, after.orientation), inverse))
            )
        elif obj and obj.shape:
            f = (
                via_figures(obj.shape, self.editor.profile)
                if obj.kind == 'stdVia'
                else [shape_figure(obj.shape)]
            )
            self.draw_owner(uid, f)
        elif obj:
            self.draw_owner(uid)
        elif uid in self.groups:
            self.groups.pop(uid).remove()
    # Native-generated group members are read-only and carry their own cache.
    for group_uid, preview in self.editor.w.guard_previews.items():
        if group_uid in changed and (force or group_uid not in deferred):
            from ..model import Object

            members = {k: Object.model_validate(v) for k, v in preview['objects'].items()}
            figs, _ = figures_by_owner(
                self.editor.w.baseline, display=preview['display'], objects=members
            )
            for uid, f in figs.items():
                self.draw_owner(uid, f)
                if uid in objects and objects[uid].mpp:
                    from ..mpp import delta

                    self.groups[uid].reference_bbox = members[uid].bbox
                    self.groups[uid].setTransform(
                        qt_transform(delta(members[uid].placement, objects[uid].placement))
                    )
    for uid in set(self.groups) - set(objects):
        self.groups.pop(uid).remove()
