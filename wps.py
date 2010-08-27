#!/usr/bin/env python
#-*- coding: utf-8 -*-
"""
This program is simple implementation of OGC's [http://opengeospatial.org]
Web Processing Service (OpenGIS(r) Web Processing Service - OGC 05-007r7)
version 1.0.0 from 2007-06-08

Target of this application is to bring functionality of GIS GRASS
[http://grass.itc.it] to the World Wide Web - it should work like
wrapper for modules of this GIS. Though GRASS was at the first place in the
focus, it is not necessary to use it's modules - you can use any program
you can script in Python or other language.

The first version was written with support of Deutsche Bundesstiftung
Umwelt, Osnabrueck, Germany on the spring 2006. SVN server is hosted by
GDF-Hannover, Hannover, Germany.

Current development is supported mainly by:
Help Service - Remote Sensing s.r.o
Cernoleska 1600
256  01 - Benesov u Prahy
Czech Republic
Europe

For setting see comments in 'etc' directory and documentation.

This program is free software, distributed under the terms of GNU General
Public License as published by the Free Software Foundation version 2 of the
License.

Enjoy and happy GISing!

$Id: wps.py 871 2009-11-23 14:25:09Z jachym $
"""
__version__ = "3.0-svn"


# Author:    Jachym Cepicky
#            http://les-ejk.cz
# License:
#
# Web Processing Service implementation
# Copyright (C) 2006 Jachym Cepicky
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA

#import pycallgraph
#filter_func = pycallgraph.GlobbingFilter(max_depth=4)
#pycallgraph.start_trace(filter_func=filter_func)
#import sys,os, traceback
#sys.path.append("/users/rsg/jmdj/workspace/pywps-3.2-soap/pywps")
#os.environ["PYWPS_CFG"]="/etc/pywps.cfg"
#sys.path.append("/users/rsg/jmdj/.eclipse/793567567/plugins/org.python.pydev.debug_1.6.0.2010071813/pysrc/")
#import pydevd   

import pywps
from pywps.Exceptions import *
#import logging

# get the request method and inputs

method = os.getenv("REQUEST_METHOD")



if not method:  # set standard method
    method = pywps.METHOD_GET

inputQuery = None
if method == pywps.METHOD_GET:
    try:
        inputQuery = os.environ["QUERY_STRING"]
    except KeyError:
        # if QUERY_STRING isn't found in env-dictionary, try to read
        # query from command line:
        if len(sys.argv)>1:  # any arguments available?
            inputQuery = sys.argv[1]
    if not inputQuery:
        err =  NoApplicableCode("No query string found.")
        pywps.response.response(err,sys.stdout)
        sys.exit(1)
else:
    inputQuery = sys.stdin

 




try:
    wps = pywps.Pywps(method)
   
     
   
    if wps.parseRequest(inputQuery):
        #pywps.debug(wps.inputs)
        response = wps.performRequest()

        # request performed, write the response back
        if response:
            # print only to standard out
          
            #pydevd.settrace() 
            pywps.response.response(wps.response,
                    sys.stdout,wps.parser.soapVersion,wps.parser.isSoap,
                    wps.request.contentType)
            
            #pywps.response.response(wps.response,
             #       sys.stdout,wps.parser.soapVersion,wps.parser.isSoap,
              #      wps.request.contentType)
except WPSException,e:
    #traceback.print_exc(file=pywps.logFile)
    pywps.response.response(e, sys.stdout, wps.parser.isSoap)

#pycallgraph.make_dot_graph('/users/rsg/jmdj/pywps_Exception.png')
