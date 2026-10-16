import gzip
import json

import httpx
import pytest

from getmeajob.service import JobService
from getmeajob.sources.bulldogjob import BulldogjobSource, canonical_url, parse_job_page as parse_bulldog
from getmeajob.sources.solidjobs import SolidJobsSource, parse_job_page as parse_solid
from getmeajob.sources.rocketjobs import prefilter
from getmeajob.store import Store
from tests.profile_fixtures import SAMPLE_SEARCH_PROFILE

BULLDOG_URL = 'https://bulldogjob.com/companies/jobs/123-senior-python-developer-example'
SOLID_URL = 'https://solid.jobs/offer/123/example-senior-python-developer'


def bulldog_page(**changes):
    job = {
        'state': 'published', 'position': 'Senior Python Developer',
        'company': {'name': 'Example'}, 'details': '<p>Build Python APIs with Flask.</p>',
        'requirements': '<p>Python, Vue and SQL</p>', 'offer': '<p>Full-time role</p>',
        'workModes': ['remote'], 'remote': True, 'locations': [{'location': {'cityPl': 'Bydgoszcz'}}],
        'contractB2b': True, 'contractEmployment': False, 'contractOther': False,
        'b2bSalary': {'money': '22 000 - 28 000', 'currency': 'PLN', 'timeframe': 'month', 'hidden': False},
        'publishedAt': '2026-10-01', 'endsAt': '2026-11-01', **changes,
    }
    state = {'props': {'pageProps': {'data': {'job': job}}}}
    return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(state) + '</script>'


def solid_page(**changes):
    posting = {
        '@type': 'JobPosting', 'title': 'Senior Python Developer',
        'description': '<p>Build Python and Vue applications.</p>',
        'hiringOrganization': {'name': 'Example'},
        'jobLocationType': 'TELECOMMUTE',
        'jobLocation': {'address': {'addressLocality': 'Warszawa'}},
        'employmentType': 'CONTRACTOR',
        'baseSalary': {'currency': 'PLN', 'value': {'minValue': 23000, 'maxValue': 28000, 'unitText': 'MONTH'}},
        'datePosted': '2026-10-01', 'validThrough': '2026-11-01', **changes,
    }
    return '<script type="application/ld+json">' + json.dumps({'@type': 'WebSite'}) + '</script>' \
           + '<script type="application/ld+json">' + json.dumps(posting) + '</script>'


def sitemap(*urls):
    return '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(
        f'<url><loc>{url}</loc><lastmod>2026-10-16</lastmod></url>' for url in urls) + '</urlset>'


@pytest.mark.parametrize('source_type,url,page', [
    ('bulldog', BULLDOG_URL, bulldog_page()),
    ('solid', SOLID_URL, solid_page()),
])
def test_public_offer_parsing_and_prefilter(source_type, url, page):
    offer = (parse_bulldog if source_type == 'bulldog' else parse_solid)(url, page)
    assert offer['title'] == 'Senior Python Developer'
    assert offer['remote_mode'] == 'remote'
    assert offer['contract_types'] == ['B2B']
    assert offer['salary']['maximum'] == 28000
    assert offer['salary']['basis'] == 'b2b_net'
    assert prefilter(offer, SAMPLE_SEARCH_PROFILE) == (True, '')


def test_bulldog_hybrid_and_multiple_contract_salaries():
    offer = parse_bulldog(BULLDOG_URL, bulldog_page(
        remote=False, workModes=['hybrid'], contractEmployment=True,
        employmentSalary={'money': '19 000 - 24 000', 'currency': 'PLN', 'timeframe': 'month', 'hidden': False}))
    assert offer['remote_mode'] == 'hybrid'
    assert offer['salary']['maximum'] is None
    assert 'Salary B2B: 22000' in offer['description']
    assert 'Salary UoP: 19000' in offer['description']
    assert not prefilter(offer, SAMPLE_SEARCH_PROFILE)[0]
    assert canonical_url(BULLDOG_URL.replace('.com', '.pl')) == BULLDOG_URL

    remote_option = parse_bulldog(BULLDOG_URL, bulldog_page(workModes=['remote', 'hybrid']))
    assert remote_option['remote_mode'] == 'remote'


def test_solid_onsite_and_hourly_salary():
    offer = parse_solid(SOLID_URL, solid_page(
        jobLocationType='ON_SITE', baseSalary={'currency': 'USD', 'value': {
            'minValue': 40, 'maxValue': 50, 'unitText': 'HOUR'}}))
    assert offer['remote_mode'] == 'unknown'
    assert offer['salary']['unit'] == 'hour'
    assert offer['salary']['currency'] == 'USD'
    assert not prefilter(offer, SAMPLE_SEARCH_PROFILE)[0]


def make_source(cls, url, page, *, blocked=False):
    def respond(request):
        if request.url.path == '/robots.txt':
            rules = 'User-agent: *\nDisallow: /companies/jobs/' if blocked else 'User-agent: *\nAllow: /'
            return httpx.Response(200, text=rules)
        if request.url.path.endswith('.gz'):
            return httpx.Response(200, content=gzip.compress(sitemap(url, url).encode()))
        if request.url.path.endswith('.xml'):
            return httpx.Response(200, text=sitemap(url, url))
        if str(request.url) == url:
            return httpx.Response(200, text=page)
        return httpx.Response(404)
    return cls(httpx.Client(transport=httpx.MockTransport(respond)), delay_seconds=0)


@pytest.mark.parametrize('cls,url,page', [
    (BulldogjobSource, BULLDOG_URL, bulldog_page()),
    (SolidJobsSource, SOLID_URL, solid_page()),
])
def test_sitemap_sync_deduplicates_and_reports(cls, url, page, tmp_path):
    source = make_source(cls, url, page)
    source.max_candidates = 5
    store = Store(tmp_path / 'test.db')
    store.set_setting('search_profile', SAMPLE_SEARCH_PROFILE)
    service = JobService(store, source=source)
    result = service.sync(lambda *_args: None)
    assert result['new'] == 1
    assert result['sources'][0]['discovery']['candidates'] == 1
    assert service.sync(lambda *_args: None)['unchanged'] == 1


def test_bulldog_robots_blocks_jobs():
    source = make_source(BulldogjobSource, BULLDOG_URL, bulldog_page(), blocked=True)
    diagnostics = {}
    assert source.discover(SAMPLE_SEARCH_PROFILE, diagnostics) == []
    with pytest.raises(ValueError, match='robots.txt'):
        source.fetch_offer(BULLDOG_URL)


def test_service_registers_sources_and_imports_polish_bulldog_link(tmp_path):
    store = Store(tmp_path / 'test.db')
    store.set_setting('search_profile', SAMPLE_SEARCH_PROFILE)
    service = JobService(store)
    ids = {source['id'] for source in service.available_sources()}
    assert {'bulldogjob', 'solidjobs'} <= ids
    service.sources = [make_source(BulldogjobSource, BULLDOG_URL, bulldog_page())]
    offer, reason = service.import_url(BULLDOG_URL.replace('.com', '.pl'))
    assert offer['url'] == BULLDOG_URL
    assert not reason
