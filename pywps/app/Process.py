##################################################################
# Copyright 2018 Open Source Geospatial Foundation and others    #
# licensed under MIT, Please consult LICENSE.txt for details     #
##################################################################

import logging
import os
from pywps.translations import lower_case_dict
import sys
import traceback
import json
import shutil

from pywps import dblog
from pywps.response import get_response
from pywps.response.status import WPS_STATUS
from pywps.response.execute import ExecuteResponse
from pywps.app.WPSRequest import WPSRequest
from pywps.inout.inputs import input_from_json
from pywps.inout.outputs import output_from_json
import pywps.configuration as config
from pywps.exceptions import (StorageNotSupported, OperationNotSupported,
                              ServerBusy, NoApplicableCode,
                              InvalidParameterValue)
from pywps.app.exceptions import ProcessError
from pywps.inout.storage.builder import StorageBuilder
from pywps.inout.outputs import ComplexOutput
import importlib


LOGGER = logging.getLogger("PYWPS")


class Process(object):
    """
    :param handler: A callable that gets invoked for each incoming
                    request. It should accept a single
                    :class:`pywps.app.WPSRequest` argument and return a
                    :class:`pywps.app.WPSResponse` object.
    :param string identifier: Name of this process.
    :param string title: Human readable title of process.
    :param string abstract: Brief narrative description of the process.
    :param list keywords: Keywords that characterize a process.
    :param inputs: List of inputs accepted by this process. They
                   should be :class:`~LiteralInput` and :class:`~ComplexInput`
                   and :class:`~BoundingBoxInput`
                   objects.
    :param outputs: List of outputs returned by this process. They
                   should be :class:`~LiteralOutput` and :class:`~ComplexOutput`
                   and :class:`~BoundingBoxOutput`
                   objects.
    :param metadata: List of metadata advertised by this process. They
                     should be :class:`pywps.app.Common.Metadata` objects.
    :param dict[str,dict[str,str]] translations: The first key is the RFC 4646 language code,
        and the nested mapping contains translated strings accessible by a string property.
        e.g. {"fr-CA": {"title": "Mon titre", "abstract": "Une description"}}
    """

    def __init__(self, handler, identifier, title, abstract='', keywords=[], profile=[],
                 metadata=[], inputs=[], outputs=[], version='None', store_supported=False,
                 status_supported=False, grass_location=None, translations=None):
        self.identifier = identifier
        self.handler = handler
        self.title = title
        self.abstract = abstract
        self.keywords = keywords
        self.metadata = metadata
        self.profile = profile
        self.version = version
        self.inputs = inputs
        self.outputs = outputs
        self.uuid = None
        self._status_store = None
        # self.status_location = ''
        # self.status_url = ''
        self.workdir = None
        self._grass_mapset = None
        self.grass_location = grass_location
        self.service = None
        self.translations = lower_case_dict(translations)

        if store_supported:
            self.store_supported = 'true'
        else:
            self.store_supported = 'false'

        if status_supported:
            self.status_supported = 'true'
        else:
            self.status_supported = 'false'

    @property
    def json(self):

        return {
            'class': '{}:{}'.format(self.__module__, self.__class__.__name__),
            'uuid': str(self.uuid),
            'workdir': self.workdir,
            'version': self.version,
            'identifier': self.identifier,
            'title': self.title,
            'abstract': self.abstract,
            'keywords': self.keywords,
            'metadata': [m.json for m in self.metadata],
            'inputs': [i.json for i in self.inputs],
            'outputs': [o.json for o in self.outputs],
            'store_supported': self.store_supported,
            'status_supported': self.status_supported,
            'profile': [p for p in self.profile],
            'translations': self.translations,
        }

    @classmethod
    def from_json(cls, value):
        """init this process from json back again

        :param value: the json (not string) representation
        """
        module, classname = value['class'].split(':')
        # instantiate subclass of Process
        new_process = getattr(importlib.import_module(module), classname)()
        new_process._set_uuid(value['uuid'])
        new_process.set_workdir(value['workdir'])
        return new_process

    def execute(self, wps_request, uuid):
        self._set_uuid(uuid)
        self._setup_status_storage()
        self.async_ = False
        response_cls = get_response("execute")
        wps_response = response_cls(wps_request, process=self, uuid=self.uuid)

        LOGGER.debug('Check if status storage and updating are supported by this process')
        if wps_request.store_execute == 'true':
            if self.store_supported != 'true':
                raise StorageNotSupported('Process does not support the storing of the execute response')

            if wps_request.status == 'true':
                if self.status_supported != 'true':
                    raise OperationNotSupported('Process does not support the updating of status')

                wps_response.store_status_file = True
                self.async_ = True
            else:
                wps_response.store_status_file = False

        LOGGER.debug('Check if updating of status is not required then no need to spawn a process')

        wps_response = self._execute_process(self.async_, wps_request, wps_response)

        return wps_response

    def _set_uuid(self, uuid):
        """Set uuid and status location path and url
        """

        self.uuid = uuid
        for inpt in self.inputs:
            inpt.uuid = uuid

        for outpt in self.outputs:
            outpt.uuid = uuid

    def _setup_status_storage(self):
        self._status_store = StorageBuilder.buildStorage()

    @property
    def status_store(self):
        if self._status_store is None:
            self._setup_status_storage()
        return self._status_store

    @property
    def status_location(self):
        return self.status_store.location(self.status_filename)

    @property
    def status_filename(self):
        return str(self.uuid) + '.xml'

    @property
    def status_url(self):
        return self.status_store.url(self.status_filename)

    def _execute_process(self, async_, wps_request, wps_response):
        """Uses :module:`pywps.processing` module for sending process to
        background BUT first, check for maxprocesses configuration value

        :param async_: run in asynchronous mode
        :return: wps_response or None
        """

        maxparallel = int(config.get_config_value('server', 'parallelprocesses'))

        running, stored = dblog.get_process_counts()

        # async
        if async_:

            # run immedietly
            LOGGER.debug("Running processes: {} of {} allowed parallelprocesses".format(running, maxparallel))
            LOGGER.debug("Stored processes: {}".format(stored))

            if running < maxparallel or maxparallel == -1:
                wps_response._update_status(WPS_STATUS.ACCEPTED, "PyWPS Request accepted", 0)
                LOGGER.debug("Accepted request {}".format(self.uuid))
                self._run_async(wps_request, wps_response)

            # try to store for later usage
            else:
                maxprocesses = int(config.get_config_value('server', 'maxprocesses'))
                if stored >= maxprocesses and maxprocesses != -1:
                    raise ServerBusy('Maximum number of processes in queue reached. Please try later.')
                LOGGER.debug("Store process in job queue, uuid={}".format(self.uuid))
                dblog.store_process(self.uuid, wps_request)
                wps_response._update_status(WPS_STATUS.ACCEPTED, 'PyWPS Process stored in job queue', 0)

        # not async
        else:
            if running >= maxparallel and maxparallel != -1:
                raise ServerBusy('Maximum number of parallel running processes reached. Please try later.')
            wps_response._update_status(WPS_STATUS.ACCEPTED, "PyWPS Request accepted", 0)
            wps_response = self._run_process(wps_request, wps_response)

        return wps_response

    # This function may not raise exception and must return a valid wps_response
    # Failure must be reported as wps_response.status = WPS_STATUS.FAILED
    def _run_async(self, wps_request, wps_response):
        import pywps.processing
        process = pywps.processing.Process(
            process=self,
            wps_request=wps_request,
            wps_response=wps_response)
        LOGGER.debug("Starting process for request: {}".format(self.uuid))
        process.start()

    # This function may not raise exception and must return a valid wps_response
    # Failure must be reported as wps_response.status = WPS_STATUS.FAILED
    def _run_process(self, wps_request, wps_response):
        LOGGER.debug("Started processing request: {}".format(self.uuid))
        try:
            self._set_grass(wps_request)
            # if required set HOME to the current working directory.
            if config.get_config_value('server', 'sethomedir') is True:
                os.environ['HOME'] = self.workdir
                LOGGER.info('Setting HOME to current working directory: {}'.format(os.environ['HOME']))
            LOGGER.debug('ProcessID={}, HOME={}'.format(self.uuid, os.environ.get('HOME')))
            wps_response._update_status(WPS_STATUS.STARTED, 'PyWPS Process started', 0)
            self.handler(wps_request, wps_response)  # the user must update the wps_response.
            # Ensure process termination
            if wps_response.status != WPS_STATUS.SUCCEEDED and wps_response.status != WPS_STATUS.FAILED:
                # if (not wps_response.status_percentage) or (wps_response.status_percentage != 100):
                LOGGER.debug('Updating process status to 100% if everything went correctly')
                wps_response._update_status(WPS_STATUS.SUCCEEDED, f'PyWPS Process {self.title} finished', 100)
        except Exception as e:
            traceback.print_exc()
            LOGGER.debug('Retrieving file and line number where exception occurred')
            exc_type, exc_obj, exc_tb = sys.exc_info()
            found = False
            while not found:
                # search for the _handler method
                m_name = exc_tb.tb_frame.f_code.co_name
                if m_name == '_handler':
                    found = True
                else:
                    if exc_tb.tb_next is not None:
                        exc_tb = exc_tb.tb_next
                    else:
                        # if not found then take the first
                        exc_tb = sys.exc_info()[2]
                        break
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            method_name = exc_tb.tb_frame.f_code.co_name

            # update the process status to display process failed

            msg = 'Process error: method={}.{}, line={}, msg={}'.format(fname, method_name, exc_tb.tb_lineno, e)
            LOGGER.error(msg)
            # In case of a ProcessError use the validated exception message.
            if isinstance(e, ProcessError):
                msg = "Process error: {}".format(e)
            # Only in debug mode we use the log message including the traceback ...
            elif config.get_config_value("logging", "level") != "DEBUG":
                # ... otherwise we use a sparse common error message.
                msg = 'Process failed, please check server error log'
            wps_response._update_status(WPS_STATUS.FAILED, msg, 100)

        finally:
            # The run of the next pending request if finished here, weather or not it successfull
            self.launch_next_process()

        return wps_response

    def launch_next_process(self):
        """Look at the queue of async process, if the queue is not empty launch the next pending request.
        """
        try:
            LOGGER.debug("Checking for stored requests")

            stored_request = dblog.pop_first_stored()
            if not stored_request:
                LOGGER.debug("No stored request found")
                return

            (uuid, request_json) = (stored_request.uuid, stored_request.request)
            request_json = request_json.decode('utf-8')
            LOGGER.debug("Launching the stored request {}".format(str(uuid)))
            new_wps_request = WPSRequest()
            new_wps_request.json = json.loads(request_json)
            process_identifier = new_wps_request.identifier
            process = self.service.prepare_process_for_execution(process_identifier)
            process._set_uuid(uuid)
            process._setup_status_storage()
            process.async_ = True
            process.setup_outputs_from_wps_request(new_wps_request)
            new_wps_response = ExecuteResponse(new_wps_request, process=process, uuid=uuid)
            new_wps_response.store_status_file = True
            process._run_async(new_wps_request, new_wps_response)
        except Exception as e:
            LOGGER.exception("Could not run stored process. {}".format(e))

    def clean(self):
        """Clean the process working dir and other temporary files
        """
        if config.get_config_value('server', 'cleantempdir'):
            LOGGER.info("Removing temporary working directory: {}".format(self.workdir))
            try:
                if os.path.isdir(self.workdir):
                    shutil.rmtree(self.workdir)
                if self._grass_mapset and os.path.isdir(self._grass_mapset):
                    LOGGER.info("Removing temporary GRASS GIS mapset: {}".format(self._grass_mapset))
                    shutil.rmtree(self._grass_mapset)
            except Exception as err:
                LOGGER.error('Unable to remove directory: {}'.format(err))
        else:
            LOGGER.warning('Temporary working directory is not removed: {}'.format(self.workdir))

    def set_workdir(self, workdir):
        """Set working dir for all inputs and outputs

        this is the directory, where all the data are being stored to
        """

        self.workdir = workdir
        for inpt in self.inputs:
            inpt.workdir = workdir

        for outpt in self.outputs:
            outpt.workdir = workdir

    def _set_grass(self, wps_request):
        """Handle given grass_location parameter of the constructor

        location is either directory name, 'epsg:1234' form or a georeferenced
        file

        in the first case, new temporary mapset within the location will be
        created

        in the second case, location will be created in self.workdir

        the mapset should be deleted automatically using self.clean() method
        """
        if self.grass_location:

            import random
            import string
            from grass.script import core as grass
            from grass.script import setup as gsetup

            # HOME needs to be set - and that is usually not the case for httpd
            # server
            os.environ['HOME'] = self.workdir

            # GISRC envvariable needs to be set
            gisrc = open(os.path.join(self.workdir, 'GISRC'), 'w')
            gisrc.write("GISDBASE: {}\n".format(self.workdir))
            gisrc.write("GUI: txt\n")
            gisrc.close()
            os.environ['GISRC'] = gisrc.name

            new_loc_args = dict()
            mapset_name = 'pywps_ms_{}'.format(
                ''.join(random.sample(string.ascii_letters, 5)))

            if self.grass_location.startswith('complexinput:'):
                # create new location from a georeferenced file
                ref_file_parameter = self.grass_location.split(':')[1]
                ref_file = wps_request.inputs[ref_file_parameter][0].file
                new_loc_args.update({'filename': ref_file})
            elif self.grass_location.lower().startswith('epsg:'):
                # create new location from epsg code
                epsg = self.grass_location.lower().replace('epsg:', '')
                new_loc_args.update({'epsg': epsg})

            if new_loc_args:
                dbase = self.workdir
                location = str()
                while os.path.isdir(os.path.join(dbase, location)):
                    location = 'pywps_loc_{}'.format(
                        ''.join(random.sample(string.ascii_letters, 5)))

                gsetup.init(os.environ['GISBASE'], dbase,
                            location, 'PERMANENT')

                grass.create_location(dbase=dbase,
                                      location=location,
                                      **new_loc_args)
                LOGGER.debug('GRASS location based on {} created'.format(
                    list(new_loc_args.keys())[0]))
                grass.run_command('g.mapset',
                                  mapset=mapset_name,
                                  flags='c',
                                  dbase=dbase,
                                  location=location,
                                  quiet=True)

            # create temporary mapset within existing location
            elif os.path.isdir(self.grass_location):
                from grass.pygrass.gis import make_mapset

                LOGGER.debug('Temporary mapset will be created')

                dbase = os.path.dirname(self.grass_location)
                location = os.path.basename(self.grass_location)

                grass.run_command('g.gisenv', set="GISDBASE={}".format(dbase))
                grass.run_command('g.gisenv', set="LOCATION_NAME=%s" % location)

                while os.path.isdir(os.path.join(dbase, location, mapset_name)):
                    mapset_name = 'pywps_ms_{}'.format(
                        ''.join(random.sample(string.ascii_letters, 5)))
                make_mapset(mapset=mapset_name, location=location,
                            gisdbase=dbase)
                grass.run_command('g.gisenv', set="MAPSET=%s" % mapset_name)

            else:
                raise NoApplicableCode('Location does exists or does not seem '
                                       'to be in "EPSG:XXXX" form nor is it existing directory: {}'.format(location))

            # set _grass_mapset attribute - will be deleted once handler ends
            self._grass_mapset = mapset_name

            # final initialization
            LOGGER.debug('GRASS Mapset set to {}'.format(mapset_name))

            LOGGER.debug('GRASS environment initialised')
            LOGGER.debug('GISRC {}, GISBASE {}, GISDBASE {}, LOCATION {}, MAPSET {}'.format(
                         os.environ.get('GISRC'), os.environ.get('GISBASE'),
                         dbase, location, os.path.basename(mapset_name)))

    def setup_outputs_from_wps_request(self, wps_request):
        # set as_reference to True for all the outputs specified as reference
        # if the output is not required to be raw
        if not wps_request.raw:
            for wps_outpt in wps_request.outputs:

                is_reference = wps_request.outputs[wps_outpt].get('asReference', 'false')
                mimetype = wps_request.outputs[wps_outpt].get('mimetype', '')
                if is_reference.lower() == 'true':
                    # check if store is supported
                    if self.store_supported == 'false':
                        raise StorageNotSupported(
                            'The storage of data is not supported for this process.')

                    is_reference = True
                else:
                    is_reference = False

                for outpt in self.outputs:
                    if outpt.identifier == wps_outpt:
                        outpt.as_reference = is_reference
                        if isinstance(outpt, ComplexOutput) and mimetype != '':
                            data_format = [f for f in outpt.supported_formats if f.mime_type == mimetype]
                            if len(data_format) == 0:
                                raise InvalidParameterValue(
                                    'MimeType ' + mimetype + ' not valid')
                            outpt.data_format = data_format[0]
