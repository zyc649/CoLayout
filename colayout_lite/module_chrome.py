"""Screen-sized hierarchy captions; native geometry and device text stay separate."""
from PySide6.QtCore import Qt,QRectF
from PySide6.QtGui import QFont,QFontMetrics,QColor,QPen,QPainterPath,QPainter
from PySide6.QtWidgets import QGraphicsSimpleTextItem


def native_frame_pen(colors):
    pen=QPen(QColor(colors.native_border),1.5);pen.setCosmetic(True)
    return pen


class ModuleCaption(QGraphicsSimpleTextItem):
    def __init__(self,text,*,native,color,background):
        super().__init__();self.full_text=text;self.native=native;self.background=background;self.module_bounds=None
        font=QFont('Microsoft YaHei UI');font.setPixelSize(12);self.setFont(font)
        self.setText(QFontMetrics(font).elidedText(text,Qt.TextElideMode.ElideRight,270))
        self.setBrush(QColor(color))

    @property
    def text_offset(self):return 15 if self.native else 0

    def boundingRect(self):
        return super().boundingRect().adjusted(0,0,self.text_offset,0)

    def shape(self):
        path=QPainterPath();path.addRect(self.boundingRect());return path

    def paint(self,painter,option,widget=None):
        painter.save()
        try:
            painter.fillRect(self.boundingRect().adjusted(-2,-2,4,2),QColor(self.background))
            if self.native:
                # Fixed screen units, neutral text color and symmetric shackle;
                # no platform-dependent emoji font or stretched world glyph.
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setPen(QPen(self.brush().color(),1.2));painter.setBrush(Qt.BrushStyle.NoBrush)
                top=(super().boundingRect().height()-12)/2
                shackle=QPainterPath();shackle.moveTo(3.5,top+5)
                shackle.lineTo(3.5,top+3);shackle.cubicTo(3.5,top,8.5,top,8.5,top+3);shackle.lineTo(8.5,top+5)
                painter.drawPath(shackle);painter.drawRoundedRect(QRectF(1.5,top+5,9,7),.7,.7)
                painter.drawLine(6,round(top+8),6,round(top+10))
                painter.translate(self.text_offset,0)
            super().paint(painter,option,widget)
        finally:painter.restore()
