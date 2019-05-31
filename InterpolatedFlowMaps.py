#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#   .-.                              _____                                  __
#   /v\    L   I   N   U   X       / ____/__   ___   ___   ____ ___   ___  / /_  __  __
#  // \\                          / / __/ _ \/ __ \/ __ `/ ___/ __ `/ __ \/ __ \/ / / /
# /(   )\                        / /_/ /  __/ /_/ / /_/ / /  / /_/ / /_/ / / / / /_/ /
#  ^^-^^                         \____/\___/\____/\__, /_/   \__,_/ .___/_/ /_/\__, /
#                                                /____/          /_/          /____/

"""
This script draws flow maps for rendering in a GIS. It does this by drawing an
interpolation between origins and destinations in the output coordinate system,
combined with an across-track point. This module depends on GDAL/OGR, pyproj,
shapely, and scipy, each of which is freely available and open-source.

You must supply the script with a csv file where each row represents an arc
with a flow magnitude. Specific information about the required format of that
csv file is in the README file acompanying this script.

This is written for Python 3; it may not work on Python 2.

Written against versions (via the Anaconda Python distribution):
Python 3.5.3
scipy 0.19.0
gdal 2.1.0
shapely 1.5.16
pyproj 1.9.5.1

Please feel free to contact the author, Dr. Paulo Raposo, at
pauloj.raposo@outlook.com. Thanks for your interest!

- Paulo, http://volweb.utk.edu/~praposo

"""

dependencies = """Python 3, scipy, gdal, shapely, pyproj (Proj.4)"""

progName = "Interpolated Flow Maps"
__version__ = "0.3, March 2018"

license = """
# Under MIT License:
#
# Copyright (c) 2018 Paulo Raposo, Ph.D. - pauloj.raposo@outlook.com
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""



# Notes /////////////////////////////////////////////////////////////////////////////

# TODO: make script write any other attributes to output, too.
# TODO: allow user to skew curves.

# Imports ///////////////////////////////////////////////////////////////////////////

try:
    import pyproj
    from pyproj import Proj
except ImportError:
    print("""This script depends on the pyproj library, which isn't installed in
    this Pyhon environment. Please install the library or use an environment
    with it installed. Exiting.""")
    exit()
try:
    import osgeo
    from osgeo import ogr, gdal, osr
    gdal.UseExceptions()
except ImportError:
    print("""This script depends on the GDAL library, which isn't installed in this
    Python environment. Please install the library or use a Python environment
    with GDAL installed. Exiting.""")
    exit()
try:
    from scipy.interpolate import CubicSpline, Akima1DInterpolator, PchipInterpolator
except ImportError:
    print("""This script depends on the scipy library, version 0.18 or greater,
    which isn't installed in this Python environment. Please install the
    library or use a Python environment with scipy installed. Exiting.""")
    exit()
try:
    import shapely.affinity as aff
    import shapely.geometry
    from shapely.geometry import Point
except ImportError:
    print("""This script depends on the shapely library, version 1.5.17.post1 or
    greater, which isn't installed in this Python environment. Please install
    the library or use a Python environment with scipy installed. Exiting.""")
    exit()

import os, csv, argparse, math, re
from urllib import request
import numpy as np
# import datetime, logging


# Functions & Classes ///////////////////////////////////////////////////////////////////

def calcOrthogonalVector(aVector, clockwise):
    """Given a 2-vector (i.e., a numpy 2D array), this returns the orthogonal
    vector of the same magnitude in either the clockwise or counter-clockwise
    direction, corresponding to the given boolean flag."""
    if clockwise == True:
        return np.array([aVector[1], aVector[0] * -1.0])
    else:
        return np.array([aVector[1] * -1.0, aVector[0]])

def calcAlongSegmentCoords(xy1, xy2, asf):
    """Given the endpoints of a line segment, and an 'along-segment fraction,'
    returns the coordinates of the midpoint by calculating simple x and y
    ranges, each times the value of asf."""
    ydiff = (float(xy2[1]) - float(xy1[1]))
    xdiff = (float(xy2[0]) - float(xy1[0]))
    yMid = float(xy1[1]) + (asf * ydiff)
    xMid = float(xy1[0]) + (asf * xdiff)
    return (xMid, yMid)

def generateInterpolator(xSeries, ySeries, aType):
    """Given an x and y series (assumed to be in sync with each other!),
    and a string indicating which type of interpolant is asked for,
    returns the calculated interpolation function from the appropriate
    SciPy method. Options are 'cs' for cubic spline, 'a' for Akima, and
    'pchip' for PCHIP."""
    interpo = acceptedInterpolators[aType]
    if interpo == CubicSpline:
        # Boundary Conditions are crucial to shape here!!!!
        # TODO: study these and do something smart here using first and second derivatives at line ends.
        # see https://docs.scipy.org/doc/scipy-0.18.1/reference/generated/scipy.interpolate.CubicSpline.html
        i = interpo(xSeries, ySeries, bc_type=((2, 0.0), (2, 0.0))) # A 'natural' spline, with second derivatives at ends = 0.0.
    else:
        # Akima or PCHIP
        i =  interpo(xSeries, ySeries)
    return i

def createLineString(xyList):
    """Creates an ORG LineString geometry, given a sequenced list of
    vertices, being tuples of format (x,y)."""
    line = ogr.Geometry(ogr.wkbLineString)
    for v in xyList:
        line.AddPoint(v[0], v[1]) # x then y
    return line

def createAField(dstLayer, fieldName, fieldType):
    """Simple field maker for this script."""
    new_field = ogr.FieldDefn(fieldName, fieldType)
    dstLayer.CreateField(new_field)

def strictly_increasing(L):
    """Checks strict increasing monotonicity of a list of numbers.
    Returns True or False."""
    # With thanks to "6502": http://stackoverflow.com/questions/4983258/python-how-to-check-list-monotonicity
    return all(x<y for x, y in zip(L, L[1:]))

def gdal_error_handler(err_class, err_num, err_msg):
    # https://pcjericks.github.io/py-gdalogr-cookbook/gdal_general.html#install-gdal-ogr-error-handler
    # https://trac.osgeo.org/gdal/wiki/PythonGotchas#Gotchasthatarebydesign...orperhistory
    errtype = {
            gdal.CE_None:'None',
            gdal.CE_Debug:'Debug',
            gdal.CE_Warning:'Warning',
            gdal.CE_Failure:'Failure',
            gdal.CE_Fatal:'Fatal'
    }
    err_msg = err_msg.replace('\n',' ')
    err_class = errtype.get(err_class, 'None')
    print('Error Number: %s' % (err_num))
    print('Error Type: %s' % (err_class))
    print('Error Message: %s' % (err_msg))

def filterProj4String(p4string, should_print_final_string):
    """
    Removes the '+units' flag and value from a Proj4 string, and the
    '+ellps' flag and value if there is a '+datum' flag and value, 
    since those seems to trip pyproj up. Seems kludgy. Argh.
    """

    def should_keep_flag(flag, should_remove_ellps):
        """
        Determines if a flag should be kept
        in the string.
        """
        if flag.startswith("+units="):
            return False

        if should_remove_ellps and flag.startswith("+ellps="):
            return False

        return True

    has_datum_flag = "+datum=" in p4string

    flags = [
        flag for flag in p4string.split(" ")
        # Having a datum means specifying an ellipse is redundant.
        if should_keep_flag(flag, has_datum_flag)
    ]

    # Return the final filtered Proj4 string
    outstring = " ".join(flags)
    if should_print_final_string:
        print("String returned: {}".format(outstring))
    return outstring

class LicenseAction(argparse.Action):
    """A custom action to get the license to print, and then exit."""
    def __init__(self, nargs=0, **kw):
        super().__init__(nargs=nargs, **kw)
    def __call__(self, parser, namespace, values, option_string=None):
        print(license)


# The acceptable values for interpolator types as code and SciPy method pairs.
acceptedInterpolators = {
    "cs":    CubicSpline,
    "a":     Akima1DInterpolator,
    "pchip": PchipInterpolator
}

# The acceptable output file types by file extension and their driver names for OGR.
# These are a hand-picked subset of these: http://gdal.org/1.11/ogr/ogr_formats.html.
# These are chosen mainly because they're available in OGR by default (i.e., OGR is
# compiled supporting them by default), and they carry attribute fields over well.
typesAndDrivers = {
    ".shp":     "ESRI Shapefile",
    ".geojson": "GeoJSON",
    ".kml":     "KML",
    ".gml":     "GML",
    ".gmt":     "GMT"
}


# Script /////////////////////////////////////////////////////////////////////////////////

def main():

    """The main method of this script, for making flow maps, hot and fresh
     to your table (or desk), all flowy and map-like - that's amore!"""

    # Constants, defaults, etc. /////////////////////////////////////////////////////////

    # Set up error handler for GDAL
    gdal.PushErrorHandler(gdal_error_handler)

    # EPSG:4326 WGS 84 - for required input.
    wgs84RefURL = "http://spatialreference.org/ref/epsg/4326/" # Retrieved string below on 2017-06-01
    epsgWGS84Proj4 = "+proj=longlat +ellps=WGS84 +datum=WGS84 +no_defs"
    wgs84SR = osr.SpatialReference()
    wgs84SR.ImportFromProj4(epsgWGS84Proj4)

    # EPSG:3785 Web Mercator - for default output.
    webMercatorRefURL = "http://spatialreference.org/ref/epsg/3785/" # Retrieved string below on 2017-06-01
    epsgWebMercProj4 = "+proj=merc +lon_0=0 +k=1 +x_0=0 +y_0=0 +a=6378137 +b=6378137 +towgs84=0,0,0,0,0,0,0 +no_defs" # manually removed +units=m
    wmSR = osr.SpatialReference()
    wmSR.ImportFromProj4(epsgWebMercProj4)

    # Output field names
    textFieldNames = ["Orig", "Dest"]
    floatFieldNames = ["FlowMag", "OrigLat", "OrigLon", "DestLat", "DestLon"]

    # gr = 0.25 / 1.618 # For the Golden Ratio, phi.

    # Usage messages, and parse command line arguments.
    descString = progName + " -- " + "A script for making flow maps in GIS, using interpolated paths, by Paulo Raposo (pauloj.raposo@outlook.com).\nUnder MIT license. \nWritten for Python 3 - may not work on 2. Dependencies include: " + dependencies + "."
    parser = argparse.ArgumentParser(prog = progName, description = descString, formatter_class = argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ROUTES", help = "CSV file specifying routes and magnitudes. Coordinates must be lat and lon in WGS84. Please see the README file for required formatting.")
    parser.add_argument("OUTPUTFILE", help = "File path and name for output shapefile. The containing directory must already exist. The file format is determined from the extension given here, with these options: .shp, .kml, .gml, .gmt, or .geojson.")
    parser.add_argument("--outproj4", help = "Output projected coordinate system to draw flow arcs in, given as a Proj.4 string. Often available at spatialreference.org. Three input formats are acceptable: a Proj.4 string, a URL starting with 'http://' to the Proj.4 string for a coodinate system on spatialreference.org (e.g., http://spatialreference.org/ref/esri/53012/proj4/), or a full path to a plain text file containing (only) a Proj.4 string. Default output projection is Web Mercator (" + webMercatorRefURL + ").", default=epsgWebMercProj4)
    parser.add_argument("-i", "--interpolator", help = "The type of interpolator to use. Options are 'cs' for cubic spline (the default), 'a' for Akima, and 'pchp' for PCHIP.", default="cs")
    parser.add_argument("-a", "--asf", help = "The 'along-segment fraction' of the straight line segment between start and end points of a flow at which an orthogonal vector will be found to construct the deviation point. Expressed as a number between 0.0 and 1.0. Default is %(default)f.", default=0.5, type=float)
    parser.add_argument("-d", "--dev", help = "The across-track distance at which a deviated point should be established from the straight-line vector between origin and destination points, expressed as a fraction of the straight line distance. Larger values make arcs more curved, while zero makes straight lines. Negative values result in right-handed curves. Default is %(default)f.", default=0.15, type=float)
    parser.add_argument("-v", "--vpa", help = "The number of vertices the mapped arcs should each have. Must be greater than 3, but typically should be at least several dozen to a few hundred or so. Default is %(default)d.", default=300, type=int)
    parser.add_argument("--ccw", default = False, action = "store_true", help = "Sets the across-track deviation point on the left by rotating the across-track vector counter-clockwise. Changes the directions that arcs curve in. Default is clockwise.")
    parser.add_argument("--verbose", default = False, action = "store_true", help = "Be verbose while running, printing lots of status messages.")
    parser.add_argument("--version", action = "version", version = "%(prog)s " + __version__)
    parser.add_argument("--license", action = LicenseAction, nargs = 0, help = "Print the script's license and exit.")
    #
    args = parser.parse_args()

    # Set variables, do various checks on input arguments.
    pathAndFile, ext = os.path.splitext(args.OUTPUTFILE)
    try:
        ogrDriverName = typesAndDrivers[ext.lower()]
    except:
        print("Output file must be of one of these types: {}. Exiting.".format(str(list(typesAndDrivers.keys()))))
        exit()
    
    if args.interpolator not in acceptedInterpolators:
        print("Didn't understand the specified interpolator type. Acceptable codes are {}. Exiting.".format(str(list(acceptedInterpolators.keys()))))
        exit()

    if args.asf <= 0.0 or args.asf >= 1.0:
        print("Along-segment fraction {} is out of bounds, must be within 0.0 and 1.0. Exiting.".format(str(args.asf)))
        exit()

    if args.outproj4.startswith("http://"):
        # URL.
        f = request.urlopen(args.outproj4)
        outP4 = filterProj4String( str(f.read(), "utf-8"), args.verbose) # Decode from byte string.
    elif os.path.exists(args.outproj4):
        # Assuming a path to a text file has been passed in.
        f = open(args.outproj4)
        outP4 = filterProj4String( f.read(), args.verbose)
        f.close()
    else:
        # Proj.4 string.
        outP4 = filterProj4String( args.outproj4, args.verbose)

    # Build the necessary coordinate systems.
    pIn = Proj(epsgWGS84Proj4)
    try:
        pOut = Proj(outP4)
    except:
        print("Unable to define projection from input provided for Proj4. Please ensure the string is valid. Exiting.")
        exit()
    outSR = osr.SpatialReference()
    outSR.ImportFromProj4(outP4)

    # Create an output file where the user specified, and add attribute fields to it.
    if args.verbose:
        print("Preparing file for output...")
    driver = ogr.GetDriverByName(ogrDriverName)
    outFile = args.OUTPUTFILE
    dst_ds = driver.CreateDataSource(outFile)
    fName = os.path.splitext(os.path.split(outFile)[1])[0]
    dst_layer = dst_ds.CreateLayer(fName, outSR, geom_type = ogr.wkbLineString)
    layer_defn = dst_layer.GetLayerDefn()
    for field in textFieldNames:
        createAField(dst_layer, field, ogr.OFTString)
    for field in floatFieldNames:
        createAField(dst_layer, field, ogr.OFTReal)

    # Open and read the CSV.
    # Each row is an arc/route in the flow map. Process each row into a feature.
    if args.verbose:
        print("Reading csv...")
    with open(args.ROUTES) as csvfile:
        dReader = csv.DictReader(csvfile, delimiter = ',', quotechar = '"')
        # Reference fields by their headers; first row taken for headers by default.
        # Find every unique origin point, and separate arcs into groups by origin point,
        # stored in a dictionary.
        originGroups = {} # Entries return lists of lists.
        originKeys = []

        for row in dReader: # Populate originGroups.

            # These strings are the headers (and fields) the input csv must have.
            oName  =  row["OrigName"]
            oLat   =  row["OrigLat"]
            oLon   =  row["OrigLon"]
            dName  =  row["DestName"]
            dLat   =  row["DestLat"]
            dLon   =  row["DestLon"]
            floMag =  row["FlowMag"]

            thisRecordStrings = [oName, oLat, oLon, dName, dLat, dLon, floMag]
            thisOrigin = (float(thisRecordStrings[1]), float(thisRecordStrings[2]))
            if thisOrigin not in originGroups: # Make new dictionary entry if new.
                originGroups[thisOrigin] = []
                originKeys.append(thisOrigin)
            # Whether new or not, append this record to the values of its key.
            originGroups[thisOrigin].append(thisRecordStrings)

        for ok in originKeys:

            theseArcs = originGroups[ok]

            for a in theseArcs:

                if args.verbose:
                    print(str(a[0]) + " to " + str(a[3]) + "..." )

                originLatLon = ok # lat, lon
                destinLatLon = (float(a[4]), float(a[5])) # lat, lon

                # Convert these lat lon pairs to x,y in the outbound projected coordinate system, using pyproj.
                xOrigOut, yOrigOut = pOut(originLatLon[1], originLatLon[0])
                xDestOut, yDestOut = pOut(destinLatLon[1], destinLatLon[0])

                origMapVert = (xOrigOut, yOrigOut)
                destMapVert = (xDestOut, yDestOut)

                ## Find the "dev" point for defining an interpolator, using vector geometry.

                # Straight-line route as a vector starting at coord system origin is second vertex minus first.
                routeVector = np.array([destMapVert[0], destMapVert[1]]) - np.array([origMapVert[0], origMapVert[1]])

                # get along-track fraction of line as vector.
                alongTrackVector = routeVector * args.asf

                # The user-set fraction of the arc distance for point dev.
                deviationVector = routeVector * args.dev

                # Get the left-handed orthogonal vector of this.
                orthogVector = calcOrthogonalVector(deviationVector, not args.ccw)

                # dev point is at the origin point + aMidpointVector + orthogVector
                devPointVector = np.array([origMapVert[0], origMapVert[1]]) + alongTrackVector + orthogVector
                devMapVert = (devPointVector[0], devPointVector[1])

                # Now determine the interpolator going through the origin, the dev point, and the destination.
                # NB: Usually, for the SciPy functions we use, the x values must be a strictly monotonic,
                # increasing series. To handle all cases, we will translate all three points equally so that the
                # origin point lies on the coordinate system origin, and rotate all points counterclockwise so
                # that the origin and destination y values are both 0. This will ensure the three x values are
                # monotonic, increasing in sequence.

                # Translate all points by negative vector of origMapVert, so origMapVert lies on the origin.
                orgV = np.array([origMapVert[0], origMapVert[1]])
                devV = np.array([devMapVert[0], devMapVert[1]])
                desV = np.array([destMapVert[0], destMapVert[1]])
                orgV_shft = np.array([0.0, 0.0]) # orgV_shft minus itself.
                devV_shft = devV - orgV
                desV_shft = desV - orgV
                devPt = Point(devV_shft[0], devV_shft[1]) # Shapely Point object.
                desPt = Point(desV_shft[0], desV_shft[1]) # Shapely Point object.
                # Determine angle necessary to rotate desV_shft so it lies on the x axis.
                # The origin vertex obviously doesn't change, but the other two do.
                # Angle of rotation necessary is given in radians by math.atan2(y2-y1, x2-x1).
                # Thanks to Jim Lewis: http://stackoverflow.com/questions/2676719/calculating-the-angle-between-the-line-defined-by-two-points
                theta_desV_shift = math.atan2( desV_shft[1] , desV_shft[0] ) # Returned in radians.
                angleToRotateBy = -1.0 * theta_desV_shift
                # Rotate both the dev point and the destination point by this angle.
                orgV_shft_rot = orgV_shft # Origin unchanged.
                devV_shft_rot = aff.rotate(devPt, angleToRotateBy, origin = (0.0, 0.0), use_radians = True)
                desV_shft_rot = aff.rotate(desPt, angleToRotateBy, origin = (0.0, 0.0), use_radians = True)
                # Restate each point as a simple tuple.
                orgV_shft_rot_tuple = (0.0, 0.0)
                devV_shft_rot_tuple = (devV_shft_rot.x, devV_shft_rot.y)
                desV_shft_rot_tuple = (desV_shft_rot.x, desV_shft_rot.y)
                # We've got the three necessary vertices to construct an interpolator, now in strictly increasing x order.
                interpoVerts = [orgV_shft_rot_tuple, devV_shft_rot_tuple, desV_shft_rot_tuple]
                #
                # Just a sanity check...
                if not strictly_increasing([ orgV_shft_rot_tuple[0], devV_shft_rot_tuple[0], desV_shft_rot_tuple[0] ]):
                    print("X values for this interpolation are not strictly increasing!")
                # The interpolator:
                series_x = [i[0] for i in interpoVerts]
                series_y = [i[1] for i in interpoVerts]
                thisInterpolator = generateInterpolator(series_x, series_y, args.interpolator)

                # Determine how many vertices each arc should have, using user-specified vertsPerArc,
                # over the range defined by the destination x - the origin x.
                xRange = series_x[2] - series_x[0]
                anInterval = xRange / args.vpa
                # xValues = np.linspace(series_x[0], series_x[2], num=anInterval, endpoint=True) # works, but slower by far than np.append()
                xValues = np.append( np.arange(series_x[0], series_x[2], anInterval), series_x[2] )
                # NB: This leaves the dev point behind! We should have many others near it though,
                # or it could be inserted into the sequence here.
                #
                # Add final (rotated and translated) destination x value to xValues.
                np.append(xValues, desV_shft_rot_tuple[0])
                # Evaluate interpolants by thisInterpolator([xValues]), store vertices as tuples (x,y).
                yValues = thisInterpolator(xValues)
                # Build list of verts with origin at beginning, then interpolated ones, then destination.
                vertsInterpolated = [ (x,y) for x,y in zip(xValues, yValues) ]
                # Now rotate these points back...
                rerotatedPoints = []
                for vi in vertsInterpolated:
                    aVert = Point(vi[0], vi[1]) # Shapely Point object.
                    aRerotatedPoint = aff.rotate(aVert, theta_desV_shift, origin = (0.0, 0.0), use_radians = True)
                    rerotatedPoints.append(aRerotatedPoint)
                # ...and now translate the rerotated points back to projected map coordinates.
                rectifiedPoints = []
                for rrp in rerotatedPoints:
                    rrpV = np.array([rrp.x, rrp.y])
                    rectV = rrpV + orgV
                    aPoint = (rectV[0], rectV[1])
                    rectifiedPoints.append(aPoint)
                # Finally, build a line with this list of vertices, carrying over
                # the FlowMag attribute, and write to file.
                anArc = ogr.Feature(layer_defn)
                anArc.SetField( textFieldNames[0], a[0]) # origin
                anArc.SetField( textFieldNames[1], a[3]) # destination
                anArc.SetField(floatFieldNames[0], a[6]) # flow
                anArc.SetField(floatFieldNames[1], a[1]) # origin lat
                anArc.SetField(floatFieldNames[2], a[2]) # origin lon
                anArc.SetField(floatFieldNames[3], a[4]) # destination lat
                anArc.SetField(floatFieldNames[4], a[5]) # destination lon
                lineGeometry = createLineString(rectifiedPoints) # actually create the line
                anArc.SetGeometry(lineGeometry)
                dst_layer.CreateFeature(anArc)
                anArc = None # Free resources, finish this route.

    dst_ds = None # Destroy the data source to free resouces and finish writing.

    print("Finished, output written to: " + outFile)


# Main module check /////////////////////////////////////////////////////////////////////

if __name__ == '__main__':
    main()


# fin
