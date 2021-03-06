"""
Script to find and process datafiles generated by process_userstates.py

Usage:
python process_userstates_datafiles.py path/to/datadir
"""
from __future__ import with_statement

import logging
import optparse
import os
import re
import signal
import sys
import time

import sqlalchemy as sa

from paste.deploy import converters

from lolapps.util import processor

_player_pattern = re.compile(r'^user_state-modified-\d+-\d+\.\d+\.\d+\.player$')

sleep_time = 0
file_dirs = ['.']
dane_connection = None
rebalancing = False

log = processor.configure_logging()

last_out = 0

def run_once():
    start_time = time.time()
    processed_file = False
    log.debug("checking for files")
    global last_out
    if last_out < time.time() - 60:
        last_out = time.time()
        log.info("blip")
    found_file = True
    while found_file:
        found_file = False
        for file_dir in file_dirs:
            if rebalancing:
                player_filename = find_file(file_dir, _player_pattern)
                if player_filename:
                    delete_player_file(file_dir, player_filename)
                    found_file = True
            else:
                player_filename = find_file(file_dir, _player_pattern)
                if player_filename:
                    process_player_file(file_dir, player_filename)
                    processed_file = True
                    found_file = True

    if processed_file:
        proc_time = time.time() - start_time
        log.info("%s seconds to process all files" % proc_time)


def process_player_file(file_dir, filename):
    """
    Process a single player file.
    Each line is a paren-surrounded list of values.
    We read in the file and then do a batch insert-update.
    """
    full_filename = os.path.join(file_dir, filename)
    start_time = time.time()
    log.info("processing player file %s" % full_filename)
    
    # run the command
    try:
        sql = (r"LOAD DATA LOCAL INFILE '%s' INTO TABLE player_audit_trail4 "
            r"FIELDS TERMINATED BY ', ' OPTIONALLY ENCLOSED BY '''' ESCAPED BY '\\' "
            r"LINES STARTING BY '(' TERMINATED BY ')\n' "
            r"(user_id, app_id, tutorial_step, level, xp, last_visit, timestamp);" % full_filename)
        dane_connection.execute(sql)

        proc_time = time.time() - start_time
        log.info("%s seconds to process player file" % proc_time)
    except Exception, e:
        log.exception(e)
        # save bad files for later
        os.rename(full_filename, full_filename+".bad")
    else:
        # it succeeded - remove the file
        os.unlink(full_filename)


def delete_player_file(file_dir, filename):
    full_filename = os.path.join(file_dir, filename)
    log.info("deleting player file %s" % full_filename)
    os.unlink(full_filename)


def find_file(file_dir, pattern):
    files = os.listdir(file_dir)
    for file in sorted(files):
        if pattern.match(file):
            return file
    return None


def print_usage():
    print "usage: python process_userstates_datafiles.py path/to/datadir"
    sys.exit(1)

def configure():
    global file_dirs, dane_connection, sleep_time, rebalancing, game

    parser = optparse.OptionParser()
    parser.add_option("-s", "--sleep", dest="sleep", default="5", 
                      help="time to sleep between file searches")
    parser.add_option("-d", "--shard", dest="shard", default="-1", help="shard to process")
    parser.add_option("-i", "--ini", dest="ini", help="uuss ini file")
    parser.add_option("-r", "--rebal", dest="rebal", action="store_true", default=False, 
                      help="rebalancing node")
    parser.add_option("-g", "--game", dest="game", help="game to process (dane, india)")
    options, args = parser.parse_args()

    sleep_time = int(options.sleep)

    game = options.game
    if game is None:
        print "game option is required"
        sys.exit(1)

    ini_file = options.ini
    if ini_file is None:
        print "ini option is required"
        sys.exit(1)

    shard = int(options.shard)

    from uuss.server import configuration
    (full_config, config) = configuration.init_from_ini(ini_file, [game], {'uuss.use_gevent': False})

    if shard >= 0:
        file_dirs = [ config["%s_user_state.tmp_dir%s" % (shard, game)] ]
    else:
        shard_count = len(config["%s_user_state.mongo_hosts" % game].split(';'))
        file_dirs = [config["%s_user_state.tmp_dir%s" % (game, shard_index)] for shard_index in range(shard_count)]
    rebalancing = converters.asbool(config["sqlalchemy.%s_userstate.rebalancing" % game]) and options.rebal

    dane_write = config['sqlalchemy.%s.url' % game]
    dane_connection = sa.create_engine(dane_write).connect()


def main():
    configure()

    import gc
    log.info("GC collected %r objects", gc.collect())
    
    while(True):
        try:
            run_once()
        except Exception, e:
            log.exception(e)
        time.sleep(sleep_time)

    #processor.register_signal_handlers()
    #processor.start_log_processor(run_once, 1)


if __name__ == '__main__':
    # TODO signal handlers
    main()
