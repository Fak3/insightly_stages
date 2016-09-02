#!/usr/bin/env python
# -*- coding: UTF-8 -*-

from __future__ import print_function

import json
import logging
import logging.config
import os
import re

from datetime import datetime
from os.path import abspath, dirname, exists, join
from shutil import copyfile
from textwrap import dedent

import requests

if not exists('insightly_stages_config.py'):
    print(u'*** Creating default config file insightly_stages_config.py')
    copyfile('insightly_stages_config.py.example', 'insightly_stages_config.py')

import insightly_stages_config as config


def insightly_get_all(url, auth):
    """ Send GET request. Raise exception if response status code is not 200. """
    results = []
    skip = 0
    while True:
        response = requests.get('https://api.insight.ly/v2.2%s&skip=%d&count_total=true' % (url, skip), auth=auth)
        if response.status_code != 200:
            err = Exception('Insightly api GET error: Http status %s. Url:\n%s' % (response.status_code, url))
            logging.critical(err)
            raise err
        results += json.loads(response.content)
        if len(results) >= int(response.headers['X-Total-Count']):
            break
        skip += len(results)
    return results


def insightly_get(url, auth):
    """ Send GET request. Raise exception if response status code is not 200. """
    response = requests.get('https://api.insight.ly/v2.2' + url, auth=auth)
    if response.status_code != 200:
        err = Exception('Insightly api GET error: Http status %s. Url:\n%s' % (response.status_code, url))
        logging.critical(err)
        raise err
    return json.loads(response.content)


def insightly_put(url, auth, **kwargs):
    """ Send PUT request. Raise exception if response status code is not 200. """
    response = requests.put("https://api.insight.ly/v2.2" + url, auth=auth, **kwargs)
    if response.status_code != 200:
        err = Exception('Insightly api PUT error: Http status %s. Url:\n%s' % (response.status_code, url))
        logging.critical(err)
        raise err
    return json.loads(response.content)


def configure():
    """
    Apply configuration from config.py
    """

    if hasattr(config, 'LOG_FILE'):
        LOG_FILE = abspath(config.LOG_FILE)
        print('Log messages will be sent to %s' % LOG_FILE)
    else:
        LOG_FILE = '/var/log/insightly_stages.log'
        print('Log messages will be sent to %s. You can change LOG_FILE in the config.' % LOG_FILE)

    # Test write permissions in the log file directory.
    permissons_test_path = join(dirname(LOG_FILE), 'insightly_test.log')
    try:
        with open(permissons_test_path, 'w+') as test_file:
            test_file.write('test')
        os.remove(permissons_test_path)
    except (OSError, IOError) as e:
        msg = '''\
            Write to the "%s/" directory failed. Please check permissions or change LOG_FILE config.
            Original error was: %s.''' % (dirname(LOG_FILE), e)
        raise Exception(dedent(msg))

    LOG_LEVEL = getattr(config, 'LOG_LEVEL', 'INFO')

    logging.config.dictConfig({
        'version': 1,
        'formatters': {
            'verbose': {
                'format': '%(levelname)s %(asctime)s %(module)s.py: %(message)s',
                'datefmt': '<%Y-%m-%d %H:%M:%S>'
            },
            'simple': {'format': '%(levelname)s %(module)s.py: %(message)s'},
        },
        'handlers': {
            'log_file': {
                'level': LOG_LEVEL,
                'class': 'logging.handlers.WatchedFileHandler',
                'filename': LOG_FILE,
                'formatter': 'verbose'
            },
            'console': {
                'level': LOG_LEVEL,
                'class': 'logging.StreamHandler',
                'formatter': 'simple'
            },
        },
        'loggers': {
            '': {'handlers': ['log_file', 'console'], 'level': LOG_LEVEL},
        }
    })

    try:
        from insightly_stages_config import INSIGHTLY_API_KEY
    except Exception as e:
        logging.critical('Please set required config varialble in insightly_automation_config.py:\n%s', str(e))
        raise

    if not re.match(r'\w{8}-\w{4}-\w{4}-\w{4}-\w{12}', INSIGHTLY_API_KEY):
        err = Exception('INSIGHTLY_API_KEY has wrong format "%s", please set the right value in insightly_automation_config.py' % INSIGHTLY_API_KEY)
        logging.critical(err)
        raise err


def get_custom_field(opp, field_id, default=None):
    field = [x for x in opp['CUSTOMFIELDS'] if x['CUSTOM_FIELD_ID'] == field_id]
    if field:
        return field[0]
    else:
        field = {'CUSTOM_FIELD_ID': field_id}
        if default is not None:
            field['FIELD_VALUE'] = default
        opp['CUSTOMFIELDS'].append(field)
        return field


def get_fields_by_name(fields, name):
    for x in fields:
        if x['FIELD_FOR'] == 'OPPORTUNITY' and name.lower() in x['FIELD_NAME'].lower():
            yield x


def process_opportunities_stages():
    insightly_auth = (config.INSIGHTLY_API_KEY, '')
    fields = insightly_get('/CustomFields', insightly_auth)
    fields_map = {
        'last_known_stage': list(get_fields_by_name(fields, 'last known stage')),
        'last_time_stage_changed': list(get_fields_by_name(fields, 'last time stage changed')),
        'days_in_current_stage': list(get_fields_by_name(fields, 'days in current stage')),
    }

    for fieldname in fields_map:
        if len(fields_map[fieldname]) > 1:
            logging.error('More than one %s custom fields: %s' % (fieldname, fields_map[fieldname]))
            return
        elif not fields_map[fieldname]:
            logging.error('No %s custom field found!' % fieldname)
            return

    last_known_stage_id = fields_map['last_known_stage'][0]['CUSTOM_FIELD_ID']
    last_time_stage_changed_id = fields_map['last_time_stage_changed'][0]['CUSTOM_FIELD_ID']
    days_in_current_stage_id = fields_map['days_in_current_stage'][0]['CUSTOM_FIELD_ID']

    opportunities = insightly_get_all('/opportunities/Search?opportunity_state=OPEN', insightly_auth)
    stages = {x['STAGE_ID']: x for x in insightly_get('/PipelineStages', insightly_auth)}

    logging.info('%d opportunities found.' % len(opportunities))

    for opp in opportunities:
        if not opp['STAGE_ID']:
            continue
        if not stages.get(opp['STAGE_ID']):
            logging.error('No stage %s found!' % opp['STAGE_ID'])
            return
        stage_order = stages.get(opp['STAGE_ID'])['STAGE_ORDER']

        now = datetime.now().strftime('%Y-%m-%d 00:00:00')
        last_known_stage = get_custom_field(opp, last_known_stage_id)
        last_time_stage_changed = get_custom_field(opp, last_time_stage_changed_id, default=now)
        days_in_current_stage = get_custom_field(opp, days_in_current_stage_id, default=0)

        if last_known_stage.get('FIELD_VALUE'):
            if stage_order == last_known_stage['FIELD_VALUE']:
                last_time = datetime.strptime(last_time_stage_changed['FIELD_VALUE'], '%Y-%m-%d 00:00:00')
                days_in_current_stage['FIELD_VALUE'] = (datetime.now() - last_time).days
            elif stage_order > last_known_stage['FIELD_VALUE']:
                days_in_current_stage['FIELD_VALUE'] = 0
                last_time_stage_changed['FIELD_VALUE'] = datetime.now().strftime('%Y-%m-%d 00:00:00')
                last_known_stage['FIELD_VALUE'] = stage_order
        else:
            last_known_stage['FIELD_VALUE'] = stage_order
            last_time_stage_changed['FIELD_VALUE'] = datetime.now().strftime('%Y-%m-%d 00:00:00')

        opp_url = "/opportunities/%s" % opp['OPPORTUNITY_ID']
        insightly_put(opp_url, insightly_auth, json=opp)
        logging.info('Opportunity #%d last_known_stage updated to "%s"' % (opp['OPPORTUNITY_ID'], last_known_stage['FIELD_VALUE']))


def main():
    configure()
    process_opportunities_stages()


if __name__ == '__main__':
    main()
