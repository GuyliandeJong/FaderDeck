"""Small reusable widgets: meters, sliders, faders, the splitter grip and
the mute badge."""

import time

from PySide6.QtCore import Qt, Signal, QRectF, QByteArray, QPointF
from PySide6.QtGui import (
    QBrush,
    QFont,
    QFontMetricsF,
    QIcon,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLineEdit,
    QProgressBar,
    QStyle,
    QSlider,
    QStyleOptionSlider,
    QSizePolicy,
    QSplitter,
    QSplitterHandle,
    QWidget,
)

from core import (
    CHANNEL_FADER_MIN_HEIGHT,
    MIC_METER_GAP,
    MIC_METER_SPACING,
    NORMAL_METER_WIDTH,
)
from themes import LOGO_GRADIENT, MONO_ICONS, QColor, _PlainColor, _svg_icon


class Wordmark(QWidget):
    """The program's name in the header.

    "Fader" is heavy and white; "Deck" is light and carries the logo's
    gradient, so the name reads as a mark and not as a line of text. A
    stylesheet cannot colour text with a gradient, hence the painting.
    """

    WORDS = (("Fader", QFont.Weight.ExtraBold), ("Deck", QFont.Weight.Normal))
    PIXEL_SIZE = 18

    def __init__(self):
        super().__init__()
        self._fonts = []
        width = 0.0
        height = 0.0
        for _text, weight in self.WORDS:
            font = QFont("Segoe UI")
            font.setPixelSize(self.PIXEL_SIZE)
            font.setWeight(weight)
            self._fonts.append(font)
        for (text, _weight), font in zip(self.WORDS, self._fonts):
            metrics = QFontMetricsF(font)
            width += metrics.horizontalAdvance(text)
            height = max(height, metrics.height())
        self.setFixedSize(int(width) + 2, int(height) + 2)
        self.setToolTip("FaderDeck")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        x = 0.0
        last = len(self.WORDS) - 1
        for index, ((text, _weight), font) in enumerate(
            zip(self.WORDS, self._fonts)
        ):
            advance = QFontMetricsF(font).horizontalAdvance(text)
            if index == last:
                # The gradient runs across this word only, and diagonally like
                # the tile's: blue at the top left, purple at the bottom right.
                metrics = QFontMetricsF(font)
                middle = self.height() / 2
                top = middle - metrics.capHeight() / 2
                bottom = middle + metrics.capHeight() / 2
                # A true 45 degree slope, as on the tile: the colour depends
                # on x + y, and the run is long enough to cover the word.
                run = (advance + (bottom - top)) / 2
                gradient = QLinearGradient(x, top, x + run, top + run)
                gradient.setColorAt(0.0, _PlainColor(LOGO_GRADIENT[0]))
                gradient.setColorAt(1.0, _PlainColor(LOGO_GRADIENT[1]))
                painter.setPen(QPen(QBrush(gradient), 1))
            else:
                painter.setPen(QColor("#e6edf3"))
            painter.setFont(font)
            painter.drawText(
                QRectF(x, 0, advance + 1, self.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                text,
            )
            x += advance
        painter.end()


class VUMeter(QProgressBar):

    """Simple vertical VU meter."""

    def __init__(self, label=""):
        super().__init__()
        self._label = label

        self.setOrientation(Qt.Orientation.Vertical)

        # Keep the progress-bar value itself in dBFS. 0 dBFS is the top.
        # The previous build used -60..12 and then normalized the dB value
        # into that range a second time, which made the visual position wrong.
        self.setRange(-60, 0)

        self.setValue(-60)

        self.setTextVisible(False)

        self.setMinimumWidth(NORMAL_METER_WIDTH)
        self.setMaximumWidth(NORMAL_METER_WIDTH)

        # Height is flexible: the Mic meters follow the fader length.
        self.setMinimumHeight(40)

        # Vertical meters should rise from the bottom as the signal increases.
        self.setInvertedAppearance(False)
        self._display_level = float(self.minimum())
        self._target_level = float(self.minimum())
        self._last_animation = time.monotonic()


    def paintEvent(self, event):
        """Draw a bottom-up meter with color thresholds fixed to dB scale."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        outer = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor("#303a45"), 1))
        painter.setBrush(QColor("#111820"))
        painter.drawRoundedRect(outer, 5, 5)

        inner = outer.adjusted(2, 2, -2, -2)
        span = max(1, self.maximum() - self.minimum())
        fraction = max(0.0, min(1.0, (self.value() - self.minimum()) / span))
        filled_height = inner.height() * fraction
        if filled_height <= 0:
            self._draw_scale(painter, inner)
            painter.end()
            return

        gradient = QLinearGradient(0, inner.bottom(), 0, inner.top())
        # Anchor the warning colors to dBFS values rather than normalized
        # bar height, so 0 dBFS remains the red/clipping threshold.
        def db_position(db):
            return max(0.0, min(1.0, (db - self.minimum()) / span))

        gradient.setColorAt(db_position(-60), QColor("#27c76f"))
        gradient.setColorAt(db_position(-18), QColor("#54db39"))
        gradient.setColorAt(db_position(-10.8), QColor("#a5e52b"))
        gradient.setColorAt(db_position(-6), QColor("#f5df27"))
        gradient.setColorAt(db_position(-2.4), QColor("#ff9637"))
        gradient.setColorAt(db_position(0), QColor("#ff514b"))
        gradient.setColorAt(1.00, QColor("#ff514b"))

        fill = QRectF(
            inner.left(),
            inner.bottom() - filled_height,
            inner.width(),
            filled_height,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.fillRect(fill, QBrush(gradient))
        self._draw_scale(painter, inner)
        painter.end()

    def _draw_scale(self, painter, inner):
        """Draw faint dB ticks and the channel letter, visible at silence."""
        span = max(1, self.maximum() - self.minimum())
        painter.setPen(QPen(QColor(255, 255, 255, 46), 1))
        for db in (-48, -36, -24, -12, -6):
            y = inner.bottom() - inner.height() * (db - self.minimum()) / span
            painter.drawLine(
                QPointF(inner.left() + 3, y), QPointF(inner.right() - 3, y)
            )
        # A slim (compact view) meter has no room for the letter.
        if self._label and self.width() >= NORMAL_METER_WIDTH:
            font = painter.font()
            font.setPixelSize(10)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#8ba0b5"))
            painter.drawText(
                QRectF(inner.left(), inner.top() + 2, inner.width(), 14),
                Qt.AlignmentFlag.AlignCenter,
                self._label,
            )


    def set_level(self, level):
        """Set the latest target level from the audio worker."""
        try:
            level = float(level)
        except (TypeError, ValueError):
            level = float(self.minimum())

        minimum = float(self.minimum())

        if level <= -199.0:
            target = minimum
            self.setToolTip("-∞ dB")
        else:
            target = max(minimum, min(0.0, level))
            self.setToolTip(f"{level:.1f} dB")

        self._target_level = target

    def _update_visual_level(self, display):
        """Apply the current animated dB level to the meter widget."""
        minimum = float(self.minimum())
        display = max(minimum, min(0.0, float(display)))
        self._display_level = display

        # The widget range is already dBFS, so do not normalize and then
        # convert back into the progress-bar range. Write the displayed dB
        # directly. paintEvent() converts that dB value to a fill fraction.
        self.setValue(int(round(display)))

    def animate_level(self):
        """Smoothly animate the displayed level toward the latest sample."""
        now = time.monotonic()
        elapsed = min(now - self._last_animation, 0.05)
        self._last_animation = now

        minimum = float(self.minimum())
        display = float(self._display_level)
        target = float(self._target_level)

        # Fast attack so short mic taps are visible immediately without
        # stepping from one 33 ms sample directly to another.
        if target > display:
            attack_speed = 500.0
            display += attack_speed * elapsed
            if display > target:
                display = target

        # Controlled release. A continuous worker sample means we no longer
        # need an event-timeout to force the meter down.
        elif target < display:
            release_speed = 110.0
            display -= release_speed * elapsed
            if display < target:
                display = target

        if display < minimum:
            display = minimum
        elif display > 0.0:
            display = 0.0

        self._display_level = display
        self._update_visual_level(display)

class NumericEdit(QLineEdit):
    """Editable numeric field that selects its contents when focused."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            "QLineEdit { background: #0d141b; border: 1px solid #314558; "
            "border-radius: 4px; padding: 2px 5px; }"
            "QLineEdit:hover { border-color: #4b6179; }"
            "QLineEdit:focus { border-color: #58a6ff; background: #101c28; }"
        )

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.selectAll()


class MicLevelBar(QWidget):
    """Horizontal Mic input level with the processing thresholds marked.

    Thresholds only mean something next to the level they are compared with,
    so the Mic Processing window shows both on one scale.
    """

    MIN_DB = -60.0

    def __init__(self):
        super().__init__()
        self.setFixedHeight(40)
        self.setToolTip(
            "Mic input level (before processing) with the gate and "
            "compressor thresholds"
        )
        self._markers = []
        self._target = self.MIN_DB
        self._display = self.MIN_DB
        self._last_animation = time.monotonic()

    def add_marker(self, label, color, getter):
        """Mark a threshold; getter returns its current value in dB."""
        self._markers.append((label, color, getter))

    def set_level(self, level):
        self._target = max(self.MIN_DB, min(0.0, float(level)))

    def animate(self):
        """Fast attack, slower release, like the Mic strip meters."""
        now = time.monotonic()
        elapsed = min(now - self._last_animation, 0.05)
        self._last_animation = now
        display = self._display
        if self._target > display:
            display = min(self._target, display + 500.0 * elapsed)
        elif self._target < display:
            display = max(self._target, display - 110.0 * elapsed)
        if display != self._display:
            self._display = display
            self.update()

    def _x(self, bar, db):
        fraction = (db - self.MIN_DB) / -self.MIN_DB
        return bar.left() + bar.width() * max(0.0, min(1.0, fraction))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bar = QRectF(1, 5, self.width() - 2, 14)

        painter.setPen(QPen(QColor("#303a45"), 1))
        painter.setBrush(QColor("#111820"))
        painter.drawRoundedRect(bar, 4, 4)

        inner = bar.adjusted(2, 2, -2, -2)
        filled = self._x(inner, self._display) - inner.left()
        if filled > 0:
            gradient = QLinearGradient(inner.left(), 0, inner.right(), 0)
            gradient.setColorAt(0.0, QColor("#27c76f"))
            gradient.setColorAt(0.7, QColor("#54db39"))
            gradient.setColorAt(0.9, QColor("#f5df27"))
            gradient.setColorAt(1.0, QColor("#ff514b"))
            painter.fillRect(
                QRectF(inner.left(), inner.top(), filled, inner.height()),
                QBrush(gradient),
            )

        font = painter.font()
        font.setPixelSize(10)
        font.setBold(True)
        painter.setFont(font)
        markers = []
        for label, color, getter in self._markers:
            try:
                markers.append((float(getter()), label, QColor(color)))
            except Exception:
                continue
        markers.sort(key=lambda marker: marker[0])
        for index, (db, label, color) in enumerate(markers):
            x = self._x(inner, db)
            painter.setPen(QPen(color, 2))
            painter.drawLine(QPointF(x, bar.top() - 3), QPointF(x, bar.bottom() + 3))
            # Text of the lowest threshold goes left of its line and the
            # others right, so two nearby thresholds stay readable.
            text = f"{label} {db:.0f} dB"
            if index == 0 and len(markers) > 1:
                rect = QRectF(x - 124, bar.bottom() + 4, 120, 14)
                align = Qt.AlignmentFlag.AlignRight
            else:
                rect = QRectF(x + 4, bar.bottom() + 4, 120, 14)
                align = Qt.AlignmentFlag.AlignLeft
            painter.drawText(rect, align | Qt.AlignmentFlag.AlignVCenter, text)
        painter.end()


class PanelSlider(QSlider):
    """Horizontal slider of a Mic processing parameter.

    It ignores the mouse wheel until it has been clicked, so scrolling over
    the window cannot change the live microphone by accident, and it can show
    a notch at a reference value.
    """

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(26)
        self._mark = None

    def set_mark(self, value):
        self._mark = value
        self.update()

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()

    def paintEvent(self, event):
        super().paintEvent(event)
        span = self.maximum() - self.minimum()
        if self._mark is None or span <= 0:
            return

        option = QStyleOptionSlider()
        self.initStyleOption(option)
        style = self.style()
        groove = style.subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderGroove,
            self,
        )
        handle = style.subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderHandle,
            self,
        )
        travel = groove.width() - handle.width()
        x = (
            groove.left()
            + handle.width() / 2
            + travel * (self._mark - self.minimum()) / span
        )
        y = self.height() / 2
        painter = QPainter(self)
        painter.setPen(QPen(QColor("#8ba0b5"), 2))
        painter.drawLine(QPointF(x, y + 8), QPointF(x, y + 12))
        painter.end()


class FineControlSlider(QSlider):
    """Slider with predictable, one-step-per-wheel-notch adjustments."""

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._wheel_remainder = 0
        # Step of one wheel notch; None means singleStep(). With Shift held
        # the wheel moves by shift_step, or singleStep() when that is None.
        self.wheel_step = None
        self.shift_step = None

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if not delta:
            event.ignore()
            return

        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        step = self.singleStep()
        if shift and self.shift_step is not None:
            step = self.shift_step
        elif self.wheel_step is not None and not shift:
            step = self.wheel_step

        self._wheel_remainder += delta
        notches = int(self._wheel_remainder / 120)
        if notches:
            self._wheel_remainder -= notches * 120
            self.setValue(self.value() + notches * step)
        event.accept()


class MixerFader(FineControlSlider):
    """Vertical gain fader with a dB scale beside its track."""

    SCALE_DB = (12, 0, -12, -24, -36, -48, -60)
    UNITS_PER_DB = 100
    WIDTH = 100  # leaves room for the scale labels; the track stays centered
    show_labels = True

    def mouseDoubleClickEvent(self, event):
        # A double right-click puts the fader back at 0 dB; a single one
        # does nothing, so a stray click cannot reset it.
        if event.button() == Qt.MouseButton.RightButton:
            self.setValue(0)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)

        option = QStyleOptionSlider()
        self.initStyleOption(option)
        style = self.style()
        groove = style.subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderGroove,
            self,
        )
        handle = style.subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderHandle,
            self,
        )
        travel = groove.height() - handle.height()
        span = self.maximum() - self.minimum()
        if travel <= 0 or span <= 0:
            return

        center = self.width() / 2
        painter = QPainter(self)
        font = painter.font()
        font.setPixelSize(9)
        painter.setFont(font)
        for db in self.SCALE_DB:
            value = db * self.UNITS_PER_DB
            y = (
                groove.top()
                + handle.height() / 2
                + travel * (self.maximum() - value) / span
            )
            unity = db == 0
            length = 8 if unity else 4
            painter.setPen(QPen(QColor("#e6edf3" if unity else "#4b5a6b"), 1))
            painter.drawLine(
                QPointF(center - 14 - length, y), QPointF(center - 14, y)
            )
            painter.drawLine(
                QPointF(center + 14, y), QPointF(center + 14 + length, y)
            )
            if not self.show_labels:
                continue
            painter.setPen(QColor("#e6edf3" if unity else "#7d8ea0"))
            painter.drawText(
                QRectF(center + 25, y - 7, 24, 14),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"{db:+d}" if db else "0",
            )
        painter.end()


class MicFaderArea(QWidget):
    """Mic fader and meters.

    The fader is centered with the same stretch layout the other strips use,
    so it lines up exactly with the gain readout and the other faders. The two
    input meters are positioned relative to the fader instead of being part of
    the layout, so they can never push the fader off center.
    """

    def __init__(self, fader, meters):
        super().__init__()
        self.fader = fader
        self.meters = list(meters)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addStretch(1)
        row.addWidget(fader)
        row.addStretch(1)

        for meter in self.meters:
            meter.setParent(self)

        self.setMinimumHeight(CHANNEL_FADER_MIN_HEIGHT)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_meters()

    def showEvent(self, event):
        super().showEvent(event)
        self._place_meters()

    def _place_meters(self):
        if not self.meters:
            return
        self.layout().activate()
        widths = [meter.maximumWidth() for meter in self.meters]
        total = sum(widths) + MIC_METER_SPACING * (len(widths) - 1)
        # Keep the usual gap when there is room, and close up to the fader
        # in a narrow card rather than sliding under it.
        gap = min(MIC_METER_GAP, max(4, self.fader.x() - total - 2))
        x = max(0, self.fader.x() - gap - total)
        y = self.fader.y()
        height = self.fader.height()
        for meter, width in zip(self.meters, widths):
            meter.setGeometry(x, y, width, height)
            meter.show()
            x += width + MIC_METER_SPACING


class LiveVolumeSlider(FineControlSlider):
    """Volume slider with the live session peak drawn on its track.

    Clicking or dragging anywhere on the track directly sets the volume,
    rather than requiring the user to grab the small thumb first.
    """

    thumb_color = "#58a6ff"

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._audio_level = 0.0

    def _set_value_from_position(self, x):
        margin = 8
        usable_width = max(1, self.width() - (margin * 2))
        position = max(0, min(usable_width, int(x) - margin))
        value = QStyle.sliderValueFromPosition(
            self.minimum(),
            self.maximum(),
            position,
            usable_width,
            False,
        )
        self.setValue(value)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._set_value_from_position(event.position().x())
            self.setSliderDown(True)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.isSliderDown() and event.buttons() & Qt.MouseButton.LeftButton:
            self._set_value_from_position(event.position().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isSliderDown():
            self._set_value_from_position(event.position().x())
            self.setSliderDown(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def set_audio_level(self, level):
        self._audio_level = max(0.0, min(1.0, float(level)))
        self.update()

    def paintEvent(self, event):
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        style = self.style()
        groove = style.subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderGroove,
            self,
        )
        handle = style.subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderHandle,
            self,
        )

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(
            groove.left() + 8,
            handle.center().y() - 3,
            max(1, groove.width() - 16),
            6,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#30363d"))
        painter.drawRoundedRect(track, 3, 3)

        if self._audio_level > 0.0:
            live_track = QRectF(
                track.left(),
                track.top(),
                max(1.0, track.width() * self._audio_level),
                track.height(),
            )
            painter.setBrush(QColor("#3fb950"))
            painter.drawRoundedRect(live_track, 3, 3)

        # Draw the volume thumb on the exact same centerline as the meter.
        handle_width = max(14, handle.width())
        handle_height = 14
        thumb = QRectF(
            handle.center().x() - handle_width / 2,
            track.center().y() - handle_height / 2,
            handle_width,
            handle_height,
        )
        thumb_color = QColor(self.thumb_color)
        if self.isSliderDown():
            thumb_color = thumb_color.lighter(125)
        painter.setBrush(thumb_color)
        painter.drawRoundedRect(thumb, 4, 4)
        painter.end()


# What the mute badge and the tray icon show: (text, colour) per state.
MUTE_INDICATORS = {
    "muted": ("Mic muted", "#f85149"),
    "stream": ("Not on stream", "#f0883e"),
}


def mute_indicator_state(mic_muted, stream_muted):
    """Which warning the badge and the tray icon show: "muted", "stream" or
    None for nothing. stream_muted is None when no stream output is set."""
    if mic_muted:
        return "muted"  # nobody hears you: the bigger warning wins
    if stream_muted:
        return "stream"  # None (no stream output set) is no warning
    return None


def badged_icon(icon, colour, size=32):
    """The tray icon with a coloured dot holding a crossed-out microphone."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.drawPixmap(0, 0, icon.pixmap(size, size))
    dot = size * 0.62
    box = QRectF(size - dot, size - dot, dot, dot)
    painter.setPen(QPen(QColor("#0d1117"), size * 0.06))
    painter.setBrush(QColor(colour))
    painter.drawEllipse(box.adjusted(1, 1, -1, -1))
    mic = dot * 0.62
    QSvgRenderer(QByteArray(
        MONO_ICONS["mic_off"].replace("#d7e1eb", "#ffffff").encode("utf-8")
    )).render(painter, QRectF(box.center().x() - mic / 2,
                              box.center().y() - mic / 2, mic, mic))
    painter.end()
    return QIcon(pixmap)


class MuteBadge(QWidget):
    """A small label that stays on top of other windows while the
    microphone is muted. It never takes the focus, so a game keeps the
    keyboard. Drag it to move it; moved() reports where it was left."""

    moved = Signal(object)

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setToolTip("FaderDeck. Drag to move; turn it off in Settings, Microphone.")
        self.state = None
        self._grab = None
        font = QFont(self.font())
        font.setPointSize(11)
        font.setBold(True)
        self.setFont(font)
        self.icon = _svg_icon(MONO_ICONS["mic_off"].replace("#d7e1eb", "#ffffff"), 18)

    def set_state(self, state):
        self.state = state
        text = MUTE_INDICATORS[state][0]
        width = QFontMetricsF(self.font()).horizontalAdvance(text)
        self.setFixedSize(int(width) + 58, 38)
        self.update()

    def place(self, point=None):
        """Put it at point when that is on a screen; else top centre."""
        screen = QApplication.screenAt(point) if point is not None else None
        if screen is None:
            area = QApplication.primaryScreen().availableGeometry()
            self.move(area.center().x() - self.width() // 2, area.top() + 24)
        else:
            area = screen.availableGeometry()
            self.move(
                min(max(point.x(), area.left()), area.right() - self.width()),
                min(max(point.y(), area.top()), area.bottom() - self.height()),
            )

    def paintEvent(self, _event):
        if self.state is None:
            return
        text, colour = MUTE_INDICATORS[self.state]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        fill = QColor(colour)
        fill.setAlpha(235)
        painter.setPen(QPen(QColor(0, 0, 0, 90), 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 19, 19)
        self.icon.paint(painter, 14, 10, 18, 18)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(QRectF(40, 0, self.width() - 52, self.height()),
                         Qt.AlignmentFlag.AlignVCenter, text)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._grab = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if self._grab is not None:
            self.move(event.globalPosition().toPoint() - self._grab)

    def mouseReleaseEvent(self, _event):
        if self._grab is not None:
            self._grab = None
            self.moved.emit(self.pos())


class GripSplitterHandle(QSplitterHandle):
    """Splitter handle with a visible grip, so it is obviously draggable."""

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self._hover = False
        self._pressed = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setToolTip("Drag to resize • double-click to reset")

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self._pressed = True
        self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        splitter = self.splitter()
        if hasattr(splitter, "reset_sizes"):
            splitter.reset_sizes()
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bar = QRectF(self.rect()).adjusted(0, 3, 0, -3)
        active = self._hover or self._pressed
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#243b52" if active else "#18232e"))
        painter.drawRoundedRect(bar, 3, 3)
        painter.setBrush(QColor("#58a6ff" if active else "#4b6179"))
        center = bar.center()
        for offset in (-14, 0, 14):
            painter.drawEllipse(QPointF(center.x() + offset, center.y()), 2.0, 2.0)


class GripSplitter(QSplitter):
    """Splitter that uses the grip handle and can return to default sizes."""

    def __init__(self, orientation, default_sizes, parent=None):
        super().__init__(orientation, parent)
        self._default_sizes = list(default_sizes)
        self.setHandleWidth(14)
        self.setChildrenCollapsible(False)
        self.setOpaqueResize(True)

    def createHandle(self):
        return GripSplitterHandle(self.orientation(), self)

    def reset_sizes(self):
        self.setSizes(self._default_sizes)
