"""Readability budget for the dark shell and temporary electrical results.

These checks need no QApplication and do not constrain exact theme hex values.
They guard against making secondary text or functional highlights as subdued as
the everyday module chrome during future palette adjustments.
"""
import pytest
from PySide6.QtGui import QColor, QPalette

from colayout_lite.compact_style import window_palette
from colayout_lite.theme import COMPACT


def _luminance(color):
    color = QColor(color)
    channels = (color.redF(), color.greenF(), color.blueF())
    linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4
              for c in channels]
    return sum(c * weight for c, weight in zip(linear, (.2126, .7152, .0722)))


def _contrast(foreground, background):
    low, high = sorted((_luminance(foreground), _luminance(background)))
    return (high + .05) / (low + .05)


@pytest.mark.parametrize('foreground,background', [
    ('WindowText', 'Window'), ('Text', 'Base'), ('ButtonText', 'Button'),
    ('PlaceholderText', 'Base'), ('HighlightedText', 'Highlight'),
])
def test_active_shell_text_remains_readable(foreground, background):
    colors = window_palette()
    assert _contrast(colors.color(getattr(QPalette.ColorRole, foreground)),
                     colors.color(getattr(QPalette.ColorRole, background))) >= 4.5


@pytest.mark.parametrize('token,minimum', [
    ('net_connected', 7), ('pin_contact', 7), ('pin_target', 7),
    ('net_short', 4.5), ('pin_error', 4.5), ('pin', 7),
    ('local_label', 4.5), ('native_label', 4.5),
])
def test_results_and_pin_labels_are_legible_on_canvas(token, minimum):
    assert _contrast(getattr(COMPACT, token), COMPACT.background) >= minimum


def test_window_surface_frames_canvas_without_light_dark_jump():
    chrome = window_palette().color(QPalette.ColorRole.Window)
    assert _luminance(chrome) > _luminance(COMPACT.background)
    assert _contrast(chrome, COMPACT.background) < 1.5
