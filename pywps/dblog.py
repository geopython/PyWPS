"""
Implementation of logging for PyWPS-4
"""

import logging
from pywps import configuration
from pywps.exceptions import NoApplicableCode
import sqlite3
import datetime
import pickle
import json
import os


import psycopg2 as postgresql

LOGGER = logging.getLogger(__name__)
_CONNECTION = None

def log_request(uuid, request):
    """Write OGC WPS request (only the necessary parts) to database logging
    system
    """

    conn = get_connection()
    insert = """
        INSERT INTO
            pywps_requests (uuid, pid, operation, version, time_start, identifier)
        VALUES
            ('{uuid}', {pid}, '{operation}', '{version}', '{time_start}', '{identifier}');
    """.format(
        uuid=uuid,
        pid=os.getpid(),
        operation=request.operation,
        version=request.version,
        time_start=datetime.datetime.now().isoformat(),
        identifier=_get_identifier(request)
    )
    LOGGER.debug(insert)

    cur = conn.cursor()
    cur.execute(insert, (str(uuid), pid, operation, version, time_start, identifier))
    conn.commit()
    

def get_running():
    """Returns running processes ids
    """

    conn = get_connection()
    cur = conn.cursor()

    cur.execute('SELECT uuid FROM pywps_requests WHERE percent_done < 100;')

    return cur.fetchall()


def get_stored():
    """Returns running processes ids
    """

    conn = get_connection()
    cur = conn.cursor()

    cur.execute('SELECT uuid FROM pywps_stored_requests;')

    return cur.fetchall()

def get_first_stored():
    """Returns running processes ids
    """

    conn = get_connection()
    cur = conn.cursor()

    cur.execute('SELECT uuid,  request FROM pywps_stored_requests LIMIT 1;')

    return cur.fetchall()



def update_response(uuid, response, close=False):
    """Writes response to database
    """

    conn = get_connection()
    message = 'Null'
    status_percentage = 'Null'
    status = 'Null'

    if hasattr(response, 'message'):
        message = response.message
    if hasattr(response, 'status_percentage'):
        status_percentage = response.status_percentage
    if hasattr(response, 'status'):
        status = response.status

    update = """
        UPDATE
            pywps_requests
        SET
            pid = '{pid}',
            time_end = '{time_end}', message={message},
            percent_done = {percent_done}, status={status}
        WHERE
            uuid = '{uuid}';
    """.format(
        time_end=datetime.datetime.now().isoformat(),
        pid=os.getpid(),
        message=message,
        percent_done=status_percentage,
        status=status,
        uuid=uuid
    )
    LOGGER.debug(update)

    cur = conn.cursor()
    cur.execute(update, (pid, time_end, message, status_percentage, status, str(uuid)))
    conn.commit()


def _get_identifier(request):
    """Get operation identifier
    """

    if request.operation == 'execute':
        return request.identifier
    elif request.operation == 'describeprocess':
        if request.identifiers:
            return ','.join(request.identifiers)
        else:
            return 'Null'
    else:
        return 'NULL'

def get_connection():
    """Get Connection for database
    """


    LOGGER.debug('Initializing database connection')
    global _CONNECTION

    if _CONNECTION:
        return _CONNECTION

    #database = configuration.get_config_value('server', 'logdatabase')

    #if not database:
    #    database = 'file:memdb1?mode=memory&cache=shared'

    #print(database)

    #connection = sqlite3.connect(database)
    _CONNECTION = postgresql.connect("dbname= 'pywps' user='janrudolf' password='1Straskov-Vodochody12'")
    
    #if check_db_table(connection):
    #    if check_db_columns(connection):
    #        _CONNECTION = connection
     #   else:
     #       raise NoApplicableCode("""
     #           Columns in the table 'pywps_requests' or 'pywps_stored_requests' in database '%s' are in
    #            conflict
    #        """ % database)

    #else:
    #    _CONNECTION = sqlite3.connect(database, check_same_thread=False)
    #    print("vytvarim novou")
   #     cursor = _CONNECTION.cursor()
    #    createsql = """
    #        CREATE TABLE pywps_requests(
   #             uuid VARCHAR(255) not null primary key,
   #             pid INTEGER not null,
   #             operation varchar(30) not null,
   #             version varchar(5) not null,
   #             time_start text not null,
   #             time_end text,
   #             identifier text,
   #             message text,
   #             percent_done float,
   #             status varchar(30)
   #         );
   #     """
   #     cursor.execute(createsql)

    #    createsql = """
    #        CREATE TABLE pywps_stored_requests(
    #            uuid VARCHAR(255) not null primary key,
    #            request BLOB not null
    #        );
    #        """
    #    cursor.execute(createsql)
    #    _CONNECTION.commit()

    return _CONNECTION

def check_db_table(connection):
    """Check for existing pywps_requests table in the datase

    :return: boolean pywps_requests table is in database
    """

    cursor = connection.cursor()
    cursor.execute("""
        SELECT
            name
        FROM
            sqlite_master
        WHERE
            name='pywps_requests';
    """)
    table = cursor.fetchone()
    if table:
        LOGGER.debug('pywps_requests table exists')
        return True
    else:
        LOGGER.debug('pywps_requests table does not exist')
        return False


def check_db_columns(connection):
    """Simple check for existing columns in given database

    we will make just simple check, this is not django

    :return: all needed columns found
    :rtype: boolean
    """

    def _check_table(name, needed_columns):
        cur = connection.cursor()
        cur.execute("""PRAGMA table_info('%s')""" % name)
        metas = cur.fetchall()
        columns = []
        for column in metas:
            columns.append(column[1])

        needed_columns.sort()
        columns.sort()

        if columns == needed_columns:
            return True
        else:
            return False

    name = 'pywps_requests'
    needed_columns = ['uuid', 'pid', 'operation', 'version', 'time_start',
                      'time_end', 'identifier', 'message', 'percent_done',
                      'status']

    pywps_requests = _check_table(name, needed_columns)
    pywps_stored_requests = _check_table('pywps_stored_requests', ['uuid', 'request'])


    return pywps_requests and pywps_stored_requests

def close_connection():
    """close connection"""
    LOGGER.debug('Closing DB connection')
    global _CONNECTION
    if _CONNECTION:
        _CONNECTION.close()
    _CONNECTION = None

def store_process(uuid, request):
    """Save given request under given UUID for later usage
    """

    conn = get_connection()
    insert = """
        INSERT INTO
            pywps_stored_requests (uuid, request)
        VALUES
            ('{uuid}', '{request}');
    """.format(
        uuid=uuid,
        request=request.json
    )

    cur = conn.cursor()
    cur.execute(insert, (str(uuid), request.json))
    conn.commit()
    

def remove_stored(uuid):
    """Remove given request from stored requests
    """

    conn = get_connection()
    insert = """
        DELETE FROM
            pywps_stored_requests
        WHERE uuid = '{uuid}';
    """.format(
        uuid=uuid
    )

    cur = conn.cursor()
    cur.execute(insert, (str(uuid)))
    conn.commit()

