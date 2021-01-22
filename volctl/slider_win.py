"""
VolumeSliders window

Small window that appears next to tray icon when activated. It show sliders
for main and application volume.
"""

from gi.repository import Gtk, Gdk, GLib, GObject


class VolumeSliders(Gtk.Window):
    """Window that displays volume sliders."""

    SPACING = 6

    def __init__(self, volctl, monitor_rect):
        super().__init__(type=Gtk.WindowType.POPUP)
        self._volctl = volctl
        self._monitor_rect = monitor_rect
        self._grid = None
        self._show_percentage = self._volctl.settings.get_boolean("show-percentage")

        # GUI objects by index
        self._sink_scales = None
        self._sink_input_scales = None

        self.connect("enter-notify-event", self._cb_enter_notify)
        self.connect("leave-notify-event", self._cb_leave_notify)

        self._frame = Gtk.Frame()
        self._frame.set_shadow_type(Gtk.ShadowType.OUT)
        self.add(self._frame)
        self.create_sliders()

        # Timeout
        self._timeout = None
        self._enable_timeout()

    def set_increments(self):
        """Set sliders increment step."""
        for _, scale in self._sink_scales.items():
            self._set_increments_on_scale(scale)
        for _, scale in self._sink_input_scales.items():
            self._set_increments_on_scale(scale)

    def reset_timeout(self):
        """Reset auto-close timeout."""
        self._remove_timeout()
        self._enable_timeout()

    def _set_increments_on_scale(self, scale):
        scale.set_increments(
            1.0 / self._volctl.mouse_wheel_step,
            1.0 / self._volctl.mouse_wheel_step,
        )

    def _set_position(self):
        status_icon = self._volctl.status_icon
        info_avail, screen, status_rect, orient = status_icon.get_geometry()
        if not info_avail:
            raise ValueError("StatusIcon position information not available!")
        win_w, win_h = self.get_size()

        # Initial position (window anchor based on screen quadrant)
        win_x = status_rect.x
        win_y = status_rect.y
        if status_rect.x - self._monitor_rect.x < self._monitor_rect.width / 2:
            win_x += status_rect.width
        else:
            if orient == Gtk.Orientation.VERTICAL:
                win_x -= win_w
        if status_rect.y - self._monitor_rect.y < self._monitor_rect.height / 2:
            win_y += status_rect.height
        else:
            win_y -= win_h

        # Keep window inside screen
        if win_x + win_w > self._monitor_rect.x + self._monitor_rect.width:
            win_x = self._monitor_rect.x + self._monitor_rect.width - win_w

        self.set_screen(screen)
        self.move(win_x, win_y)

    def create_sliders(self):
        """(Re-)create sliders from PulseAudio sinks."""
        print("create_sliders")
        if self._grid is not None:
            self._grid.destroy()
        if self._sink_scales is not None:
            del self._sink_scales
        if self._sink_input_scales is not None:
            del self._sink_input_scales
        self._sink_scales = {}
        self._sink_input_scales = {}

        self._grid = Gtk.Grid()
        self._grid.set_column_spacing(2)
        self._grid.set_row_spacing(self.SPACING)
        self._frame.add(self._grid)

        pos = 0
        with self._volctl.pulsemgr.update_wakeup() as pulse:
            sinks = pulse.sink_list()
            sink_inputs = pulse.sink_input_list()

        # Sinks
        for sink in sinks:
            scale, btn = self._add_scale(sink.proplist["alsa.card_name"], "audio-card")
            self._sink_scales[sink.index] = scale, btn
            self._update_scale_values((scale, btn), sink.volume.value_flat, sink.mute)
            scale.set_margin_top(self.SPACING)
            btn.set_margin_bottom(self.SPACING)
            self._grid.attach(scale, pos, 0, 1, 1)
            self._grid.attach(btn, pos, 1, 1, 1)
            idx = sink.index
            scale.connect("value-changed", self._cb_sink_scale_change, idx)
            btn.connect("toggled", self._cb_sink_mute_toggle, idx)
            pos += 1

        # Sink inputs
        if sink_inputs:
            separator = Gtk.Separator().new(Gtk.Orientation.VERTICAL)
            separator.set_margin_top(self.SPACING)
            separator.set_margin_bottom(self.SPACING)
            self._grid.attach(separator, pos, 0, 1, 2)
            pos += 1

            for sink_input in sink_inputs:
                try:
                    icon_name = sink_input.proplist["media.icon_name"]
                except KeyError:
                    try:
                        icon_name = sink_input.proplist["application.icon_name"]
                    except KeyError:
                        icon_name = "multimedia-volume-control"
                try:
                    name = (
                        f"{sink_input.proplist['application.name']}: "
                        + sink_input.proplist["media.name"]
                    )
                except KeyError:
                    try:
                        name = sink_input.proplist["application.name"]
                    except KeyError:
                        name = sink_input.name
                scale, btn = self._add_scale(name, icon_name)
                self._sink_input_scales[sink_input.index] = scale, btn
                self._update_scale_values(
                    (scale, btn), sink_input.volume.value_flat, sink_input.mute
                )
                scale.set_margin_top(self.SPACING)
                btn.set_margin_bottom(self.SPACING)
                self._grid.attach(scale, pos, 0, 1, 1)
                self._grid.attach(btn, pos, 1, 1, 1)
                idx = sink_input.index
                scale.connect("value-changed", self._cb_sink_input_scale_change, idx)
                btn.connect("toggled", self._cb_sink_input_mute_toggle, idx)
                pos += 1

        self.show_all()
        self.resize(1, 1)  # Smallest possible
        GObject.idle_add(self._set_position)

    def _add_scale(self, name, icon_name):
        # Scale
        scale = Gtk.Scale().new(Gtk.Orientation.VERTICAL)
        scale.set_range(0.0, 1.0)
        scale.set_inverted(True)
        scale.set_size_request(24, 128)
        scale.set_tooltip_text(name)
        self._set_increments_on_scale(scale)
        if self._show_percentage:
            scale.set_draw_value(True)
            scale.set_value_pos(Gtk.PositionType.BOTTOM)
            scale.connect("format_value", self._cb_format_value)
        else:
            scale.set_draw_value(False)

        if self._volctl.settings.get_boolean("vu-enabled"):
            scale.set_has_origin(False)
            scale.set_show_fill_level(False)
            scale.set_fill_level(0)
            scale.set_restrict_to_fill_level(False)

        # Mute button
        icon = Gtk.Image()
        icon.set_from_icon_name(icon_name, Gtk.IconSize.SMALL_TOOLBAR)
        btn = Gtk.ToggleButton()
        btn.set_image(icon)
        btn.set_relief(Gtk.ReliefStyle.NONE)
        btn.set_tooltip_text(name)

        return scale, btn

    @staticmethod
    def _update_scale_values(scale_btn, volume, mute):
        scale, btn = scale_btn
        scale.set_value(volume)
        if mute is not None:
            scale.set_sensitive(not mute)
            btn.set_active(mute)

    @staticmethod
    def _update_scale_peak(scale, val):
        if val > 0:
            scale.set_show_fill_level(True)
            scale.set_fill_level(val)
        else:
            scale.set_show_fill_level(False)
            scale.set_fill_level(0)

    def _enable_timeout(self):
        if self._volctl.settings.get_boolean("auto-close") and self._timeout is None:
            self._timeout = GLib.timeout_add(
                self._volctl.settings.get_int("timeout"), self._cb_auto_close
            )

    def _remove_timeout(self):
        if self._timeout is not None:
            GLib.Source.remove(self._timeout)
            self._timeout = None

    # Updates coming from outside

    def update_sink_scale(self, idx, volume, mute):
        """Update sink scale by index."""
        try:
            scale_btn = self._sink_scales[idx]
        except KeyError:
            return
        self._update_scale_values(scale_btn, volume, mute)

    def update_sink_input_scale(self, idx, volume, mute):
        """Update sink input scale by index."""
        try:
            scale_btn = self._sink_input_scales[idx]
        except KeyError:
            return
        self._update_scale_values(scale_btn, volume, mute)

    def update_sink_scale_peak(self, idx, val):
        """Update sink scale peak value by index."""
        try:
            scale, _ = self._sink_scales[idx]
        except KeyError:
            return
        self._update_scale_peak(scale, val)

    def update_sink_input_scale_peak(self, idx, val):
        """Update sink input peak value by index."""
        try:
            scale, _ = self._sink_input_scales[idx]
        except KeyError:
            return
        self._update_scale_peak(scale, val)

    # gui callbacks

    @staticmethod
    def _cb_format_value(scale, val):
        """Format scale label"""
        return "{:d}%".format(round(100 * val))

    def _cb_sink_scale_change(self, scale, idx):
        value = scale.get_value()
        with self._volctl.pulsemgr.update_wakeup() as pulse:
            sink = next(s for s in pulse.sink_list() if s.index == idx)
            if sink:
                pulse.volume_set_all_chans(sink, value)

    def _cb_sink_input_scale_change(self, scale, idx):
        value = scale.get_value()
        with self._volctl.pulsemgr.update_wakeup() as pulse:
            sink_input = next(s for s in pulse.sink_input_list() if s.index == idx)
            if sink_input:
                pulse.volume_set_all_chans(sink_input, value)

    def _cb_sink_mute_toggle(self, button, idx):
        mute = button.get_property("active")
        self._volctl.pulsemgr.sink_set_mute(idx, mute)

    def _cb_sink_input_mute_toggle(self, button, idx):
        mute = button.get_property("active")
        self._volctl.pulsemgr.sink_input_set_mute(idx, mute)

    def _cb_enter_notify(self, win, event):
        if (
            event.detail == Gdk.NotifyType.NONLINEAR
            or event.detail == Gdk.NotifyType.NONLINEAR_VIRTUAL
        ):
            self._remove_timeout()

    def _cb_leave_notify(self, win, event):
        if (
            event.detail == Gdk.NotifyType.NONLINEAR
            or event.detail == Gdk.NotifyType.NONLINEAR_VIRTUAL
        ):
            self._enable_timeout()

    def _cb_auto_close(self):
        self._timeout = None
        self._volctl.close_slider()
        return GLib.SOURCE_REMOVE
