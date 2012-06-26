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


import gtk
import os
import subprocess

from gettext import gettext as _

XO1 = 'xo1'
XO15 = 'xo1.5'
XO175 = 'xo1.75'
UNKNOWN = 'unknown'


def play_audio_from_file(file_path):
    """ Audio media """
    command_line = ['gst-launch', 'filesrc', 'location=' + file_path,
                    '! oggdemux', '! vorbisdec', '! audioconvert',
                    '! alsasink']
    subprocess.call(command_line)


def get_hardware():
    """ Determine whether we are using XO 1.0, 1.5, or "unknown" hardware """
    product = _get_dmi('product_name')
    if product is None:
        if os.path.exists('/sys/devices/platform/lis3lv02d/position'):
            return XO175  # FIXME: temporary check for XO 1.75
        elif os.path.exists('/etc/olpc-release') or \
           os.path.exists('/sys/power/olpc-pm'):
            return XO1
        else:
            return UNKNOWN
    if product != 'XO':
        return UNKNOWN
    version = _get_dmi('product_version')
    if version == '1':
        return XO1
    elif version == '1.5':
        return XO15
    else:
        return XO175


def _get_dmi(node):
    ''' The desktop management interface should be a reliable source
    for product and version information. '''
    path = os.path.join('/sys/class/dmi/id', node)
    try:
        return open(path).readline().strip()
    except:
        return None


def get_path(activity, subpath):
    """ Find a Rainbow-approved place for temporary files. """
    try:
        return(os.path.join(activity.get_activity_root(), subpath))
    except:
        # Early versions of Sugar didn't support get_activity_root()
        return(os.path.join(os.environ['HOME'], ".sugar/default",
                            "org.sugarlabs.PortfolioActivity", subpath))


def _luminance(color):
    ''' Calculate luminance value '''
    return int(color[1:3], 16) * 0.3 + int(color[3:5], 16) * 0.6 + \
           int(color[5:7], 16) * 0.1


def lighter_color(colors):
    ''' Which color is lighter? Use that one for the text background '''
    if _luminance(colors[0]) > _luminance(colors[1]):
        return 0
    return 1


def svg_str_to_pixbuf(svg_string):
    ''' Load pixbuf from SVG string '''
    pl = gtk.gdk.PixbufLoader('svg')
    pl.write(svg_string)
    pl.close()
    pixbuf = pl.get_pixbuf()
    return pixbuf


def svg_rectangle(width, height, colors):
    ''' Generate a rectangle frame in two colors '''
    return \
'<?xml version="1.0" encoding="UTF-8" standalone="no"?>\
<svg\
   version="1.1"\
   width="%f"\
   height="%f">\
    <g>\
      <rect\
         width="%f"\
         height="%f"\
         x="2.5"\
         y="2.5"\
         style="fill:none;stroke:%s;stroke-width:5;stroke-linecap:round;stroke-linejoin:round;stroke-miterlimit:4;stroke-opacity:1;stroke-dasharray:none" />\
      <rect\
         width="%f"\
         height="%f"\
         x="7.5"\
         y="7.5"\
         style="fill:none;stroke:%s;stroke-width:5;stroke-linecap:round;stroke-linejoin:round;stroke-miterlimit:4;stroke-opacity:1;stroke-dasharray:none" />\
    </g>\
</svg>' % (width, height,
           width - 5, height - 5, colors[1],
           width - 15, height - 15, colors[0])


def load_svg_from_file(file_path, width, height):
    '''Create a pixbuf from SVG in a file. '''
    return gtk.gdk.pixbuf_new_from_file_at_size(file_path, width, height)


def image_to_base64(pixbuf, path_name):
    """ Convert an image to base64-encoded data """
    file_name = os.path.join(path_name, 'imagetmp.png')
    if pixbuf != None:
        pixbuf.save(file_name, "png")
    return file_to_base64(file_name, path_name)


def file_to_base64(file_name, path_name):
    base64 = os.path.join(path_name, 'base64tmp')
    cmd = "base64 <" + file_name + " >" + base64
    subprocess.check_call(cmd, shell=True)
    file_handle = open(base64, 'r')
    data = file_handle.read()
    file_handle.close()
    return data


def get_pixbuf_from_journal(dsobject, w, h):
    """ Load a pixbuf from a Journal object. """
    pixbufloader = \
        gtk.gdk.pixbuf_loader_new_with_mime_type('image/png')
    pixbufloader.set_size(min(300, int(w)), min(225, int(h)))
    try:
        pixbufloader.write(dsobject.metadata['preview'])
        pixbuf = pixbufloader.get_pixbuf()
    except:
        pixbuf = None
    pixbufloader.close()
    return pixbuf


def genblank(w, h, colors, stroke_width=1.0):
    svg = SVG()
    svg.set_colors(colors)
    svg.set_stroke_width(stroke_width)
    svg_string = svg.header(w, h)
    svg_string += svg.footer()
    return svg_string


class SVG:
    ''' SVG generators '''

    def __init__(self):
        self._scale = 1
        self._stroke_width = 1
        self._fill = '#FFFFFF'
        self._stroke = '#FFFFFF'

    def _svg_style(self, extras=""):
        return "%s%s%s%s%s%f%s%s%s" % ("style=\"fill:", self._fill, ";stroke:",
                                       self._stroke, ";stroke-width:",
                                       self._stroke_width, ";", extras,
                                       "\" />\n")

    def _svg_rect(self, w, h, rx, ry, x, y):
        svg_string = "       <rect\n"
        svg_string += "          width=\"%f\"\n" % (w)
        svg_string += "          height=\"%f\"\n" % (h)
        svg_string += "          rx=\"%f\"\n" % (rx)
        svg_string += "          ry=\"%f\"\n" % (ry)
        svg_string += "          x=\"%f\"\n" % (x)
        svg_string += "          y=\"%f\"\n" % (y)
        self.set_stroke_width(self._stroke_width)
        svg_string += self._svg_style()
        return svg_string

    def _background(self, w=80, h=60, scale=1):
        return self._svg_rect((w - 0.5) * scale, (h - 0.5) * scale,
                              1, 1, 0.25, 0.25)

    def header(self, w=80, h=60, scale=1, background=True):
        svg_string = "<?xml version=\"1.0\" encoding=\"UTF-8\""
        svg_string += " standalone=\"no\"?>\n"
        svg_string += "<!-- Created with Emacs -->\n"
        svg_string += "<svg\n"
        svg_string += "   xmlns:svg=\"http://www.w3.org/2000/svg\"\n"
        svg_string += "   xmlns=\"http://www.w3.org/2000/svg\"\n"
        svg_string += "   version=\"1.0\"\n"
        svg_string += "%s%f%s" % ("   width=\"", scale * w * self._scale,
                                  "\"\n")
        svg_string += "%s%f%s" % ("   height=\"", scale * h * self._scale,
                                  "\">\n")
        svg_string += "%s%f%s%f%s" % ("<g\n       transform=\"matrix(",
                                      self._scale, ",0,0,", self._scale,
                                      ",0,0)\">\n")
        if background:
            svg_string += self._background(w, h, scale)
        return svg_string

    def footer(self):
        svg_string = "</g>\n"
        svg_string += "</svg>\n"
        return svg_string

    def set_scale(self, scale=1.0):
        self._scale = scale

    def set_colors(self, colors):
        self._stroke = colors[0]
        self._fill = colors[1]

    def set_stroke_width(self, stroke_width=1.0):
        self._stroke_width = stroke_width
