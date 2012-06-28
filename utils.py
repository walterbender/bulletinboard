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
    return(os.path.join(activity.get_activity_root(), subpath))


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
    svg = SVG()
    svg.set_colors(colors)
    svg.set_stroke_width(5.0)
    svg_string = svg.header(width, height, background=False)
    svg.set_colors([colors[1], 'none'])
    width -= 5
    height -= 5
    svg_string += svg.rect(width, height, 0, 0, 2.5, 2.5)
    svg.set_colors([colors[0], 'none'])
    width -= 10
    height -= 10
    svg_string += svg.rect(width, height, 0, 0, 7.5, 7.5)
    svg_string += svg.footer()
    return svg_string


def load_svg_from_file(file_path, width, height):
    '''Create a pixbuf from SVG in a file. '''
    return gtk.gdk.pixbuf_new_from_file_at_size(file_path, width, height)


def file_to_base64(activity, path):
    base64 = os.path.join(get_path(activity, 'instance'), 'base64tmp')
    cmd = 'base64 <' + path + ' >' + base64
    subprocess.check_call(cmd, shell=True)
    file_handle = open(base64, 'r')
    data = file_handle.read()
    file_handle.close()
    os.remove(base64)
    return data


def pixbuf_to_base64(activity, pixbuf):
    ''' Convert pixbuf to base64-encoded data '''
    png_file = os.path.join(get_path(activity, 'instance'), 'imagetmp.png')
    if pixbuf != None:
        pixbuf.save(png_file, "png")
    data = file_to_base64(activity, png_file)
    os.remove(png_file)
    return data


def base64_to_file(activity, data, path):
    base64 = os.path.join(get_path(activity, 'instance'), 'base64tmp')
    file_handle = open(base64, 'w')
    file_handle.write(data)
    file_handle.close()
    cmd = 'base64 -d <' + base64 + '>' + path
    subprocess.check_call(cmd, shell=True)
    os.remove(base64)


def base64_to_pixbuf(activity, data, width=300, height=225):
    ''' Convert base64-encoded data to a pixbuf '''
    png_file = os.path.join(get_path(activity, 'instance'), 'imagetmp.png')
    base64_to_file(activity, data, png_file)
    pixbuf = gtk.gdk.pixbuf_new_from_file_at_size(png_file, width, height)
    os.remove(png_file)
    return pixbuf


def get_pixbuf_from_journal(dsobject, w, h):
    """ Load a pixbuf from a Journal object. """
    pixbufloader = \
        gtk.gdk.pixbuf_loader_new_with_mime_type('image/png')
    # pixbufloader.set_size(min(300, int(w)), min(225, int(h)))
    pixbufloader.set_size(int(w), int(h))
    try:
        pixbufloader.write(dsobject.metadata['preview'])
        pixbuf = pixbufloader.get_pixbuf()
    except:
        pixbuf = None
    pixbufloader.close()
    return pixbuf


def svg_xo_chat(colors):
    svg = SVG()
    svg.set_colors(colors)
    svg_string = svg.header(55, 55, background=False)
    svg_string += svg.xo_chat()
    svg_string += svg.footer()
    return svg_string


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

    def xo_chat(self):
        self.set_stroke_width(3.5)
        svg_string = '<g transform="translate(1.514,0.358)">\n'
        svg_string += '<g transform="matrix(0.75,0,0,0.75,-1.156,10.875)">\n'
        svg_string += '<path d="M33.233,35.1l10.102,10.1c0.752,0.75,1.217,1.783,1.217,2.932   c0,2.287-1.855,4.143-4.146,4.143c-1.145,0-2.178-0.463-2.932-1.211L27.372,40.961l-10.1,10.1c-0.75,0.75-1.787,1.211-2.934,1.211   c-2.284,0-4.143-1.854-4.143-4.141c0-1.146,0.465-2.184,1.212-2.934l10.104-10.102L11.409,24.995   c-0.747-0.748-1.212-1.785-1.212-2.93c0-2.289,1.854-4.146,4.146-4.146c1.143,0,2.18,0.465,2.93,1.214l10.099,10.102l10.102-10.103   c0.754-0.749,1.787-1.214,2.934-1.214c2.289,0,4.146,1.856,4.146,4.145c0,1.146-0.467,2.18-1.217,2.932L33.233,35.1z"\n'
        svg_string += self._svg_style()
        svg_string += '<circle cx="27.371" cy="10.849" r="8.122"\n'
        svg_string += self._svg_style()
        svg_string += '</g>\n'
        svg_string += '<g transform="matrix(0.4,0,0,0.4,26.061,0.178)">\n'
        svg_string += '<path d="m 9.263,48.396 c 0.682,1.152 6.027,0.059 8.246,-1.463 2.102,-1.432 3.207,-2.596 4.336,-2.596 1.133,0 12.54,0.92 20.935,-5.715 C 50.005,32.915 52.553,24.834 47.3,17.185 42.048,9.541 33.468,8.105 26.422,8.625 16.806,9.342 4.224,16.91 4.677,28.313 c 0.264,6.711 3.357,9.143 4.922,10.703 1.562,1.566 4.545,1.566 2.992,5.588 -0.61,1.579 -3.838,2.918 -3.328,3.792 z"\n'
        svg_string += self._svg_style()
        svg_string += '</g>\n'
        svg_string += '</g>\n'
        return svg_string

    def rect(self, w, h, rx, ry, x, y):
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

    def _background(self, w, h, scale=1):
        return self.rect((w - 0.5) * scale, (h - 0.5) * scale, 1, 1, 0.25, 0.25)

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
