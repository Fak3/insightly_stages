# -*- coding: UTF-8 -*-
# You can run this test script with `python -m unittest test`

from datetime import datetime, timedelta
from unittest import TestCase

from mock import Mock, patch

import insightly_stages
import insightly_stages_config as config


OPPORTUNITY_TEMPLATE = {
    "OPPORTUNITY_ID": 111,
    "OPPORTUNITY_NAME": "op111",
    "OPPORTUNITY_DETAILS": "dddddd",
    "PROBABILITY": 1,
    "BID_CURRENCY": "USD",
    "BID_AMOUNT": 1,
    "BID_TYPE": "Fixed Bid",
    "BID_DURATION": None,
    "FORECAST_CLOSE_DATE": "2016-03-31 00:00:00",
    "ACTUAL_CLOSE_DATE": None,
    "CATEGORY_ID": 111,
    "PIPELINE_ID": 111,
    "STAGE_ID": 111,
    "OPPORTUNITY_STATE": "OPEN",
    "IMAGE_URL": "http://s3.amazonaws.com/insightly.userfiles/643478/",
    "RESPONSIBLE_USER_ID": None,
    "OWNER_USER_ID": 111,
    "DATE_CREATED_UTC": "2016-03-28 13:11:50",
    "DATE_UPDATED_UTC": "2016-03-29 12:03:56",
    "VISIBLE_TO": "EVERYONE",
    "VISIBLE_TEAM_ID": None,
    "VISIBLE_USER_IDS": None,
    "CUSTOMFIELDS": [],
    "TAGS": [],
    "LINKS": [],
    "EMAILLINKS": []}

CUSTOM_FIELD_TEMPLATE = {
    u'CUSTOM_FIELD_ID': u'OPPORTUNITY_FIELD_1',
    u'CUSTOM_FIELD_OPTIONS': [],
    u'DEFAULT_VALUE': None,
    u'FIELD_FOR': u'OPPORTUNITY',
    u'FIELD_HELP_TEXT': None,
    u'FIELD_NAME': u'title',
    u'FIELD_TYPE': u'TEXT',
    u'GROUP_ID': None,
    u'ORDER_ID': 1}

STAGE_TEMPLATE = {
    "STAGE_ID": 824432,
    "PIPELINE_ID": 259547,
    "STAGE_NAME": "stage1",
    "STAGE_ORDER": 1,
    "ACTIVITYSET_ID": None,
    "OWNER_USER_ID": 1093279
}


class InsightlyFakeServer(object):
    """
    Trivial fake server will look up requested GET url in dict of configured responses (self.get_response).

    You can provide initial get_response dict on init:
    >>> fake_insightly = InsightlyFakeServer(get_response={'/CustomFields': [{'x': 'y'}, {'a': 'b'}]})

    Or you can later add items to the response dict:
    >>> fake_insightly.get_response['/contacts/1'] = {'id': 1, 'name': 'lol'})

    Then you should patch `insightly_get()` function with this server's get() method:
    >>> patch('insightly_stages.insightly_get', Mock(side_effect=fake_insightly.get)).start()

    """
    def __init__(self, get_response=None):
        self.get_response = get_response or {}

    def get(self, url, *args, **kwargs):
        if url not in self.get_response:
            raise Exception('Unknown fake url "%s"' % url)
        return self.get_response[url]


class OpportynityTestCase(TestCase):

    def setUp(self):
        # GIVEN insightly server with three custom fields and two pipeline stages
        self.fake_insightly = InsightlyFakeServer(get_response={
            '/CustomFields': [
                dict(CUSTOM_FIELD_TEMPLATE, CUSTOM_FIELD_ID='last_stage', FIELD_NAME='last known stage'),
                dict(CUSTOM_FIELD_TEMPLATE, CUSTOM_FIELD_ID='last_time', FIELD_NAME='last time stage changed'),
                dict(CUSTOM_FIELD_TEMPLATE, CUSTOM_FIELD_ID='days_in_cur_stage', FIELD_NAME='days in current stage'),
            ],
            '/PipelineStages': [
                dict(STAGE_TEMPLATE, STAGE_ID=1, STAGE_ORDER=1), dict(STAGE_TEMPLATE, STAGE_ID=2, STAGE_ORDER=2)
            ]
        })
        patch('insightly_stages.insightly_get', Mock(side_effect=self.fake_insightly.get)).start()
        patch('insightly_stages.insightly_put', Mock()).start()

    def tearDown(self):
        patch.stopall()

    def test_new_opportunity(self):
        # GIVEN new opportunity
        self.fake_insightly.get_response['/opportunities/Search?opportunity_state=OPEN'] = [dict(
            OPPORTUNITY_TEMPLATE, OPPORTUNITY_ID=1, STAGE_ID=1
        )]

        # WHEN process_opportunities_stages() is called
        insightly_stages.process_opportunities_stages()

        # THEN
        insightly_stages.insightly_put.assert_called_once_with(
            '/opportunities/1',
            (config.INSIGHTLY_API_KEY, ''),
            json=dict(
                OPPORTUNITY_TEMPLATE,
                OPPORTUNITY_ID=1,
                STAGE_ID=1,
                CUSTOMFIELDS=[
                    {'CUSTOM_FIELD_ID': 'last_stage', 'FIELD_VALUE': 1},
                    {'CUSTOM_FIELD_ID': 'last_time', 'FIELD_VALUE': datetime.now().strftime('%Y-%m-%d 00:00:00')},
                    {'CUSTOM_FIELD_ID': 'days_in_cur_stage', 'FIELD_VALUE': 0},
                ]
            )
        )

    def test_opportunity_stage_update(self):
        # GIVEN opportunity
        self.fake_insightly.get_response['/opportunities/Search?opportunity_state=OPEN'] = [dict(
            OPPORTUNITY_TEMPLATE,
            OPPORTUNITY_ID=1,
            STAGE_ID=2,
            CUSTOMFIELDS=[
                {'CUSTOM_FIELD_ID': 'last_stage', 'FIELD_VALUE': 1},
                {'CUSTOM_FIELD_ID': 'last_time', 'FIELD_VALUE': datetime(2015, 8, 30).strftime('%Y-%m-%d 00:00:00')},
                {'CUSTOM_FIELD_ID': 'days_in_cur_stage', 'FIELD_VALUE': 0},
            ]
        )]

        # WHEN process_opportunities_stages() is called
        insightly_stages.process_opportunities_stages()

        # THEN
        insightly_stages.insightly_put.assert_called_once_with(
            '/opportunities/1',
            (config.INSIGHTLY_API_KEY, ''),
            json=dict(
                OPPORTUNITY_TEMPLATE,
                OPPORTUNITY_ID=1,
                STAGE_ID=2,
                CUSTOMFIELDS=[
                    {'CUSTOM_FIELD_ID': 'last_stage', 'FIELD_VALUE': 2},
                    {'CUSTOM_FIELD_ID': 'last_time', 'FIELD_VALUE': datetime.now().strftime('%Y-%m-%d 00:00:00')},
                    {'CUSTOM_FIELD_ID': 'days_in_cur_stage', 'FIELD_VALUE': 0},
                ]
            )
        )

    def test_opportunity_stage_linger(self):
        # GIVEN opportunity
        last_time_stage_changed = (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d 00:00:00')

        self.fake_insightly.get_response['/opportunities/Search?opportunity_state=OPEN'] = [dict(
            OPPORTUNITY_TEMPLATE,
            OPPORTUNITY_ID=1,
            STAGE_ID=1,
            CUSTOMFIELDS=[
                {'CUSTOM_FIELD_ID': 'last_stage', 'FIELD_VALUE': 1},
                {'CUSTOM_FIELD_ID': 'last_time', 'FIELD_VALUE': last_time_stage_changed},
                {'CUSTOM_FIELD_ID': 'days_in_cur_stage', 'FIELD_VALUE': 0},
            ]
        )]

        # WHEN process_opportunities_stages() is called
        insightly_stages.process_opportunities_stages()

        # THEN
        insightly_stages.insightly_put.assert_called_once_with(
            '/opportunities/1',
            (config.INSIGHTLY_API_KEY, ''),
            json=dict(
                OPPORTUNITY_TEMPLATE,
                OPPORTUNITY_ID=1,
                STAGE_ID=1,
                CUSTOMFIELDS=[
                    {'CUSTOM_FIELD_ID': 'last_stage', 'FIELD_VALUE': 1},
                    {'CUSTOM_FIELD_ID': 'last_time', 'FIELD_VALUE': last_time_stage_changed},
                    {'CUSTOM_FIELD_ID': 'days_in_cur_stage', 'FIELD_VALUE': 5},
                ]
            )
        )
