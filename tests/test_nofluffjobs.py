import json

import httpx
import pytest

from getmeajob.service import JobService
from getmeajob.sources.nofluffjobs import BASE_URL, NoFluffJobsSource, parse_job_page
from getmeajob.sources.rocketjobs import prefilter
from getmeajob.store import Store
from tests.profile_fixtures import SAMPLE_SEARCH_PROFILE

SLUG = 'senior-python-developer-example-remote'
URL = BASE_URL + '/pl/job/' + SLUG


def html(state):
    return '<script id="serverApp-state" type="application/json">' + json.dumps(state) + '</script>'


def posting(**changes):
    return {
        'title': 'Senior Python Developer', 'status': 'PUBLISHED',
        'company': {'name': 'Example'},
        'details': {'description': '<p>Build Flask APIs.</p>'},
        'requirements': {'description': '<p>Experience with databases</p>',
                         'musts': [{'value': 'Python'}], 'nices': [{'value': 'Vue'}],
                         'languages': [{'code': 'en', 'level': 'B2', 'type': 'MUST'}]},
        'specs': {'dailyTasks': ['Maintain production services']},
        'location': {'remote': 5, 'places': [{'city': 'Warszawa'}, {'city': 'Bydgoszcz'}]},
        'essentials': {'originalSalary': {'currency': 'PLN', 'types': {
            'b2b': {'range': [22000, 27000], 'period': 'Month'}}}},
        'posted': 1790178982416, 'expiresAt': '2026-10-23T23:59:59', **changes,
    }


def job_page(**changes):
    return html({'/posting/' + SLUG + '?region=pl': posting(**changes),
                 '/joboffers/similar': {'title': 'Wrong job', 'location': {'remote': 4}}})


def listing(slugs, total=1):
    return html({'hash': {'criteriaSearch': {}, 'postings': [
        {'url': slug, 'title': 'Python Developer'} for slug in slugs], 'totalPages': total}})


def source(handler, **kwargs):
    def transport(request):
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text='User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /posting/')
        return handler(request)
    return NoFluffJobsSource(httpx.Client(transport=httpx.MockTransport(transport)), delay_seconds=0, **kwargs)


def test_complete_offer_and_prefilter():
    offer = parse_job_page(URL, job_page())
    assert offer['remote_mode'] == 'remote'
    assert offer['company'] == 'Example'
    assert offer['location'] == 'Warszawa, Bydgoszcz'
    for text in ['databases', 'Vue', 'B2', 'Maintain production', 'Flask']:
        assert text in offer['description']
    assert 'Wrong job' not in offer['description']
    assert offer['salary']['basis'] == 'b2b_net'
    assert prefilter(offer, SAMPLE_SEARCH_PROFILE) == (True, '')


@pytest.mark.parametrize('period,currency', [('Hour', 'USD'), ('Day', 'PLN')])
def test_no_salary_conversion(period, currency):
    offer = parse_job_page(URL, job_page(essentials={'originalSalary': {
        'currency': currency, 'types': {'b2b': {'range': [100, 150], 'period': period}}}}))
    assert offer['salary']['maximum'] == 150
    assert offer['salary']['currency'] == currency
    assert offer['salary']['unit'] == period.lower()


def test_multiple_contracts_and_missing_salary():
    offer = parse_job_page(URL, job_page(essentials={'originalSalary': {'currency': 'PLN', 'types': {
        'b2b': {'range': [25000, 30000], 'period': 'Month'},
        'permanent': {'range': [18000, 22000], 'period': 'Month'}}}}))
    assert offer['contract_types'] == ['B2B', 'UoP']
    assert offer['salary']['maximum'] is None
    assert '30000' in offer['description'] and '22000' in offer['description']
    assert parse_job_page(URL, job_page(essentials={}))['salary']['maximum'] is None


def test_boolean_contract_flag_has_no_salary_and_does_not_stop_sync():
    flagged = job_page(essentials={'originalSalary': {
        'currency': 'PLN', 'types': {'intern': True}, 'disclosedAt': 'VISIBLE'}})
    offer = parse_job_page(URL, flagged)
    assert offer['contract_types'] == ['intern']
    assert offer['salary']['maximum'] is None
    assert not prefilter(offer, SAMPLE_SEARCH_PROFILE)[0]

    second_slug = 'python-developer-example-remote'
    def handler(request):
        if request.url.path == '/pl/':
            return httpx.Response(200, text=listing([SLUG, second_slug]))
        if request.url.path.endswith(SLUG):
            return httpx.Response(200, text=flagged)
        return httpx.Response(200, text=job_page().replace(SLUG, second_slug))

    diagnostics = {}
    offers = list(source(handler).offers(profile={'roles': ['Python Developer']}, diagnostics=diagnostics))
    assert len(offers) == 2
    assert diagnostics['detail_errors'] == 0


def test_hybrid_and_description_override_remote():
    offer = parse_job_page(URL, job_page(location={'remote': 4, 'places': []}))
    assert offer['remote_mode'] == 'hybrid'
    assert not prefilter(offer, SAMPLE_SEARCH_PROFILE)[0]
    offer = parse_job_page(URL, job_page(requirements={'description': 'Office attendance required weekly'}))
    assert not prefilter(offer, SAMPLE_SEARCH_PROFILE)[0]


@pytest.mark.parametrize('page', ['<html>Blocked</html>', html({}), job_page(status='EXPIRED')])
def test_missing_or_inactive_offer_fails(page):
    with pytest.raises(ValueError):
        parse_job_page(URL, page)


def test_cumulative_pagination_dedup_and_detail_error():
    calls = []
    def handler(request):
        calls.append(str(request.url))
        if request.url.path == '/pl/':
            page = int(request.url.params['page'])
            return httpx.Response(200, text=listing([SLUG] if page == 1 else [SLUG, 'bad-python-developer'], 2))
        return httpx.Response(200, text=job_page() if request.url.path.endswith(SLUG) else '<html>Gone</html>')
    diagnostics, progress = {}, []
    offers = list(source(handler).offers(profile={'roles': ['Python Developer', 'Python Engineer']},
                                        diagnostics=diagnostics, progress=lambda a, b: progress.append((a, b))))
    assert len(offers) == 1
    assert diagnostics['pages_fetched'] == 4
    assert diagnostics['candidates'] == 2
    assert diagnostics['detail_errors'] == 1
    assert calls.count(URL) == 1
    assert progress[-1] == (2, 2)


def test_candidate_limit_and_configurable_roles():
    queries = []
    def handler(request):
        queries.append(request.url.params['criteria'])
        return httpx.Response(200, text=html({'hash': {'criteriaSearch': {}, 'totalPages': 9, 'postings': [
            {'url': f'java-developer-{n}', 'title': 'Java Developer'} for n in range(4)]}}))
    diag = {}
    urls = source(handler, max_candidates_per_term=2).discover({'roles': ['Java Developer z Spring']}, diag)
    assert len(urls) == 2 and diag['pages_fetched'] == 1
    assert queries == ['keyword=Java Developer']


def test_robots_and_redirects_block_before_request():
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={'location': 'https://example.org/private'})
    with pytest.raises(ValueError, match='przekierowanie'):
        source(handler).fetch_offer(URL)
    assert calls == [URL]
    blocked = NoFluffJobsSource(httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text='User-agent: *\nDisallow: /pl/job/'))), delay_seconds=0)
    with pytest.raises(ValueError, match='robots.txt'):
        blocked.fetch_offer(URL)


def test_service_registration_sync_import_and_idempotence(tmp_path):
    def handler(request):
        return httpx.Response(200, text=listing([SLUG]) if request.url.path == '/pl/' else job_page())
    store = Store(tmp_path / 'test.sqlite3')
    store.set_setting('search_profile', SAMPLE_SEARCH_PROFILE)
    service = JobService(store)
    assert {'id': 'nofluffjobs', 'label': 'No Fluff Jobs'} in service.available_sources()
    service.sources = [source(handler)]
    first = service.sync(lambda *args: None, ['nofluffjobs'])
    assert first['new'] == 1 and first['sources'][0]['discovery']['candidates'] == 1
    assert service.sync(lambda *args: None, ['nofluffjobs'])['unchanged'] == 1
    offer, reason = service.import_url(URL)
    assert offer['title'] == 'Senior Python Developer' and not reason
    assert len(store.list_offers()) == 1


def test_list_failure_saved_as_error(tmp_path):
    store = Store(tmp_path / 'test.sqlite3')
    store.set_setting('search_profile', SAMPLE_SEARCH_PROFILE)
    service = JobService(store, source=source(lambda request: httpx.Response(200, text='<html>Challenge</html>')))
    with pytest.raises(ValueError):
        service.sync(lambda *args: None)
    assert store.get_setting('last_sync_report')['status'] == 'error'
