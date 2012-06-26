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

import telepathy
from dbus.service import signal
from dbus.gobject_service import ExportedGObject
from sugar.presence import presenceservice
from sugar.presence.tubeconn import TubeConnection

SERVICE = 'org.sugarlabs.BBoardActivity'
IFACE = SERVICE

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
    svg_rectangle
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

XO1 = 'xo1'
XO15 = 'xo1.5'
XO175 = 'xo1.75'
UNKNOWN = 'unknown'

# sprite layers
DRAG = 6
STAR = 5
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

        self._setup_toolbars()
        self._setup_canvas()

        self.slides = []
        self._setup_workspace()

        self.buddies = []
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
        self.colors = profile.get_color().to_string().split(',')

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
                    ds.file_path, int(PREVIEWW * self._scale),
                    int(PREVIEWH * self._scale))
                media_object = True
            else:
                pixbuf = get_pixbuf_from_journal(ds, 300, 225)
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

        self._title = Sprite(self._sprites, 0, 0, svg_str_to_pixbuf(
                genblank(self._width, int(TITLEH * self._scale),
                          self.colors)))
        self._title.set_label_attributes(int(titlef * self._scale),
                                         rescale=False)
        self._preview = Sprite(self._sprites,
            int((self._width - int(PREVIEWW * self._scale)) / 2),
            int(PREVIEWY * self._scale), svg_str_to_pixbuf(genblank(
                    int(PREVIEWW * self._scale), int(PREVIEWH * self._scale),
                    self.colors)))

        self._description = Sprite(self._sprites,
                                   int(DESCRIPTIONX * self._scale),
                                   int(DESCRIPTIONY * self._scale),
                                   svg_str_to_pixbuf(
                genblank(int(self._width - (2 * DESCRIPTIONX * self._scale)),
                          int(DESCRIPTIONH * self._scale),
                          self.colors)))
        self._description.set_label_attributes(int(descriptionf * self._scale))

        self._my_canvas = Sprite(
            self._sprites, 0, 0, svg_str_to_pixbuf(genblank(
                    self._width, self._height, (self.colors[0],
                                                self.colors[0]))))
        self._my_canvas.set_layer(BOTTOM)

        self._clear_screen()

        self.i = 0
        self._show_slide()

        self._playing = False
        self._rate = 10

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

            record_toolbar = gtk.Toolbar()
            record_toolbar_button = ToolbarButton(
                label=_('Record a sound'),
                page=record_toolbar,
                icon_name='media-audio')
            record_toolbar.show_all()
            record_toolbar_button.show()
        else:
            # Use pre-0.86 toolbar design
            primary_toolbar = gtk.Toolbar()
            toolbox = activity.ActivityToolbox(self)
            self.set_toolbox(toolbox)
            toolbox.add_toolbar(_('Page'), primary_toolbar)
            record_toolbar = gtk.Toolbar()
            toolbox.add_toolbar(_('Record'), record_toolbar)
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

        label_factory(record_toolbar, _('Record a sound') + ':')
        self._record_button = button_factory(
            'media-record', record_toolbar,
            self._record_cb, tooltip=_('Start recording'))

        separator_factory(record_toolbar)

        self._playback_button = button_factory(
            'media-playback-start-insensitive',  record_toolbar,
            self._playback_recording_cb, tooltip=_('Nothing to play'))

        self._save_recording_button = button_factory(
            'sound-save-insensitive', record_toolbar,
            self._wait_for_transcoding_to_finish, tooltip=_('Nothing to save'))

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
        tmp_file = save_pdf(self, profile.get_nick_name())

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
        ''' Clear the screen to the darker of the two XO colors. '''
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

    def _show_slide(self, direction=1):
        ''' Display a title, preview image, and decription for slide
        i. Play an audio note if there is one recorded for this
        object. '''
        self._clear_screen()

        if len(self.slides) == 0:
            self._prev_button.set_icon('go-previous-inactive')
            self._next_button.set_icon('go-next-inactive')
            self._description.set_label(
                _('Do you have any items in your Journal starred?'))
            self._help.set_layer(TOP)
            self._description.set_layer(MIDDLE)
            return

        self.i += direction
        if self.i < 0:
            self.i = len(self.slides) - 1
        elif self.i > len(self.slides) - 1:
            self.i = 0

        if self.i == 0:
            self._prev_button.set_icon('go-previous-inactive')
        else:
            self._prev_button.set_icon('go-previous')
        if self.i == len(self.slides) - 1:
            self._next_button.set_icon('go-next-inactive')
        else:
            self._next_button.set_icon('go-next')

        # _logger.debug('Showing slide %d', self.i)
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

        if 'description' in self.dsobjects[self.i].metadata:
            self._description.set_label(self.slides[self.i].desc)
            self._description.set_layer(MIDDLE)
            text_buffer = gtk.TextBuffer()
            text_buffer.set_text(self.slides[self.i].desc)
            self._text_view.set_buffer(text_buffer)
        else:
            self._description.set_label('')
            self._description.hide()

        audio_obj = self._search_for_audio_note(self.slides[self.i].uid)
        if audio_obj is not None:
            _logger.debug('Playing audio note')
            gobject.idle_add(play_audio_from_file, audio_obj.file_path)
            self._playback_button.set_icon('media-playback-start')
            self._playback_button.set_tooltip(_('Play recording'))
        else:
            self._playback_button.set_icon('media-playback-start-insensitive')
            self._playback_button.set_tooltip(_('Nothing to play'))

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
            for i in range(len(self.slides)):
                self.i = i
                self._show_thumb(x, y, w, h)
                x += w
                if x + w > self._width:
                    x = x_off
                    y += h
            self.i = 0  # Reset position in slideshow to the beginning
        return False

    def _show_thumb(self, x, y, w, h):
        ''' Display a preview image and title as a thumbnail. '''

        if len(self._thumbs) < self.i + 1:
            # Create a Sprite for this thumbnail
            pixbuf = self.slides[self.i].pixbuf
            if pixbuf is not None:
                pixbuf_thumb = pixbuf.scale_simple(int(w), int(h),
                                                   gtk.gdk.INTERP_TILES)
            else:
                pixbuf_thumb = svg_str_to_pixbuf(genblank(int(w), int(h),
                                                          self.colors))
            self._thumbs.append([Sprite(self._sprites, x, y, pixbuf_thumb),
                                     x, y, self.i])
            self._thumbs[-1][0].set_image(svg_str_to_pixbuf(
                    svg_rectangle(int(w), int(h), self.colors)), i=1)
            self._thumbs[-1][0].set_label(str(self.i + 1))
        self._thumbs[self.i][0].set_layer(TOP)

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
                    tmp = self.dsobjects[i]
                    self.dsobjects[i] = self.dsobjects[j]
                    self.dsobjects[j] = tmp
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
            self._playback_button.set_icon('media-playback-start')
            self._playback_button.set_tooltip(_('Play recording'))
            self._save_recording_button.set_icon('sound-save')
            self._save_recording_button.set_tooltip(_('Save recording'))
            # Autosave if there was not already a recording
            if self._search_for_audio_note(
                self.dsobjects[self.i].object_id) is None:
                _logger.debug('Autosaving recording')
                self._notify_successful_save(title=_('Save recording'))
                gobject.timeout_add(100, self._wait_for_transcoding_to_finish)
            else:
                _logger.debug('Waiting for manual save.')
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

    def _playback_recording_cb(self, button=None):
        ''' Play back current recording '''
        _logger.debug('Playback current recording from output.ogg...')
        play_audio_from_file(os.path.join(self.datapath, 'output.ogg'))
        return

    def _save_recording(self):
        if os.path.exists(os.path.join(self.datapath, 'output.ogg')):
            _logger.debug('Saving recording to Journal...')
            obj_id = self.dsobjects[self.i].object_id
            copyfile(os.path.join(self.datapath, 'output.ogg'),
                     os.path.join(self.datapath, '%s.ogg' % (obj_id)))
            dsobject = self._search_for_audio_note(obj_id)
            if dsobject is None:
                dsobject = datastore.create()
            if dsobject is not None:
                _logger.debug(self.dsobjects[self.i].metadata['title'])
                dsobject.metadata['title'] = _('audio note for %s') % \
                    (self.dsobjects[self.i].metadata['title'])
                dsobject.metadata['icon-color'] = \
                    profile.get_color().to_string()
                dsobject.metadata['tags'] = obj_id
                dsobject.metadata['mime_type'] = 'audio/ogg'
                dsobject.set_file_path(
                    os.path.join(self.datapath, '%s.ogg' % (obj_id)))
                    # os.path.join(self.datapath, 'output.ogg'))
                datastore.write(dsobject)
                dsobject.destroy()
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

    def _notify_successful_save(self, title='', msg=''):
        ''' Notify user when saves are completed '''
        self._alert = Alert()
        self._alert.props.title = title
        self._alert.props.msg = msg
        self.add_alert(self._alert)
        self._alert.show()

    # Serialize

    def _dump(self, slide):
        ''' Dump data for sharing.'''
        data = []
        data.append(slide.uid, slide.colors, slide.title, slide.desc,
                    slide.pixbuf)
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
                self.slides.append(Slide(False, slide[0], slide[1], slide[2],
                                         slide[4], slide[3]))

    def _slide_search(self, uid):
        ''' Is this slide in the list already? '''
        for s in self.slides:
            if s.uid == uid:
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
        self.buddies.append(self.owner)
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
                self._send_event('j')

    def event_received_cb(self, text):
        ''' Data is passed as tuples: cmd:text '''
        if text[0] == 's':  # shared journal objects
            e, data = text.split(':')
            self._load(data)
        elif text[0] == 'j':  # Someone new has joined, so everyone must share
            for s in self.slides:
                if s.owner:  # Maybe stagger the timing of the sends?
                    self._send_event('s:' + str(self._dump(s)))

    def _send_event(self, entry):
        ''' Send event through the tube. '''
        if hasattr(self, 'chattube') and self.chattube is not None:
            self.chattube.SendText(entry)


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