import sys, signal
import threading
import queue
from collections import namedtuple

from PyQt5.QtCore import Qt, QSignalBlocker, QThread, pyqtSignal
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
import leglight

DiscoverTask = namedtuple("DiscoverTask", ("timeout",))

LightView = namedtuple("LightState", ("ip", "name", "active", "brightness", "temperature"))

class LightController(QThread):
    def __init__(self, q):
        self.lights = {}                     # mapping from model to view
        self.ui_repaint = pyqtSignal()
        self.tab_repaint = pyqtSignal()

    def run(self):
        while True:
            task = self.q.get()

            if isinstance(task, DiscoverTask):
                timeout = task.timeout
                leglight.discover(timeout)
                repaint.emit()


class ElgatoMenu(QMenu):
    def mouseReleaseEvent(self, e):
        action = self.activeAction()

        if action is not None and isinstance(action, SliderAction):
            blocker = QSignalBlocker(action)
        else:
            return super().mouseReleaseEvent(e)

class Slider(QSlider):
    def mousePressEvent(self, event):
        super(Slider, self).mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            val = self.pixelPosToRangeValue(event.pos())
            self.setValue(val)

    def pixelPosToRangeValue(self, pos):
        options = QStyleOptionSlider()
        self.initStyleOption(options)
        groove = self.style().subControlRect(
            QStyle.CC_Slider, options,
            QStyle.SC_SliderGroove, self)
        slider_handle = self.style().subControlRect(
            QStyle.CC_Slider, options,
            QStyle.SC_SliderHandle, self)

        slider_left = groove.x()
        slider_right = groove.right() - slider_handle.width() + 1
        span = slider_right - slider_left

        pr = pos - slider_handle.center() + slider_handle.topLeft()
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), pr.x() - slider_left,
            span, options.upsideDown)


class SliderAction(QWidgetAction):
    def __init__(self, name, min_val, max_val, tick_interval, parent=None):
        QWidgetAction.__init__(self, parent)
        widget = QWidget(None)
        layout = QVBoxLayout()

        label = QLabel(name)
        layout.addWidget(label)

        option = Slider(Qt.Horizontal, widget)
        option.setRange(min_val, max_val)
        option.setFocusPolicy(Qt.StrongFocus)
        option.setTickPosition(QSlider.TicksAbove)
        option.setTickInterval(tick_interval)
        option.setSingleStep(1)

        option.sliderMoved.connect(lambda value: QToolTip.showText(QCursor.pos(), f"{value}", None))

        option.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        sz = ((max_val - min_val) // tick_interval) * 10
        option.setMinimumWidth(sz)

        layout.addWidget(option)
        widget.setLayout(layout)
        self.setDefaultWidget(widget)


class TabWidgetAction(QWidgetAction):
    def __init__(self, q, parent=None):
        QWidgetAction.__init__(self, parent)
        self.q = q

        self.widget = QTabWidget()
        self.setDefaultWidget(self.widget)

    def add_tab(self, light_view):
        individual_tab_widget = QWidget(self.widget)
        layout = QVBoxLayout()

        brightness_action = SliderAction("Brightness", 0, 100, 10, individual_tab_widget)
        temperature_action = SliderAction("Color Temperature", 2900, 7000, 100, individual_tab_widget)

        layout.addWidget(brightness_action)
        layout.addWidget(temperature_action)

        individual_tab_widget.setLayout(layout)

        self.widget.addTab(individual_tab_widget,
                           f"{light_view.name}: {light_view.ip}")


def main():
    app = QApplication([])
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app.setQuitOnLastWindowClosed(False)

    q = queue.Queue()
    controller = LightController(q)
    #controller.repaint.connect()

    icon = QIcon("elgato_logo_icon.png")

    tray = QSystemTrayIcon()
    tray.setIcon(icon)
    tray.setVisible(True)

    menu = ElgatoMenu()
    tab_widget_action = TabWidgetAction(q)
    tab_widget_action.add_tab(LightView("blah", "blah", False, 100, 3000))
    menu.addAction(tab_widget_action)
    #brightness_action = SliderAction("Brightness", 0, 100, 10, menu)
    #temperature_action = SliderAction("Color Temperature", 2900, 7000, 100, menu)

    #menu.addAction(brightness_action)
    #menu.addAction(temperature_action)

    quit = QAction("Quit")
    quit.triggered.connect(app.quit)
    menu.addAction(quit)

    def activation_event(event):
        menu.exec(QCursor.pos())

    tray.activated.connect(activation_event)
    #tray.setContextMenu(menu)

    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
