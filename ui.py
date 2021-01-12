import sys, signal
import threading
import queue
from collections import OrderedDict, namedtuple

from PyQt5.QtCore import Qt, QSignalBlocker, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
import leglight

DEFAULT_TIMEOUT = 2
DEFAULT_REFRESH = 3000

DiscoverTask = namedtuple("DiscoverTask", ("timeout",))
QueryTask = namedtuple("QueryTask", ("serial",))
AdjustTask = namedtuple("AdjustTask", ("serial", "active", "brightness", "temperature"))

LightView = namedtuple("LightState", ("ip", "serial", "name", "active", "brightness", "temperature"))

# TODO: Think more about interleaving calls to `force_rediscovery`
# I don't think that they can deadlock or race, but it's worth
# thinking about
def force_rediscovery(q):
    q.put(DiscoverTask(DEFAULT_TIMEOUT))

class LightController(QThread):
    tab_create = pyqtSignal(str, LightView)
    tab_destroy = pyqtSignal(str)
    tab_update = pyqtSignal(str, LightView)

    def __init__(self, q, parent=None):
        super(LightController, self).__init__(parent)
        self.q = q

        self.lights = OrderedDict()                     # mapping from serial to (model, view)

    def eliminate_tab(self, serial):
        self.tab_destroy.emit(serial)
        del self.lights[serial]
        force_rediscovery(self.q)
        self.q.task_done()

    def run(self):
        while True:
            task = self.q.get()

            if isinstance(task, DiscoverTask):
                timeout = task.timeout
                new_lights_model = leglight.discover(timeout)
                new_lights_set = frozenset(light.serialNumber for light in new_lights_model)

                new_lights_state = OrderedDict()
                seen_lights = {}

                if new_lights_set != frozenset(serial for serial in self.lights.keys()):
                    for light_serial, model, light_view in self.lights:
                        if light_serial not in new_lights_set:
                            self.tab_destroy.emit(light_serial)
                        else:
                            new_lights_state[light_serial] = (model, light_view)
                            new_lights_state.move_to_end(light_serial)
                        seen_lights.add(light_serial)
                    for new_light_model in new_lights_model:
                        new_serial = new_light_model.serialNumber
                        if new_serial not in seen_lights:
                            new_view = LightView(
                                ip=new_light_model.address,
                                serial=new_serial,
                                name=new_light_model.productName,
                                active=new_light_model.isOn,
                                brightness=new_light_model.isBrightness,
                                temperature=new_light_model.isTemperature
                            )
                            new_light_state = (new_light_model, new_view)
                            new_lights_state[new_serial] = new_light_state
                            new_lights_state.move_to_end(new_serial)

                            self.tab_create.emit(new_serial, new_view)
                    self.lights = new_lights_state
            elif isinstance(task, QueryTask):
                if task.serial not in self.lights.keys():
                    self.tab_destroy.emit(task.serial)
                else:
                    model, original_view = self.lights[task.serial]
                    try:
                        new_info = model.info()
                    except:
                        self.eliminate_tab(task.serial)
                        return
                    updated_view = LightView(
                        ip=original_view.ip,
                        serial=original_view.serial,
                        name=original_view.name,
                        active=new_info["on"],
                        brightness=new_info["brightness"],
                        temperature=new_info["temperature"]
                    )
                    self.tab_update.emit(task.serial, updated_view)
                    self.lights[task.serial] = (model, updated_view)
            elif isinstance(task, AdjustTask):
                if task.serial not in self.lights.keys():
                    self.tab_destroy.emit(task.serial)
                else:
                    model, original_view = self.lights[task.serial]
                    try:
                        if task.active is not None:
                            model.on() if task.active else model.off()
                        if task.brightness is not None:
                            model.brightness(task.brightness)
                        if task.temperature is not None:
                            model.color(task.temperature)
                    except:
                        self.eliminate_tab(task.serial)
                        return
            self.q.task_done()


class ElgatoMenu(QMenu):
    close_menu = pyqtSignal()

    def __init__(self, parent=None):
        super(ElgatoMenu, self).__init__(parent)

    def mouseReleaseEvent(self, e):
        action = self.activeAction()

        if action is not None and isinstance(action, TabWidgetAction):
            blocker = QSignalBlocker(action)
        else:
            return super().mouseReleaseEvent(e)

    def closeEvent(self, e):
        super(ElgatoMenu, self).closeEvent(e)
        self.close_menu.emit()


class ElgatoSlider(QSlider):
    def __init__(self, controller_callback, parent=None):
        super(ElgatoSlider, self).__init__(Qt.Horizontal, parent)
        self.controller_callback = controller_callback

    def mousePressEvent(self, event):
        super(ElgatoSlider, self).mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            val = self.pixelPosToRangeValue(event.pos())
            self.setValue(val)

    def mouseReleaseEvent(self, event):
        self.controller_callback(self.value())

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


class ElgatoLabeledSlider(QWidget):
    def __init__(self, controller_callback, name, min_val,
                 max_val, tick_interval, parent=None):
        QWidget.__init__(self, parent)

        layout = QVBoxLayout()

        label = QLabel(name)
        layout.addWidget(label)

        self.option = ElgatoSlider(controller_callback, self)
        self.option.setRange(min_val, max_val)
        self.option.setFocusPolicy(Qt.StrongFocus)
        self.option.setTickPosition(QSlider.TicksAbove)
        self.option.setTickInterval(tick_interval)
        self.option.setSingleStep(1)

        self.option.sliderMoved.connect(lambda value: QToolTip.showText(QCursor.pos(), f"{value}", None))

        self.option.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        sz = ((max_val - min_val) // tick_interval) * 10
        self.option.setMinimumWidth(sz)

        layout.addWidget(self.option)
        self.setLayout(layout)

    def set_position(self, pos):
        self.option.setValue(pos)


class TabWidgetAction(QWidgetAction):
    def __init__(self, q, parent=None):
        QWidgetAction.__init__(self, parent)
        self.q = q

        self.serial_to_view = OrderedDict()

        self.widget = QTabWidget()
        self.setDefaultWidget(self.widget)

    def add_tab(self, light_serial, light_view):
        individual_tab_widget = QWidget(self.widget)
        individual_tab_widget.serial = light_serial
        layout = QVBoxLayout()

        brightness_callback = lambda v: \
            self.q.put(AdjustTask(serial=light_serial,
                                  active=None,
                                  brightness=v,
                                  temperature=None))
        temperature_callback = lambda v: \
            self.q.put(AdjustTask(serial=light_serial,
                                  active=None,
                                  brightness=None,
                                  temperature=v))

        brightness_slider = ElgatoLabeledSlider(brightness_callback,
                                                "Brightness",
                                                0, 100, 10,
                                                individual_tab_widget)
        temperature_slider = ElgatoLabeledSlider(temperature_callback,
                                                 "Color Temperature",
                                                 2900, 7000, 100,
                                                 individual_tab_widget)

        layout.addWidget(brightness_slider)
        layout.addWidget(temperature_slider)

        self.serial_to_view[light_serial] = \
            (brightness_slider, temperature_slider)
        self.serial_to_view.move_to_end(light_serial)

        brightness_slider.set_position(light_view.brightness)
        temperature_slider.set_position(light_view.temperature)

        individual_tab_widget.setLayout(layout)

        self.widget.addTab(individual_tab_widget,
                           f"{light_view.name}: {light_serial}")

    def update_tab(self, light_serial, light_view):
        try:
            brightness_slider, temperature_slider = self.serial_to_view[light_serial]
            brightness_slider.set_position(light_view.brightness)
            temperature_slider.set_position(light_view.temperature)
        except:
            pass

    def destroy_tab(self, light_serial):
        try:
            individual_tab_widget = self.serial_to_view[light_serial][0].parentWidget()
            index = self.widget.indexOf(individual_tab_widget)
            self.widget.removeTab(index)
        except:
            pass

def main():
    app = QApplication([])
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app.setQuitOnLastWindowClosed(False)

    q = queue.Queue()
    q.put(DiscoverTask(DEFAULT_TIMEOUT))
    controller = LightController(q)

    icon = QIcon("elgato_logo_icon.png")

    tray = QSystemTrayIcon()
    tray.setIcon(icon)
    tray.setVisible(True)

    menu = ElgatoMenu()
    tab_widget_action = TabWidgetAction(q)
    menu.addAction(tab_widget_action)

    def query_tab(index):
        try:
            q.put(QueryTask(tab_widget_action.widget.widget(index).serial))
        except AttributeError as _:
            pass

    tab_widget_action.widget.currentChanged.connect(query_tab)

    controller.tab_create.connect(tab_widget_action.add_tab)
    controller.tab_update.connect(tab_widget_action.update_tab)
    controller.tab_destroy.connect(tab_widget_action.destroy_tab)
    controller.start()

    quit = QAction("Quit")
    quit.triggered.connect(app.quit)
    menu.addAction(quit)

    def activation_event(event):
        def update():
            current_index = tab_widget_action.widget.currentIndex()
            if current_index >= 0:
                query_tab(current_index)
            else:
                force_rediscovery(q)

        timer = QTimer()
        menu.close_menu.connect(timer.stop)
        timer.timeout.connect(update)
        timer.start(DEFAULT_REFRESH)
        update()
        menu.exec(QCursor.pos())

    tray.activated.connect(activation_event)
    #tray.setContextMenu(menu)

    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
