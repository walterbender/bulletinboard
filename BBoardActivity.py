# -*- coding: utf-8 -*-
#Copyright (c) 2011, 2012 Walter Bender

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# You should have received a copy of the GNU General Public License
# along with this library; if not, write to the Free Software
# Foundation, 51 Franklin Street, Suite 500 Boston, MA 02110-1335 USA

import gtk
import gobject
import subprocess
import os
import time
from shutil import copyfile

from math import sqrt, ceil

from sugar.activity import activity
from sugar import profile
try:
    from sugar.graphics.toolbarbox import ToolbarBox
    HAVE_TOOLBOX = True
except ImportError:
    HAVE_TOOLBOX = False

if HAVE_TOOLBOX:
    from sugar.activity.widgets import ActivityToolbarButton
    from sugar.activity.widgets import StopButton
    from sugar.graphics.toolbarbox import ToolbarButton

from sugar.datastore import datastore
from sugar.graphics.alert import Alert
from sugar.graphics.icon import Icon
from sugar.graphics.xocolor import XoColor

import telepathy
from dbus.service import signal
from dbus.gobject_service import ExportedGObject
from sugar.presence import presenceservice
from sugar.presence.tubeconn import TubeConnection

SERVICE = 'org.sugarlabs.BBoardActivity'
IFACE = SERVICE
PATH = '/org/sugarlabs/BBoardActivity'

try:
    _OLD_SUGAR_SYSTEM = False
    import json
    from json import load as jload
    from json import dump as jdump
except(ImportError, AttributeError):
    try:
        import simplejson as json
        from simplejson import load as jload
        from simplejson import dump as jdump
    except ImportError:
        _OLD_SUGAR_SYSTEM = True
from StringIO import StringIO

from sprites import Sprites, Sprite
from exportpdf import save_pdf
from utils import get_path, lighter_color, svg_str_to_pixbuf, \
    play_audio_from_file, get_pixbuf_from_journal, genblank, get_hardware, \
    svg_rectangle, pixbuf_to_base64, base64_to_pixbuf, file_to_base64, \
    base64_to_file
from toolbar_utils import radio_factory, \
    button_factory, separator_factory, combo_factory, label_factory
from grecord import Grecord

from gettext import gettext as _

import logging
_logger = logging.getLogger("bboard-activity")

try:
    from sugar.graphics import style
    GRID_CELL_SIZE = style.GRID_CELL_SIZE
except ImportError:
    GRID_CELL_SIZE = 0

# Size and position of title, preview image, and description
PREVIEWW = 600
PREVIEWH = 450
PREVIEWY = 80
TITLEH = 60
DESCRIPTIONH = 250
DESCRIPTIONX = 50
DESCRIPTIONY = 550
MAXX = 160
MAXY = 120

# sprite layers
DRAG = 6
TOP = 4
UNDRAG = 3
MIDDLE = 2
BOTTOM = 1
HIDE = 0


class Slide():
    ''' A container for a slide '''

    def __init__(self, owner, uid, colors, title, pixbuf, desc):
        self.owner = owner
        self.uid = uid
        self.colors = colors
        self.title = title
        self.pixbuf = pixbuf
        self.desc = desc


class BBoardActivity(activity.Activity):
    ''' Make a slideshow from starred Journal entries. '''

    def __init__(self, handle):
        ''' Initialize the toolbars and the work surface '''
        super(BBoardActivity, self).__init__(handle)

        self.datapath = get_path(activity, 'instance')

        self._hw = get_hardware()

        self._playback_buttons = {}
        self._audio_recordings = {}
        self.colors = profile.get_color().to_string().split(',')

        self._setup_toolbars()
        self._setup_canvas()

        self.slides = []
        self._setup_workspace()

        self._buddies = [profile.get_nick_name()]
        self._setup_presence_service()

        self._thumbs = []
        self._thumbnail_mode = False

        self._recording = False
        self._grecord = None
        self._alert = None

        self._dirty = False

    def _setup_canvas(self):
        ''' Create a canvas '''
        self._canvas = gtk.DrawingArea()
        self._canvas.set_size_request(int(gtk.gdk.screen_width()),
                                      int(gtk.gdk.screen_height()))
        self._canvas.show()
        self.set_canvas(self._canvas)
        self.show_all()

        self._canvas.set_flags(gtk.CAN_FOCUS)
        self._canvas.add_events(gtk.gdk.BUTTON_PRESS_MASK)
        self._canvas.add_events(gtk.gdk.POINTER_MOTION_MASK)
        self._canvas.add_events(gtk.gdk.BUTTON_RELEASE_MASK)
        self._canvas.add_events(gtk.gdk.KEY_PRESS_MASK)
        self._canvas.connect("expose-event", self._expose_cb)
        self._canvas.connect("button-press-event", self._button_press_cb)
        self._canvas.connect("button-release-event", self._button_release_cb)
        self._canvas.connect("motion-notify-event", self._mouse_move_cb)

    def _setup_workspace(self):
        ''' Prepare to render the datastore entries. '''

        # Use the lighter color for the text background
        if lighter_color(self.colors) == 0:
            tmp = self.colors[0]
            self.colors[0] = self.colors[1]
            self.colors[1] = tmp

        self._width = gtk.gdk.screen_width()
        self._height = gtk.gdk.screen_height()
        self._scale = gtk.gdk.screen_height() / 900.

        if not HAVE_TOOLBOX and self._hw[0:2] == 'xo':
            titlef = 18
            descriptionf = 12
        else:
            titlef = 36
            descriptionf = 24

        self._find_starred()
        for ds in self.dsobjects:
            if 'title' in ds.metadata:
                title = ds.metadata['title']
            else:
                title = None
            pixbuf = None
            media_object = False
            mimetype = None
            if 'mime_type' in ds.metadata:
                mimetype = ds.metadata['mime_type']
            if mimetype[0:5] == 'image':
                pixbuf = gtk.gdk.pixbuf_new_from_file_at_size(
                    ds.file_path, MAXX, MAXY)
                    # ds.file_path, 300, 225)
                media_object = True
            else:
                pixbuf = get_pixbuf_from_journal(ds, MAXX, MAXY)  # 300, 225)
            if 'description' in ds.metadata:
                desc = ds.metadata['description']
            else:
                desc = None
            self.slides.append(Slide(True, ds.object_id, self.colors,
                                     title, pixbuf, desc))

        # Generate the sprites we'll need...
        self._sprites = Sprites(self._canvas)

        self._help = Sprite(
            self._sprites,
            int((self._width - int(PREVIEWW * self._scale)) / 2),
            int(PREVIEWY * self._scale),
            gtk.gdk.pixbuf_new_from_file_at_size(
                os.path.join(activity.get_bundle_path(), 'help.png'),
                int(PREVIEWW * self._scale), int(PREVIEWH * self._scale)))
        self._help.hide()

        self._genblanks(self.colors)

        self._title = Sprite(self._sprites, 0, 0, self._title_pixbuf)
        self._title.set_label_attributes(int(titlef * self._scale),
                                         rescale=False)
        self._preview = Sprite(self._sprites,
            int((self._width - int(PREVIEWW * self._scale)) / 2),
            int(PREVIEWY * self._scale), self._preview_pixbuf)

        self._description = Sprite(self._sprites,
                                   int(DESCRIPTIONX * self._scale),
                                   int(DESCRIPTIONY * self._scale),
                                   self._desc_pixbuf)
        self._description.set_label_attributes(int(descriptionf * self._scale))

        self._my_canvas = Sprite(self._sprites, 0, 0, self._canvas_pixbuf)
        self._my_canvas.set_layer(BOTTOM)

        self._clear_screen()

        self.i = 0
        self._show_slide()

        self._playing = False
        self._rate = 10

    def _genblanks(self, colors):
        ''' Need to cache these '''
        self._title_pixbuf = svg_str_to_pixbuf(
            genblank(self._width, int(TITLEH * self._scale), colors))
        self._preview_pixbuf = svg_str_to_pixbuf(
            genblank(int(PREVIEWW * self._scale), int(PREVIEWH * self._scale),
                     colors))
        self._desc_pixbuf = svg_str_to_pixbuf(
            genblank(int(self._width - (2 * DESCRIPTIONX * self._scale)),
                     int(DESCRIPTIONH * self._scale), colors))
        self._canvas_pixbuf = svg_str_to_pixbuf(
            genblank(self._width, self._height, (colors[0], colors[0])))

    def _setup_toolbars(self):
        ''' Setup the toolbars. '''

        self.max_participants = 6

        if HAVE_TOOLBOX:
            toolbox = ToolbarBox()

            # Activity toolbar
            activity_button_toolbar = ActivityToolbarButton(self)

            toolbox.toolbar.insert(activity_button_toolbar, 0)
            activity_button_toolbar.show()

            self.set_toolbar_box(toolbox)
            toolbox.show()
            self.toolbar = toolbox.toolbar

            self.record_toolbar = gtk.Toolbar()
            record_toolbar_button = ToolbarButton(
                label=_('Record a sound'),
                page=self.record_toolbar,
                icon_name='media-audio')
            self.record_toolbar.show_all()
            record_toolbar_button.show()
        else:
            # Use pre-0.86 toolbar design
            primary_toolbar = gtk.Toolbar()
            toolbox = activity.ActivityToolbox(self)
            self.set_toolbox(toolbox)
            toolbox.add_toolbar(_('Page'), primary_toolbar)
            self.record_toolbar = gtk.Toolbar()
            toolbox.add_toolbar(_('Record'), self.record_toolbar)
            toolbox.show()
            toolbox.set_current_toolbar(1)
            self.toolbar = primary_toolbar

        self._prev_button = button_factory(
            'go-previous-inactive', self.toolbar, self._prev_cb,
            tooltip=_('Prev slide'), accelerator='<Ctrl>P')

        self._next_button = button_factory(
            'go-next', self.toolbar, self._next_cb,
            tooltip=_('Next slide'), accelerator='<Ctrl>N')

        if HAVE_TOOLBOX:
            toolbox.toolbar.insert(record_toolbar_button, -1)

        slide_button = radio_factory('slide-view', self.toolbar,
                                     self._slides_cb, group=None,
                                     tooltip=_('Slide view'))

        radio_factory('thumbs-view', self.toolbar, self._thumbs_cb,
                      tooltip=_('Thumbnail view'),
                      group=slide_button)

        button_factory('view-fullscreen', self.toolbar,
                       self.do_fullscreen_cb, tooltip=_('Fullscreen'),
                       accelerator='<Alt>Return')

        separator_factory(self.toolbar)

        journal_button = button_factory(
            'write-journal', self.toolbar, self._do_journal_cb,
            tooltip=_('Update description'))
        self._palette = journal_button.get_palette()
        msg_box = gtk.HBox()

        sw = gtk.ScrolledWindow()
        sw.set_size_request(int(gtk.gdk.screen_width() / 2),
                            2 * style.GRID_CELL_SIZE)
        sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        self._text_view = gtk.TextView()
        self._text_view.set_left_margin(style.DEFAULT_PADDING)
        self._text_view.set_right_margin(style.DEFAULT_PADDING)
        self._text_view.set_wrap_mode(gtk.WRAP_WORD_CHAR)
        self._text_view.connect('focus-out-event',
                               self._text_view_focus_out_event_cb)
        sw.add(self._text_view)
        sw.show()
        msg_box.pack_start(sw, expand=False)
        msg_box.show_all()

        self._palette.set_content(msg_box)

        separator_factory(self.toolbar)

        button_factory('system-restart', self.toolbar, self._resend_cb,
                       tooltip=_('Refresh'))

        label_factory(self.record_toolbar, _('Record a sound') + ':')
        self._record_button = button_factory(
            'media-record', self.record_toolbar,
            self._record_cb, tooltip=_('Start recording'))

        separator_factory(self.record_toolbar)

        # Look to see if we have audio previously recorded
        obj_id = self._get_audio_obj_id()
        dsobject = self._search_for_audio_note(obj_id)
        if dsobject is not None:
            _logger.debug('Found previously recorded audio')
            self._add_playback_button(profile.get_nick_name(),
                                      self.colors,
                                      dsobject.file_path)

        if HAVE_TOOLBOX:
            separator_factory(activity_button_toolbar)
            self._save_pdf = button_factory(
                'save-as-pdf', activity_button_toolbar,
                self._save_as_pdf_cb, tooltip=_('Save as PDF'))
        else:
            separator_factory(self.toolbar)
            self._save_pdf = button_factory(
                'save-as-pdf', self.toolbar,
                self._save_as_pdf_cb, tooltip=_('Save as PDF'))

        if HAVE_TOOLBOX:
            separator_factory(toolbox.toolbar, True, False)

            stop_button = StopButton(self)
            stop_button.props.accelerator = '<Ctrl>q'
            toolbox.toolbar.insert(stop_button, -1)
            stop_button.show()

    def _do_journal_cb(self, button):
        self._dirty = True
        if self._palette:
            if not self._palette.is_up():
                self._palette.popup(immediate=True,
                                    state=self._palette.SECONDARY)
            else:
                self._palette.popdown(immediate=True)
            return

    def _text_view_focus_out_event_cb(self, widget, event):
        buffer = self._text_view.get_buffer()
        start_iter = buffer.get_start_iter()
        end_iter = buffer.get_end_iter()
        self.slides[self.i].desc = buffer.get_text(start_iter, end_iter)
        self._show_slide()

    def _destroy_cb(self, win, event):
        ''' Clean up on the way out. '''
        gtk.main_quit()

    def _find_starred(self):
        ''' Find all the favorites in the Journal. '''
        self.dsobjects, nobjects = datastore.find({'keep': '1'})
        _logger.debug('found %d starred items', nobjects)

    def _prev_cb(self, button=None):
        ''' The previous button has been clicked; goto previous slide. '''
        if self.i > 0:
            self.i -= 1
            self._show_slide(direction=-1)

    def _next_cb(self, button=None):
        ''' The next button has been clicked; goto next slide. '''
        if self.i < len(self.slides) - 1:
            self.i += 1
            self._show_slide()

    def _save_as_pdf_cb(self, button=None):
        ''' Export an PDF version of the slideshow to the Journal. '''
        _logger.debug('saving to PDF...')
        if 'description' in self.metadata:
            tmp_file = save_pdf(self, self._buddies,
                                description=self.metadata['description'])
        else:
            tmp_file = save_pdf(self, self._buddies)
        _logger.debug('copying PDF file to Journal...')
        dsobject = datastore.create()
        dsobject.metadata['title'] = profile.get_nick_name() + ' ' + \
                                     _('Bboard')
        dsobject.metadata['icon-color'] = profile.get_color().to_string()
        dsobject.metadata['mime_type'] = 'application/pdf'
        dsobject.set_file_path(tmp_file)
        dsobject.metadata['activity'] = 'org.laptop.sugar.ReadActivity'
        datastore.write(dsobject)
        dsobject.destroy()
        return

    def _clear_screen(self):
        ''' Clear the screen to the darker of the two user colors. '''
        self._title.hide()
        self._preview.hide()
        self._description.hide()
        if hasattr(self, '_thumbs'):
            for thumbnail in self._thumbs:
                thumbnail[0].hide()
        self.invalt(0, 0, self._width, self._height)

        # Reset drag settings
        self._press = None
        self._release = None
        self._dragpos = [0, 0]
        self._total_drag = [0, 0]
        self.last_spr_moved = None

    def _update_colors(self):
        ''' Match the colors to those of the slide originator. '''
        self._genblanks(self.slides[self.i].colors)
        self._title.set_image(self._title_pixbuf)
        self._preview.set_image(self._preview_pixbuf)
        self._description.set_image(self._desc_pixbuf)
        self._my_canvas.set_image(self._canvas_pixbuf)

    def _show_slide(self, direction=1):
        ''' Display a title, preview image, and decription for slide. '''
        self._clear_screen()
        self._update_colors()

        if len(self.slides) == 0:
            self._prev_button.set_icon('go-previous-inactive')
            self._next_button.set_icon('go-next-inactive')
            self._description.set_label(
                _('Do you have any items in your Journal starred?'))
            self._help.set_layer(TOP)
            self._description.set_layer(MIDDLE)
            return

        if self.i == 0:
            self._prev_button.set_icon('go-previous-inactive')
        else:
            self._prev_button.set_icon('go-previous')
        if self.i == len(self.slides) - 1:
            self._next_button.set_icon('go-next-inactive')
        else:
            self._next_button.set_icon('go-next')

        pixbuf = self.slides[self.i].pixbuf
        if pixbuf is not None:
            self._preview.set_shape(pixbuf.scale_simple(
                    int(PREVIEWW * self._scale),
                    int(PREVIEWH * self._scale),
                    gtk.gdk.INTERP_NEAREST))
            self._preview.set_layer(MIDDLE)
        else:
            if self._preview is not None:
                self._preview.hide()

        self._title.set_label(self.slides[self.i].title)
        self._title.set_layer(MIDDLE)

        if self.slides[self.i].desc is not None:
            self._description.set_label(self.slides[self.i].desc)
            self._description.set_layer(MIDDLE)
            text_buffer = gtk.TextBuffer()
            text_buffer.set_text(self.slides[self.i].desc)
            self._text_view.set_buffer(text_buffer)
        else:
            self._description.set_label('')
            self._description.hide()

    def _add_playback_button(self, nick, colors, audio_file):
        ''' Add a toolbar button for this audio recording '''
        if nick not in self._playback_buttons:
            self._playback_buttons[nick] = button_factory(
                'xo-chat',  self.record_toolbar,
                self._playback_recording_cb, cb_arg=nick,
                tooltip=_('Audio recording by %s') % (nick))
            xocolor = XoColor('%s,%s' % (colors[0], colors[1]))
            icon = Icon(icon_name='xo-chat', xo_color=xocolor)
            icon.show()
            self._playback_buttons[nick].set_icon_widget(icon)
            self._playback_buttons[nick].show()
        self._audio_recordings[nick] = audio_file

    def _slides_cb(self, button=None):
        if self._thumbnail_mode:
            self._thumbnail_mode = False
            self.i = self._current_slide
            self._show_slide()

    def _thumbs_cb(self, button=None):
        ''' Toggle between thumbnail view and slideshow view. '''
        if not self._thumbnail_mode:
            self._current_slide = self.i
            self._thumbnail_mode = True
            self._clear_screen()

            self._prev_button.set_icon('go-previous-inactive')
            self._next_button.set_icon('go-next-inactive')

            n = int(ceil(sqrt(len(self.slides))))
            if n > 0:
                w = int(self._width / n)
            else:
                w = self._width
            h = int(w * 0.75)  # maintain 4:3 aspect ratio
            x_off = int((self._width - n * w) / 2)
            x = x_off
            y = 0
            self._thumbs = []
            for i in range(len(self.slides)):
                self._show_thumb(i, x, y, w, h)
                x += w
                if x + w > self._width:
                    x = x_off
                    y += h
            self.i = 0  # Reset position in slideshow to the beginning
        return False

    def _show_thumb(self, i, x, y, w, h):
        ''' Display a preview image and title as a thumbnail. '''
        pixbuf = self.slides[i].pixbuf
        if pixbuf is not None:
            pixbuf_thumb = pixbuf.scale_simple(
                int(w), int(h), gtk.gdk.INTERP_TILES)
        else:
            pixbuf_thumb = svg_str_to_pixbuf(
                genblank(int(w), int(h), self.slides[i].colors))
        # Create a Sprite for this thumbnail
        self._thumbs.append([Sprite(self._sprites, x, y, pixbuf_thumb),
                             x, y, i])
        self._thumbs[i][0].set_image(
            svg_str_to_pixbuf(svg_rectangle(int(w), int(h),
                                            self.slides[i].colors)), i=1)
        self._thumbs[i][0].set_layer(TOP)

    def _expose_cb(self, win, event):
        ''' Callback to handle window expose events '''
        self.do_expose_event(event)
        return True

    # Handle the expose-event by drawing
    def do_expose_event(self, event):

        # Create the cairo context
        cr = self.canvas.window.cairo_create()

        # Restrict Cairo to the exposed area; avoid extra work
        cr.rectangle(event.area.x, event.area.y,
                event.area.width, event.area.height)
        cr.clip()

        # Refresh sprite list
        self._sprites.redraw_sprites(cr=cr)

    def write_file(self, file_path):
        ''' Clean up '''
        if self._dirty:
            self._save_descriptions_cb()
            self._dirty = False
        if os.path.exists(os.path.join(self.datapath, 'output.ogg')):
            os.remove(os.path.join(self.datapath, 'output.ogg'))

    def do_fullscreen_cb(self, button):
        ''' Hide the Sugar toolbars. '''
        self.fullscreen()

    def invalt(self, x, y, w, h):
        ''' Mark a region for refresh '''
        self._canvas.window.invalidate_rect(
            gtk.gdk.Rectangle(int(x), int(y), int(w), int(h)), False)

    def _spr_to_thumb(self, spr):
        ''' Find which entry in the thumbnails table matches spr. '''
        for i, thumb in enumerate(self._thumbs):
            if spr == thumb[0]:
                return i
        return -1

    def _spr_is_thumbnail(self, spr):
        ''' Does spr match an entry in the thumbnails table? '''
        if self._spr_to_thumb(spr) == -1:
            return False
        else:
            return True

    def _button_press_cb(self, win, event):
        ''' The mouse button was pressed. Is it on a thumbnail sprite? '''
        win.grab_focus()
        x, y = map(int, event.get_coords())

        self._dragpos = [x, y]
        self._total_drag = [0, 0]

        spr = self._sprites.find_sprite((x, y))
        self._press = None
        self._release = None

        # Are we clicking on a thumbnail?
        if not self._spr_is_thumbnail(spr):
            return False

        self.last_spr_moved = spr
        self._press = spr
        self._press.set_layer(DRAG)
        return False

    def _mouse_move_cb(self, win, event):
        """ Drag a thumbnail with the mouse. """
        spr = self._press
        if spr is None:
            self._dragpos = [0, 0]
            return False
        win.grab_focus()
        x, y = map(int, event.get_coords())
        dx = x - self._dragpos[0]
        dy = y - self._dragpos[1]
        spr.move_relative([dx, dy])
        # Also move the star
        self._dragpos = [x, y]
        self._total_drag[0] += dx
        self._total_drag[1] += dy
        return False

    def _button_release_cb(self, win, event):
        ''' Button event is used to swap slides or goto next slide. '''
        win.grab_focus()
        self._dragpos = [0, 0]
        x, y = map(int, event.get_coords())

        if self._thumbnail_mode:
            if self._press is None:
                return
            # Drop the dragged thumbnail below the other thumbnails so
            # that you can find the thumbnail beneath it.
            self._press.set_layer(UNDRAG)
            i = self._spr_to_thumb(self._press)
            spr = self._sprites.find_sprite((x, y))
            if self._spr_is_thumbnail(spr):
                self._release = spr
                # If we found a thumbnail and it is not the one we
                # dragged, swap their positions.
                if not self._press == self._release:
                    j = self._spr_to_thumb(self._release)
                    self._thumbs[i][0] = self._release
                    self._thumbs[j][0] = self._press
                    tmp = self.slides[i]
                    self.slides[i] = self.slides[j]
                    self.slides[j] = tmp
                    self._thumbs[j][0].move((self._thumbs[j][1],
                                             self._thumbs[j][2]))
            self._thumbs[i][0].move((self._thumbs[i][1], self._thumbs[i][2]))
            self._press.set_layer(TOP)
            self._press = None
            self._release = None
        else:
            self._next_cb()
        return False

    def _unit_combo_cb(self, arg=None):
        ''' Read value of predefined conversion factors from combo box '''
        if hasattr(self, '_unit_combo'):
            active = self._unit_combo.get_active()
            if active in UNIT_DICTIONARY:
                self._rate = UNIT_DICTIONARY[active][1]

    def _record_cb(self, button=None):
        ''' Start/stop audio recording '''
        if self._grecord is None:
            _logger.debug('setting up grecord')
            self._grecord = Grecord(self)
        if self._recording:  # Was recording, so stop (and save?)
            _logger.debug('recording...True. Preparing to save.')
            self._grecord.stop_recording_audio()
            self._recording = False
            self._record_button.set_icon('media-record')
            self._record_button.set_tooltip(_('Start recording'))
            _logger.debug('Autosaving recording')
            self._notify(title=_('Save recording'))
            gobject.timeout_add(100, self._wait_for_transcoding_to_finish)
        else:  # Wasn't recording, so start
            _logger.debug('recording...False. Start recording.')
            self._grecord.record_audio()
            self._recording = True
            self._record_button.set_icon('media-recording')
            self._record_button.set_tooltip(_('Stop recording'))

    def _wait_for_transcoding_to_finish(self, button=None):
        while not self._grecord.transcoding_complete():
            time.sleep(1)
        if self._alert is not None:
            self.remove_alert(self._alert)
            self._alert = None
        self._save_recording()

    def _playback_recording_cb(self, button=None, nick=profile.get_nick_name()):
        ''' Play back current recording '''
        _logger.debug('Playback current recording from %s...' % (nick))
        if nick in self._audio_recordings:
            play_audio_from_file(self._audio_recordings[nick])
        return

    def _get_audio_obj_id(self):
        ''' Find unique name for audio object '''
        if 'activity_id' in self.metadata:
            obj_id = self.metadata['activity_id']
        else:
            obj_id = _('Bulletin Board')
        _logger.debug(obj_id)
        return obj_id

    def _save_recording(self):
        if os.path.exists(os.path.join(self.datapath, 'output.ogg')):
            _logger.debug('Saving recording to Journal...')
            obj_id = self._get_audio_obj_id()
            copyfile(os.path.join(self.datapath, 'output.ogg'),
                     os.path.join(self.datapath, '%s.ogg' % (obj_id)))
            dsobject = self._search_for_audio_note(obj_id)
            if dsobject is None:
                dsobject = datastore.create()
            if dsobject is not None:
                _logger.debug(self.dsobjects[self.i].metadata['title'])
                dsobject.metadata['title'] = _('Audio recording by %s') % \
                    (self.metadata['title'])
                dsobject.metadata['icon-color'] = \
                    profile.get_color().to_string()
                dsobject.metadata['tags'] = obj_id
                dsobject.metadata['mime_type'] = 'audio/ogg'
                dsobject.set_file_path(
                    os.path.join(self.datapath, '%s.ogg' % (obj_id)))
                datastore.write(dsobject)
                dsobject.destroy()
            self._add_playback_button(
                profile.get_nick_name(), self.colors,
                os.path.join(self.datapath, '%s.ogg' % (obj_id)))
            if hasattr(self, 'chattube') and self.chattube is not None:
                self._share_audio()
        else:
            _logger.debug('Nothing to save...')
        return

    def _search_for_audio_note(self, obj_id):
        ''' Look to see if there is already a sound recorded for this
        dsobject '''
        dsobjects, nobjects = datastore.find({'mime_type': ['audio/ogg']})
        # Look for tag that matches the target object id
        for dsobject in dsobjects:
            if 'tags' in dsobject.metadata and \
               obj_id in dsobject.metadata['tags']:
                _logger.debug('Found audio note')
                return dsobject
        return None

    def _save_descriptions_cb(self, button=None):
        ''' Find the object in the datastore and write out the changes
        to the decriptions. '''
        for s in self.slides:
            if not s.owner:
                continue
            jobject = datastore.get(s.uid)
            jobject.metadata['description'] = s.desc
            datastore.write(jobject, update_mtime=False,
                            reply_handler=self.datastore_write_cb,
                            error_handler=self.datastore_write_error_cb)

    def datastore_write_cb(self):
        pass

    def datastore_write_error_cb(self, error):
        _logger.error('datastore_write_error_cb: %r' % error)

    def _notify(self, title='', msg=''):
        ''' Notify user when saves are completed '''
        self._alert = Alert()
        self._alert.props.title = title
        self._alert.props.msg = msg
        self.add_alert(self._alert)
        self._alert.show()

    def _resend_cb(self, button=None):
        ''' Resend slides, but only of sharing '''
        if hasattr(self, 'chattube') and self.chattube is not None:
            self._share_slides()
            self._share_audio()

    # Serialize

    def _dump(self, slide):
        ''' Dump data for sharing.'''
        _logger.debug('dumping %s' % (slide.uid))
        data = [slide.uid, slide.colors, slide.title,
                pixbuf_to_base64(activity, slide.pixbuf), slide.desc]
        return self._data_dumper(data)

    def _data_dumper(self, data):
        if _OLD_SUGAR_SYSTEM:
            return json.write(data)
        else:
            io = StringIO()
            jdump(data, io)
            return io.getvalue()

    def _load(self, data):
        ''' Load game data from the journal. '''
        slide = self._data_loader(data)
        if len(slide) == 5:
            if not self._slide_search(slide[0]):
                _logger.debug('loading %s' % (slide[0]))
                self.slides.append(Slide(
                        False, slide[0], slide[1], slide[2],
                        base64_to_pixbuf(activity, slide[3]), slide[4]))

    def _slide_search(self, uid):
        ''' Is this slide in the list already? '''
        for slide in self.slides:
            if slide.uid == uid:
                _logger.debug('skipping %s' % (slide.uid))
                return True
        return False

    def _data_loader(self, data):
        if _OLD_SUGAR_SYSTEM:
            return json.read(data)
        else:
            io = StringIO(data)
            return jload(io)

    # Sharing-related methods

    def _setup_presence_service(self):
        ''' Setup the Presence Service. '''
        self.pservice = presenceservice.get_instance()
        self.initiating = None  # sharing (True) or joining (False)

        owner = self.pservice.get_owner()
        self.owner = owner
        self.buddies = [owner]
        self._share = ''
        self.connect('shared', self._shared_cb)
        self.connect('joined', self._joined_cb)

    def _shared_cb(self, activity):
        ''' Either set up initial share...'''
        if self._shared_activity is None:
            _logger.error('Failed to share or join activity ... \
                _shared_activity is null in _shared_cb()')
            return

        self.initiating = True
        self.waiting = False
        _logger.debug('I am sharing...')

        self.conn = self._shared_activity.telepathy_conn
        self.tubes_chan = self._shared_activity.telepathy_tubes_chan
        self.text_chan = self._shared_activity.telepathy_text_chan

        self.tubes_chan[telepathy.CHANNEL_TYPE_TUBES].connect_to_signal(
            'NewTube', self._new_tube_cb)

        _logger.debug('This is my activity: making a tube...')
        id = self.tubes_chan[telepathy.CHANNEL_TYPE_TUBES].OfferDBusTube(
            SERVICE, {})

    def _joined_cb(self, activity):
        ''' ...or join an exisiting share. '''
        if self._shared_activity is None:
            _logger.error('Failed to share or join activity ... \
                _shared_activity is null in _shared_cb()')
            return

        self.initiating = False
        _logger.debug('I joined a shared activity.')

        self.conn = self._shared_activity.telepathy_conn
        self.tubes_chan = self._shared_activity.telepathy_tubes_chan
        self.text_chan = self._shared_activity.telepathy_text_chan

        self.tubes_chan[telepathy.CHANNEL_TYPE_TUBES].connect_to_signal(\
            'NewTube', self._new_tube_cb)

        _logger.debug('I am joining an activity: waiting for a tube...')
        self.tubes_chan[telepathy.CHANNEL_TYPE_TUBES].ListTubes(
            reply_handler=self._list_tubes_reply_cb,
            error_handler=self._list_tubes_error_cb)

        self.waiting = True

    def _list_tubes_reply_cb(self, tubes):
        ''' Reply to a list request. '''
        for tube_info in tubes:
            self._new_tube_cb(*tube_info)

    def _list_tubes_error_cb(self, e):
        ''' Log errors. '''
        _logger.error('ListTubes() failed: %s', e)

    def _new_tube_cb(self, id, initiator, type, service, params, state):
        ''' Create a new tube. '''
        _logger.debug('New tube: ID=%d initator=%d type=%d service=%s '
                     'params=%r state=%d', id, initiator, type, service,
                     params, state)

        if (type == telepathy.TUBE_TYPE_DBUS and service == SERVICE):
            if state == telepathy.TUBE_STATE_LOCAL_PENDING:
                self.tubes_chan[ \
                              telepathy.CHANNEL_TYPE_TUBES].AcceptDBusTube(id)

            tube_conn = TubeConnection(self.conn,
                self.tubes_chan[telepathy.CHANNEL_TYPE_TUBES], id, \
                group_iface=self.text_chan[telepathy.CHANNEL_INTERFACE_GROUP])

            self.chattube = ChatTube(tube_conn, self.initiating, \
                self.event_received_cb)

            if self.waiting:
                self._send_event('j:%s' % (profile.get_nick_name()))

    def event_received_cb(self, text):
        ''' Data is passed as tuples: cmd:text '''
        _logger.debug('<<< %s' % (text[0]))
        if text[0] == 's':  # shared journal objects
            e, data = text.split(':')
            self._load(data)
        elif text[0] == 'j':  # Someone new has joined
            e, buddy = text.split(':')
            _logger.debug('%s has joined' % (buddy))
            if buddy not in self._buddies:
                self._buddies.append(buddy)
            if self.initiating:
                self._send_event('J:%s' % (profile.get_nick_name()))
                self._share_slides()
                self._share_audio()
        elif text[0] == 'J':  # Everyone must share
            e, buddy = text.split(':')
            self.waiting = False
            if buddy not in self._buddies:
                self._buddies.append(buddy)
                _logger.debug('%s has joined' % (buddy))
            self._share_slides()
            self._share_audio()
        elif text[0] == 'a':  # audio recording
            e, data = text.split(':')
            nick, colors, base64 = self._data_loader(data)
            path = os.path.join(activity.get_activity_root(),
                                'instance', 'nick.ogg')
            base64_to_file(activity, base64, path)
            self._add_playback_button(nick, colors, path)

    def _share_audio(self):
        if profile.get_nick_name() in self._audio_recordings:
            base64 = file_to_base64(
                    activity, self._audio_recordings[profile.get_nick_name()])
            gobject.idle_add(self._send_event, 'a:' + str(
                    self._data_dumper([profile.get_nick_name(),
                                       self.colors,
                                       base64])))

    def _share_slides(self):
        for s in self.slides:
            if s.owner:  # Maybe stagger the timing of the sends?
                gobject.idle_add(self._send_event, 's:' + str(self._dump(s)))
        _logger.debug('finished sharing')

    def _send_event(self, text):
        ''' Send event through the tube. '''
        if hasattr(self, 'chattube') and self.chattube is not None:
            _logger.debug('>>> %s' % (text[0]))
            self.chattube.SendText(text)


class ChatTube(ExportedGObject):
    ''' Class for setting up tube for sharing '''
    def __init__(self, tube, is_initiator, stack_received_cb):
        super(ChatTube, self).__init__(tube, PATH)
        self.tube = tube
        self.is_initiator = is_initiator  # Are we sharing or joining activity?
        self.stack_received_cb = stack_received_cb
        self.stack = ''

        self.tube.add_signal_receiver(self.send_stack_cb, 'SendText', IFACE,
                                      path=PATH, sender_keyword='sender')

    def send_stack_cb(self, text, sender=None):
        if sender == self.tube.get_unique_name():
            return
        self.stack = text
        self.stack_received_cb(text)

    @signal(dbus_interface=IFACE, signature='s')
    def SendText(self, text):
        self.stack = text
