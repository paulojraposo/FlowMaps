# -*- coding: utf-8 -*-

#   .-.                              _____                                  __
#   /v\    L   I   N   U   X       / ____/__   ___   ___   ____ ___   ___  / /_  __  __
#  // \\  >Phear the Penguin<     / / __/ _ \/ __ \/ __ `/ ___/ __ `/ __ \/ __ \/ / / /
# /(   )\                        / /_/ /  __/ /_/ / /_/ / /  / /_/ / /_/ / / / / /_/ /
#  ^^-^^                         \____/\___/\____/\__, /_/   \__,_/ .___/_/ /_/\__, /
#                                                /____/          /_/          /____/

# TODO: remove reprojection from the script. Argh.

"""
This script draws flow maps for rendering in a GIS. It does this by drawing
the cubic splines between origins and destinations in the output coordinate system,
combined with an across-track point. This module depends on GDAL/OGR,
pyproj, shapely, and scipy, each of which is freely available and open-source.

You must supply the script with a csv file where each row represents an arc
with a flow magnitude. Specific information about the required format of that
csv file is in the README file acompanying this script.

This is written for Python 3; it may not work on Python 2.

Written against versions (via the Anaconda Python distribution):
Python 3.4
scipy 0.18.1
gdal 2.1.0
shapely 1.5.17.post1
pyproj 1.9.5.1

Please feel free to contact the author, Dr. Paulo Raposo, at
pauloj.raposo@outlook.com. Thanks for your interest!

- Paulo, pauloraposo.weebly.com

"""

dependencies = """Python 3
scipy
gdal
shapely
pyproj (Proj.4)"""

sf = """
  __                   ___
 (_ ` _   ) o  _   _   )_  ) _         _ |
.__) )_) (  ( ) ) )_) (   ( (_) )_)_) (  o
    (            (_                   _)
"""

progName = "Spline Flows"
__version__ = "0.1, June 2017"

license = """
# Under MIT License:
#
# Copyright (c) 2017 Paulo Raposo, Ph.D. - pauloj.raposo@outlook.com
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

# TODO: investigate +ellps and +datum proj4 strings for pyproj. I think when both are
# supplied it throws an error. Should be able to prevent that; if datum is given, ellipse
# doesn't need to be since it's implied.

# OGC WKT for Azimuthal Equidistant projection on North Pole (from http://spatialreference.org/ref/esri/102016/):  PROJCS["North_Pole_Azimuthal_Equidistant",GEOGCS["GCS_WGS_1984",DATUM["WGS_1984",SPHEROID["WGS_1984",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["Degree",0.017453292519943295]],PROJECTION["Azimuthal_Equidistant"],PARAMETER["False_Easting",0],PARAMETER["False_Northing",0],PARAMETER["Central_Meridian",0],PARAMETER["Latitude_Of_Origin",90],UNIT["Meter",1],AUTHORITY["EPSG","102016"]]
# NB - 102016 not recognized at http://www.epsg-registry.org

# Rotation about (0,0) in the Cartesian plane, in a right-handed coordinate system:
# x' = x cos(f) - y sin(f)
# y' = y cos(f) + x sin(f)
# These formulas work for degrees (not radians). The angle f is measured
# counterclockwise from the x axis (i.e., negative values go clockwise.)

# Rotation of a point with shapely - negative angles are clockwise, and vise versa.
# from shapely.geometry import Point
# point = Point(343.423, 23424.23)
# pointPrime = aff.rotate(point, -53.0, origin=(0.0, 0.0), use_radians=False)


# Imports ///////////////////////////////////////////////////////////////////////////

try:
    import pyproj
    from pyproj import Proj
except ImportError:
    print("""This script depends on the pyproj library, which isn't installed in
    this Pyhon environment. Please install the library or use an environment with
    it installed.
    Exiting.""")
    exit()
try:
    import osgeo
    from osgeo import ogr, gdal, osr
    gdal.UseExceptions()
except ImportError:
    print("""This script depends on the GDAL library, which isn't installed in this
    Python environment. Please install the library or use a Python environment with
    GDAL installed.
    Exiting.""")
    exit()
try:
    from scipy.interpolate import CubicSpline
    # from scipy.constants import golden
except ImportError:
    print("""This script depends on the scipy library, version 0.18 or greater,
    which isn't installed in this Python environment. Please install the library or
    use a Python environment with scipy installed.
    Exiting.""")
    exit()
try:
    import shapely.affinity as aff
    import shapely.geometry
    from shapely.geometry import Point
except ImportError:
    print("""This script depends on the shapely library, version 1.5.17.post1 or
    greater, which isn't installed in this Python environment. Please install the
    library or use a Python environment with scipy installed.
    Exiting.""")
    exit()

import os, csv, argparse, math, re
from urllib import request
import numpy as np
# import datetime, logging

# Functions & Classes ///////////////////////////////////////////////////////////////////

def calcOrthogonalVector(aVector, lefthandBoolean):
    """Given a 2-vector (i.e., a numpy 2D array), this returns the orthogonal
    vector of the same magnitude in either the left- or right-hand direction,
    corresponding to the given boolean flag."""
    if lefthandBoolean == True:
        return np.array([aVector[1], aVector[0] * -1.0])
    else:
        return np.array([aVector[1] * -1.0, aVector[0]])

def calcMidpointCoords(xy1, xy2):
    """Given the endpoints of a line segment, returns the coordinates of the
    midpoint by calculating simple x and y ranges times 0.5."""
    ydiff = (float(xy2[1]) - float(xy1[1]))
    xdiff = (float(xy2[0]) - float(xy1[0]))
    yMid = float(xy1[1]) + (0.5 * ydiff)
    xMid = float(xy1[0]) + (0.5 * xdiff)
    return (xMid, yMid)

def createLineString(xyList):
    """Creates an ORG LineString geometry, given a sequenced list of
    vertices, being tuples of format (x,y)."""
    line = ogr.Geometry(ogr.wkbLineString)
    for v in xyList:
        line.AddPoint(v[0], v[1]) # x then y from lat, lon
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

def stripUnitFlagFromProj4(p4string):
    """Removes the ''+units=m' flag from a Proj4 string, since that seems to trip pyproj up. Argh."""
    flags = p4string.split(" ") # I think spaces are always required in the Proj4 strings, as well as "+"
    filteredFlags = []
    for f in flags:
        exp = re.compile("\+units=")
        if not exp.match(f):
            filteredFlags.append(f)
    outstring = " ".join(filteredFlags)
    print("String returned: " + outstring)
    return outstring

class LicenseAction(argparse.Action):
    def __init__(self, nargs=0, **kw):
        super().__init__(nargs=nargs, **kw)
    def __call__(self, parser, namespace, values, option_string=None):
        print(license)


# Script /////////////////////////////////////////////////////////////////////////////////

def main():

    """The main method of this script, for making flow maps, hot and fresh
     to your table, all flowy and map-like - that's amore!"""

    # Constants, defaults, etc. /////////////////////////////////////////////////////////

    # EPSG:4326 WGS 84 - for required input.
    wgs84RefURL = "http://spatialreference.org/ref/epsg/4326/" # Retrieved string below 2017-06-01
    epsgWGS84Proj4 = "+proj=longlat +ellps=WGS84 +datum=WGS84 +no_defs"
    wgs84SR = osr.SpatialReference()
    wgs84SR.ImportFromProj4(epsgWGS84Proj4)

    # EPSG:3785 Web Mercator - for default output.
    webMercatorRefURL = "http://spatialreference.org/ref/epsg/3785/" # Retrieved string below 2017-06-01
    epsgWebMercProj4 = "+proj=merc +lon_0=0 +k=1 +x_0=0 +y_0=0 +a=6378137 +b=6378137 +towgs84=0,0,0,0,0,0,0 +no_defs" # manually removed +units=m
    wmSR = osr.SpatialReference()
    wmSR.ImportFromProj4(epsgWebMercProj4)

    # Output field names
    textFieldNames = ["Orig", "Dest"]
    floatFieldNames = ["FlowMag", "OrigLat", "OrigLon", "DestLat", "DestLon"]

    outP4 = epsgWebMercProj4
    leftHanded = True
    fractionOfPath = 0.5 # TODO: add ability to move the curvature apex along the route.
    vertsPerArc = 200
    devFraction = 0.15
    # devFraction = (1.0 / golden) # For the Golden Ratio, phi.

    # Set up error handler for GDAL
    gdal.PushErrorHandler(gdal_error_handler)

    # Parse command line arguments
    helpString = sf + "A script for making flow maps in GIS, using cubic splines,\nby Paulo Raposo (pauloj.raposo@outlook.com).\nWritten for Python 3 - may not work on 2.\nUnder MIT license.\n\nDependencies include:\n" + dependencies
    parser = argparse.ArgumentParser(prog = progName, description = helpString, formatter_class = argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ROUTES", help = "CSV file specifying routes and magnitudes. Coordinates must be lat and lon in WGS84. Please see the README file for required formatting.")
    parser.add_argument("OUTSHPFILE", help = "File path and name for output shapefile, with extension '.shp'. The directory must already exist.")
    parser.add_argument("--outproj4", help = "Output projected coordinate system to draw flow arcs in, given as a Proj.4 string. Often available at spatialreference.org. Three input formats are acceptable: a Proj.4 string, a URL starting with 'http://' to the Proj.4 string for a coodinate system on spatialreference.org (e.g., http://spatialreference.org/ref/esri/53012/proj4/), or a full path to a plain text file containing (only) a Proj.4 string. Default output projection is Web Mercator (" + webMercatorRefURL + ").")
    parser.add_argument("--dev", help = "The fraction of the projected straight-line distance between start and end points of each arc at which a third, across-track deviated point should be established for cubic splines. Values must be between 0.0 and 1.0. Larger values make arcs more curved. Default is 0.15.")
    parser.add_argument("--vpa", help = "The number of vertices the mapped arcs should each have. Must be greater than 3, but should be at least several dozen to a couple hundred or so. Default is " + str(vertsPerArc) + ".")
    parser.add_argument("--rh", default = False, action = "store_true",  help = "Sets the across-track deviation point on the right-hand side instead of left. Changes the directions that arcs curve in.")
    parser.add_argument("-v", "--version", action = "version", version = "%(prog)s " + __version__)
    parser.add_argument("-l", "--license", action = LicenseAction, nargs = 0, help = "Print the script's license and exit.")
    #
    args = parser.parse_args()
    if args.vpa:
        vertsPerArc = args.vpa
    if args.outproj4:
        # specifiedSR = osr.SpatialReference()
        # wkt = None
        if args.outproj4.startswith("http://"):
            # URL
            f = request.urlopen(args.outproj4)
            # str(bytes_string,'utf-8')
            print(str(f.read(), "utf-8"))#.decode("utf-8"))
            # wkt = f.read().decode("utf-8") # decode from byte string.
            outP4 = stripUnitFlagFromProj4( str(f.read(), "utf-8") )#  f.read().decode("utf-8") # decode from byte string.
            print("Setting output SR from URL.")
        elif os.path.exists(args.outproj4):
            # Assuming a path to a text file has been passed in
            f = open(args.outproj4)
            # wkt = f.read()
            outP4 = stripUnitFlagFromProj4( f.read() )
            f.close()
        else:
            # Proj.4 string
            outP4 = stripUnitFlagFromProj4( args.outproj4 )
            # wkt = args.outwkt
        # specifiedSR.ImportFromWkt(wkt)
        # outSR = specifiedSR

    if args.dev:
        devFraction = float(args.dev)
    if args.rh:
        leftHanded = False

    # outboundTransform = osr.CoordinateTransformation(wgs84SR, outSR)
    # print("Outbound spatial reference is projected? " + str(outSR.IsProjected()))

    # Build the necessary coordinate systems for Proj.4, and the output prj file
    pIn = Proj(epsgWGS84Proj4)
    pOut = Proj(outP4)
    outSR = osr.SpatialReference()
    outSR.ImportFromProj4(outP4)

    # Create a shapefile where the user specified, and add attribute fields to it.
    print("Preparing shapefile for output...")
    outFileDir, outFilename = os.path.split(args.OUTSHPFILE)
    driver = ogr.GetDriverByName('ESRI Shapefile')
    outFile = os.path.join(outFileDir, outFilename)
    dst_ds = driver.CreateDataSource(outFile)
    fName = os.path.splitext(os.path.split(outFile)[1])[0]
    dst_layer = dst_ds.CreateLayer(fName, outSR, geom_type = ogr.wkbLineString)
    layer_defn = dst_layer.GetLayerDefn()
    for field in textFieldNames:
        createAField(dst_layer, field, ogr.OFTString)
    for field in floatFieldNames:
        createAField(dst_layer, field, ogr.OFTReal)

    # TODO: make script write any other attribute files to output, too?

    # Open and read the csv
    print("Reading csv...")
    with open(args.ROUTES) as csvfile:
        dReader = csv.DictReader(csvfile, delimiter = ',', quotechar = '"')
        # Can reference fields by their headers; first row taken for headers by default.
        # Get fieldnames from DictReader object and store in list
        # headers = dReader.fieldnames
        # Each row is an arc/arrow in the flow map. Process each row into a feature.

        # Find every unique origin point, and separate arcs into groups by origin point,
        # stored in a dictionary.
        originGroups = {} # Entries return lists of lists.
        originKeys = []

        for row in dReader: # populate originGroups

            # These strings are the headers (and fields) the input csv must have.
            oName  =  row["OrigName"]
            oLat   =  row["OrigLat"]
            oLon   =  row["OrigLon"]
            dName  =  row["DestName"]
            dLat   =  row["DestLat"]
            dLon   =  row["DestLon"]
            floMag =  row["FlowMag"]
            # odName =  oName + " to " + dName

            thisRecordStrings = [oName, oLat, oLon, dName, dLat, dLon, floMag]
            # print("this record is " + str(thisRecordStrings))
            thisOrigin = (float(thisRecordStrings[1]), float(thisRecordStrings[2]))
            if thisOrigin not in originGroups: # make new dictionary entry if new.
                originGroups[thisOrigin] = []
                originKeys.append(thisOrigin)
            # Whether new or not, append this record to the values of its key.
            originGroups[thisOrigin].append(thisRecordStrings)

        # print(str(originGroups))

        for ok in originKeys:
            theseArcs = originGroups[ok]
            for a in theseArcs:
                print("\nworking on arc from " + str(a[0]) + " to " + str(a[3]))
                originLatLon = ok # lat, lon
                destinLatLon = (float(a[4]), float(a[5])) # lat, lon
                print("originLatLon is at " + str(originLatLon))
                print("destinLatLon is at "+ str(destinLatLon))
                #
                # Convert these lat lon pairs to x,y in the outbound projected coordinate system, using pyproj.

                # build ogr points, transform them
                # pOrig = ogr.CreateGeometryFromWkt("POINT (" + str(originLatLon[0]) + " " + str(originLatLon[1]) + ")")
                # pDest = ogr.CreateGeometryFromWkt("POINT (" + str(destinLatLon[0]) + " " + str(destinLatLon[1]) + ")")
                # print("pOrig: " + str(pOrig))
                # pOrig = ogr.Geometry(ogr.wkbPoint)
                # pOrig.AddPoint(originLatLon[0], originLatLon[1])
                # pDest = ogr.Geometry(ogr.wkbPoint)
                # pDest.AddPoint(destinLatLon[0], destinLatLon[1])

                # Project the coordinates with Proj.4 via pyproj
                # see https://jswhit.github.io/pyproj/
                # xOrigIn, yOrigIn = pIn(originLatLon[1], originLatLon[0])
                # xDestIn, yDestIn = pIn(destinLatLon[1], destinLatLon[0])
                # xOrigOut, yOrigOut = pyproj.transform(pIn, pOut, xOrigIn, yOrigIn)
                # xDestOut, yDestOut = pyproj.transform(pIn, pOut, xDestIn, yDestIn)
                #
                xOrigOut, yOrigOut = pOut(originLatLon[1], originLatLon[0])
                xDestOut, yDestOut = pOut(destinLatLon[1], destinLatLon[0])

                # x_Orig, y_Orig, z_Orig = outboundTransform.TransformPoint(originLatLon[1], originLatLon[0]) # returns x then y then z
                # origMapVert = (x_Orig, y_Orig)
                # x_Dest, y_Dest, z_Dest = outboundTransform.TransformPoint(destinLatLon[1], destinLatLon[0]) # returns x then y then z
                # destMapVert = (x_Dest, y_Dest)
                # pOrig.Transform(outboundTransform)
                # pDest.Transform(outboundTransform)
                # origMapVertXYZ = pOrig.GetPoint() # returns x,y,z tuple
                # destMapVertXYZ = pOrig.GetPoint() # returns x,y,z tuple
                # origMapVert = (origMapVertXYZ[0], origMapVertXYZ[1])
                # destMapVert = (destMapVertXYZ[0], destMapVertXYZ[1])

                origMapVert = (xOrigOut, yOrigOut)
                destMapVert = (xDestOut, yDestOut)
                #
                print("Origin projected vertex x,y is      " + str(origMapVert))
                print("Destination projected vertex x,y is " + str(destMapVert))

                # Find the "dev" point for building building a cubic spline, using vector geometry.
                #
                # Straight-line route as a vector is second vertex minus first.
                routeVector = np.array([destMapVert[0], destMapVert[1]]) - np.array([origMapVert[0], origMapVert[1]])
                # The user-set fraction of the arc distance for point dev is...
                fractionVector = routeVector * devFraction
                # Get the left-handed orthogonal vector of this...
                orthogVector = calcOrthogonalVector(fractionVector, leftHanded)
                # dev point is at midpoint of the straight-line route, plus orthogVector
                aMidpoint = calcMidpointCoords(origMapVert, destMapVert)
                aMidpointVector = np.array([aMidpoint[0], aMidpoint[1]])
                devPointVector = aMidpointVector + orthogVector
                devMapVert = (devPointVector[0], devPointVector[1])
                print("dev projected vertex x,y is   " + str(devMapVert))
                # aDistance = calcPythagoreanDistance(origMapVert, destMapVert)
                # aSlope = calcSlope(origMapVert, destMapVert)
                # orthSlope = calcOrthogonalSlope(aSlope)

                # Now determine the cubic spline going through the origin,
                # the dev point, and the destination.
                # NB: for the scipy function we use, the x values must be a strictly monotonic, increasing series.
                # To handle all cases, we will rotate all points counterclockwise so that the origin and
                # destination y values are both 0. This will ensure the three x values are monotonic, increasing
                # in sequence.
                # The origin vertex obviously doesn't change, but the other two do.
                # Angle of rotation necessary is given in radians by math.atan2(y2-y1, x2-x1) .
                # Thanks to Jim Lewis: http://stackoverflow.com/questions/2676719/calculating-the-angle-between-the-line-defined-by-two-points
                # Rotated point on x axis of the destination vertex is (x = pO_pD_dist, y = 0),
                # and we use the above formula to find the necessary amount of rotation to
                # find our un-rotated dev point. Then simply rotate the destination
                # and dev points by that angle * 1.0.
                # destMapVert_R = (pO_pD_dist, 0.0)
                # necessaryRotation = math.atan2( destMapVert[1] - destMapVert_R[1] , destMapVert[0] - destMapVert_R[0] )
                # reverseRotation = math.degrees( necessaryRotation ) * -1.0
                # devMapVert_R_shapely = aff.rotate(pR, reverseRotation, origin = (0.0, 0.0), use_radians = False)
                # devMapVert_R = (devMapVert_R_shapely.x, devMapVert_R_shapely.y)

                # shift all points by vector of origMapVert, so origMapVert lies on the origin
                orgV = np.array([origMapVert[0], origMapVert[1]])
                devV = np.array([devMapVert[0], devMapVert[1]])
                desV = np.array([destMapVert[0], destMapVert[1]])
                orgV_shft = np.array([0.0, 0.0])
                devV_shft = devV - orgV
                desV_shft = desV - orgV
                devPt = Point(devV_shft[0], devV_shft[1]) # Shapely Point object
                desPt = Point(desV_shft[0], desV_shft[1]) # Shapely Point object
                # determine angle necessary to rotate desV_shft so it lies on the x axis.
                theta_desV_shift = math.atan2( desV_shft[1] , desV_shft[0] ) # returned in radians
                angleToRotateBy = -1.0 * theta_desV_shift
                # rotate both the dev point and the destination point by this angle
                orgV_shft_rot = orgV_shft # unchanged
                devV_shft_rot = aff.rotate(devPt, angleToRotateBy, origin = (0.0, 0.0), use_radians = True)
                desV_shft_rot = aff.rotate(desPt, angleToRotateBy, origin = (0.0, 0.0), use_radians = True)
                # restate each point as a simple tuple
                orgV_shft_rot_tuple = (0.0, 0.0)
                devV_shft_rot_tuple = (devV_shft_rot.x, devV_shft_rot.y)
                desV_shft_rot_tuple = (desV_shft_rot.x, desV_shft_rot.y)
                # We've got the three necessary vertices to construct the cubic spline, now in strictly increasing x order.
                csplineVerts = [orgV_shft_rot_tuple, devV_shft_rot_tuple, desV_shft_rot_tuple]

                if not strictly_increasing([ orgV_shft_rot_tuple[0], devV_shft_rot_tuple[0], desV_shft_rot_tuple[0] ]):
                    print("not strictly increasing!") # just a sanity check...

                # The cubic spline!
                series_x = [i[0] for i in csplineVerts]
                series_y = [i[1] for i in csplineVerts]
                thisSpline = CubicSpline(series_x, series_y)
                # Determine how many vertices each arc should have, using vertsPerArc,
                # over the range defined by the destination x - the origin x.
                xRange = series_x[2] - series_x[0]
                anInterval = xRange / vertsPerArc
                xValues = np.arange(series_x[0], series_x[2], anInterval)
                # NB: this leaves the dev point behind! We should have many others near it though, or it could be inserted into the sequence here.
                # Add final (rotated and translated) destination x value to xValues
                np.append(xValues, desV_shft_rot_tuple[0])
                # Evaluate interpolants by thisSpline([xValues]), store vertices as tuples (x,y)
                yValues = thisSpline(xValues)
                # Build list of verts with origin at beginning, then interpolated ones, then destination.
                vertsInterpolated = [ (x,y) for x,y in zip(xValues, yValues) ]

                # Now rotate these points back...
                rerotatedPoints = []
                for vi in vertsInterpolated:
                    aVert = Point(vi[0], vi[1]) # Shapely Point object
                    aRerotatedPoint = aff.rotate(aVert, theta_desV_shift, origin = (0.0, 0.0), use_radians = True)
                    rerotatedPoints.append(aRerotatedPoint)

                # ...and now shift (translate) the rerotated points back to projected map coordinates.
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
                # anArc.Destroy() # free resources
                anArc = None

    # dst_ds.Destroy()  # Destroy the data source to free resouces and finish writing.
    dst_ds = None

    print("\nFinished! Output written to: " + outFile)


# Main module check /////////////////////////////////////////////////////////////////////

if __name__ == '__main__':
    main()

# fin
# exit()
