"""
A simple leaflet-based pannable map server



"""

#-----------------------------------------------------------------------------
# Copyright (c) 2013, yt Development Team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file COPYING.txt, distributed with this software.
#-----------------------------------------------------------------------------
import os
import numpy as np

from functools import wraps

from yt.visualization.image_writer import apply_colormap
from yt.visualization.fixed_resolution import FixedResolutionBuffer
from yt.utilities.lib.misc_utilities import get_color_bounds
from yt.utilities.png_writer import write_png_to_string

import bottle

local_dir = os.path.dirname(__file__)

def exc_writeout(f):
    import traceback
    @wraps(f)
    def func(*args, **kwargs):
        try:
            rv = f(*args, **kwargs)
            return rv
        except Exception:
            traceback.print_exc(None, open("temp.exc", "w"))
            raise
    return func

class PannableMapServer(object):
    _widget_name = "pannable_map"
    def __init__(self, data, field, takelog, cmap, route_prefix = ""):
        self.data = data
        self.ds = data.ds
        self.field = field
        self.cmap = cmap

        bottle.route("%s/map/:field/:L/:x/:y.png" % route_prefix)(self.map)
        bottle.route("%s/map/:field/:L/:x/:y.png" % route_prefix)(self.map)
        bottle.route("%s/" % route_prefix)(self.index)
        bottle.route("%s/:field" % route_prefix)(self.index)
        bottle.route("%s/index.html" % route_prefix)(self.index)
        bottle.route("%s/list" % route_prefix, "GET")(self.list_fields)
        # This is a double-check, since we do not always mandate this for
        # slices:
        self.data[self.field] = self.data[self.field].astype("float64")
        bottle.route(":path#.+#", "GET")(self.static)

        self.takelog = takelog
        self._lock = False

    def lock(self):
        import time
        while self._lock:
            time.sleep(0.01)
        self._lock = True

    def unlock(self):
        self._lock = False

    def map(self, field, L, x, y):
        if ',' in field:
            field = tuple(field.split(','))
        cmap = self.cmap
        dd = 1.0 / (2.0**(int(L)))
        relx = int(x) * dd
        rely = int(y) * dd
        DW = (self.ds.domain_right_edge - self.ds.domain_left_edge)
        xl = self.ds.domain_left_edge[0] + relx * DW[0]
        yl = self.ds.domain_left_edge[1] + rely * DW[1]
        xr = xl + dd*DW[0]
        yr = yl + dd*DW[1]
        try:
            self.lock()
            data = self.data[field]
            frb = FixedResolutionBuffer(self.data, (xl, xr, yl, yr), (256, 256))
            cmi, cma = get_color_bounds(self.data['px'], self.data['py'],
                                        self.data['pdx'], self.data['pdy'],
                                        data,
                                        self.ds.domain_left_edge[0],
                                        self.ds.domain_right_edge[0],
                                        self.ds.domain_left_edge[1],
                                        self.ds.domain_right_edge[1],
                                        dd*DW[0] / (64*256),
                                        dd*DW[0])
        finally:
            self.unlock()

        if self.takelog:
            cmi = np.log10(cmi)
            cma = np.log10(cma)
            to_plot = apply_colormap(np.log10(frb[field]), color_bounds = (cmi, cma),
                                     cmap_name=cmap)
        else:
            to_plot = apply_colormap(frb[field], color_bounds = (cmi, cma),
                                     cmap_name=cmap)

        rv = write_png_to_string(to_plot)
        return rv

    def index(self, field=None):
        if field is not None:
            self.field = field
        return bottle.static_file("map_index.html",
                    root=os.path.join(local_dir, "html"))

    def static(self, path):
        if path[-4:].lower() in (".png", ".gif", ".jpg"):
            bottle.response.headers['Content-Type'] = "image/%s" % (path[-3:].lower())
        elif path[-4:].lower() == ".css":
            bottle.response.headers['Content-Type'] = "text/css"
        elif path[-3:].lower() == ".js":
            bottle.response.headers['Content-Type'] = "text/javascript"
        full_path = os.path.join(os.path.join(local_dir, 'html'), path)
        return open(full_path, 'r').read()

    def list_fields(self):
        d = {}

        # Add deposit fields (only cic + density for now)
        for ptype in self.ds.particle_types:
            d[ptype] = [(('deposit', '%s_cic'     % ptype), False),
                        (('deposit', '%s_density' % ptype), False)]

        # Add fluid fields (only gas for now)
        for ftype in self.ds.fluid_types:
            d[ftype] = []
            for f in self.ds.derived_field_list:
                if f[0] != ftype:
                    continue

                active = f[1] == self.field
                d[ftype].append((f, active))

        # TODO: get projection domain instead of dataset width
        w = self.ds.domain_width.in_units('kpc').value[0]

        return dict(data=d, width=w, active=self.field)
