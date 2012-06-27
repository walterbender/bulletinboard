# -*- coding: utf-8 -*-
#Copyright (c) 2011 Walter Bender

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# You should have received a copy of the GNU General Public License
# along with this library; if not, write to the Free Software
# Foundation, 51 Franklin Street, Suite 500 Boston, MA 02110-1335 USA


import pygtk
pygtk.require('2.0')
import gtk
from glib import GError
import os.path
import time
import cairo
import pango
import pangocairo
from gettext import gettext as _

from utils import get_pixbuf_from_journal


HEAD = 32
BODY = 12
PAGE_WIDTH = 504
PAGE_HEIGHT = 648
LEFT_MARGIN = 10
TOP_MARGIN = 20


def save_pdf(activity,  nicks, description=None):
    ''' Output a PDF document from the title, pictures, and descriptions '''

    if len(activity.slides) == 0:
        return None

    tmp_file = os.path.join(activity.datapath, 'output.pdf') 
    pdf_surface = cairo.PDFSurface(tmp_file, 504, 648)

    fd = pango.FontDescription('Sans')
    cr = cairo.Context(pdf_surface)
    cr.set_source_rgb(0, 0, 0)

    y = TOP_MARGIN
    for nick in nicks:
        show_text(cr, fd, nick, HEAD, LEFT_MARGIN, y)
        y += HEAD

    show_text(cr, fd, time.strftime('%x', time.localtime()),
              BODY, LEFT_MARGIN, y + 3 * HEAD)
    if description is not None:
        show_text(cr, fd, description, BODY, LEFT_MARGIN, y + 4 * HEAD)
    cr.show_page()

    for i, slide in enumerate(activity.slides):
        if slide.title is not None:
            show_text(cr, fd, slide.metadata['title'], HEAD, LEFT_MARGIN,
                      TOP_MARGIN)
        else:
            show_text(cr, fd, _('untitled'), HEAD, LEFT_MARGIN, TOP_MARGIN)

        w = 300
        h = 225
        if slide.pixbuf is not None:
            cr.save()
            cr = gtk.gdk.CairoContext(cr)
            cr.set_source_pixbuf(slide.pixbuf, LEFT_MARGIN, TOP_MARGIN + 150)
            cr.rectangle(LEFT_MARGIN, TOP_MARGIN + 150, w, h)
            cr.fill()
            cr.restore()

        if slide.desc is not None:
            show_text(cr, fd, slide.desc, BODY, LEFT_MARGIN, h + 175)
        cr.show_page()

    return tmp_file

def show_text(cr, fd, label, size, x, y):
    cr = pangocairo.CairoContext(cr)
    pl = cr.create_layout()
    fd.set_size(int(size * pango.SCALE))
    pl.set_font_description(fd)
    if type(label) == str or type(label) == unicode:
        pl.set_text(label.replace('\0', ' '))
    else:
        pl.set_text(str(label))
    pl.set_width((PAGE_WIDTH - LEFT_MARGIN * 2) * pango.SCALE)
    cr.save()
    cr.translate(x, y)
    cr.update_layout(pl)
    cr.show_layout(pl)
    cr.restore()
