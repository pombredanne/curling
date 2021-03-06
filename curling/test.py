import decimal
import json
import unittest

from django.conf import settings

minimal = {
    'DATABASES': {'default': {}},
    'CURLING_FORMAT_LISTS': True,
    # Use the toolbar for tests because it handly caches results for us.
    'STATSD_CLIENT': 'django_statsd.clients.toolbar',
    'STATSD_PREFIX': None,
}

if not settings.configured:
    settings.configure(**minimal)

from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned
import mock
from nose.tools import eq_, ok_, raises
from django_statsd.clients import get_client

import lib
lib.statsd = get_client()

from requests.exceptions import ConnectionError

# Some samples for the Mock.
samples = {
    'GET:/services/settings/APPEND_SLASH/': {
        'key': 'APPEND_SLASH'
    },
    'GET:/services/settings/': {
        'meta': {'limit': 20, 'total_count': 185},
        'objects': [
            {'key': 'ABSOLUTE_URL_OVERRIDES'},
            {'key': 'ADMINS'},
        ]
    },
    'GET:/services/nothing/': {
        'meta': {},
        'objects': []
    }
}

lib.mock_lookup = samples


class TestAPI(unittest.TestCase):

    def setUp(self):
        self.api = lib.MockAPI('')

    def test_get_one(self):
        eq_(self.api.services.settings('APPEND_SLASH').get_object(),
            samples['GET:/services/settings/APPEND_SLASH/'])

    def test_list(self):
        res = self.api.services.settings.get()
        eq_(len(res), 2)
        ok_(isinstance(res, lib.TastypieList))
        eq_(res.limit, 20)
        eq_(res.total_count, 185)

    @raises(MultipleObjectsReturned)
    def test_get_raises(self):
        self.api.services.settings.get_object()

    def test_get_empty(self):
        res = self.api.services.nothing.get()
        eq_(len(res), 0)

    @raises(ObjectDoesNotExist)
    def test_get_none(self):
        self.api.services.nothing.get_object()

    @raises(ObjectDoesNotExist)
    def test_get_404(self):
        self.api.services.nothing.get_object_or_404()

    @raises(ObjectDoesNotExist)
    def test_get_list_404(self):
        self.api.services.nothing.get_list_or_404()

    def test_get_list_404_works(self):
        res = self.api.services.settings.get_list_or_404()
        eq_(len(res), 2)

    @mock.patch('curling.lib.MockTastypieResource._lookup')
    def test_post_decimal(self, lookup):
        self.api.services.settings.post({
            'amount': decimal.Decimal('1.0')
        })
        eq_(json.loads(lookup.call_args[1]['data']), {u'amount': u'1.0'})

    def test_by_url(self):
        eq_(len(self.api.by_url('/services/settings/').get()), 2)
        eq_(self.api.by_url('/services/settings/APPEND_SLASH/').get(),
            {'key': 'APPEND_SLASH'})

    def test_by_url_borked(self):
        self.assertRaises(IndexError, self.api.by_url, '/')

    @raises(lib.HttpServerError)
    @mock.patch('curling.lib.MockTastypieResource._call_request')
    def test_connection_error(self, _call_request):
        _call_request.side_effect = ConnectionError
        self.api.services.nothing.get_object()


class TestOAuth(unittest.TestCase):

    def setUp(self):
        self.api = lib.MockAPI('http://foo.com')

    @mock.patch('curling.lib.MockTastypieResource._call_request')
    def test_none(self, _call_request):
        self.api.services.settings.get()
        _call_request.assert_called_with('GET',
            'http://foo.com/services/settings/', None, {},
            {'content-type': 'application/json', 'accept': 'application/json'})

    @mock.patch('curling.lib.MockTastypieResource._call_request')
    def test_some(self, _call_request):
        self.api.activate_oauth('key', 'secret')
        self.api.services.settings.get()
        _call_request.assert_called_with('GET',
            'http://foo.com/services/settings/', None, {}, mock.ANY)
        ok_('Authorization' in _call_request.call_args[0][4])

    @mock.patch('curling.lib.MockTastypieResource._call_request')
    def test_query_string(self, _call_request):
        self.api.activate_oauth('key', 'secret')
        self.api.services.settings.get(foo='bar')
        _call_request.assert_called_with('GET',
            'http://foo.com/services/settings/', None, {'foo': 'bar'},
            mock.ANY)


class TestCallable(unittest.TestCase):

    def setUp(self):
        self.api = lib.MockAPI('http://foo.com')

    @mock.patch('curling.lib.MockTastypieResource._call_request')
    def test_some(self, _call_request):
        def foo(slumber, headers=None, **kwargs):
            headers['Foo'] = 'bar'

        self.api._add_callback({'method': foo})

        self.api.services.settings.get()
        ok_('Foo' in _call_request.call_args[0][4])

    @mock.patch('curling.lib.MockTastypieResource._call_request')
    def test_some_extra(self, _call_request):
        def foo(slumber, headers=None, **kwargs):
            ok_(kwargs['extra'], 'boo')

        self.api._add_callback({'method': foo, 'extra': 'bar'})
        self.api.services.settings.get()


class TestStatsd(unittest.TestCase):

    def setUp(self):
        self.api = lib.MockAPI('http://foo.com')
        lib.statsd.reset()

    def test_get(self):
        self.api.services.settings.get()
        eq_(lib.statsd.cache, {'services.settings.GET.200|count': [[1, 1]]})
        eq_(len(lib.statsd.timings), 1)

    @mock.patch('curling.lib.MockTastypieResource._call_request')
    def test_get_with_etag_header(self, _call_request):
        _call_request.return_value = mock.Mock(status_code=304)
        self.api.services.settings.get(headers={'If-None-Match': 'etag'})
        eq_(lib.statsd.cache, {'services.settings.GET.304|count': [[1, 1]]})
        eq_(len(lib.statsd.timings), 1)

    def test_post(self):
        self.api.services.settings.post(data={}, headers={})
        eq_(lib.statsd.cache, {'services.settings.POST.200|count': [[1, 1]]})

    def test_put(self):
        self.api.services.settings.put(data={}, headers={})
        eq_(lib.statsd.cache, {'services.settings.PUT.200|count': [[1, 1]]})

    def test_patch(self):
        self.api.services.settings.patch(data={}, headers={})
        eq_(lib.statsd.cache, {'services.settings.PATCH.200|count': [[1, 1]]})
