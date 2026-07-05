import calendar
import glob
import importlib.util
import re
import tarfile
import jinja2
import utils
import os
import json
from datetime import datetime, timedelta, date
import pytz
import shutil
import tempfile
import urllib.request
import warnings
import yaml
import markdown

config = utils.get_config(get_all=True)

schedule_path = utils.path_to_data_folder('events.json')


# Create a Jinja2 environment
env = jinja2.Environment(loader=jinja2.FileSystemLoader('templates'), extensions=['jinja2.ext.loopcontrols'])

# URL helpers exposed to all templates. KW slug uses uppercase W per ISO 8601
# week notation (2026-W02). Month and KW arrive zero-padded as strings from
# the parser; year_url accepts either kw_year or calendar year (caller decides).
env.globals['year_url'] = lambda y: '/{}/'.format(y)
env.globals['month_url'] = lambda y, m: '/{}/{:02d}/'.format(y, int(m))
env.globals['kw_url'] = lambda y, k: '/{}/W{}/'.format(y, k)

# Load a template
template = env.get_template('index.j2')
sitemap_template = env.get_template('sitemap.j2')


# Footer wordmark SVG, generated per build by the pen-font-gen gist with the
# build datetime as seed. The seed is embedded in the SVG's provenance comment.
PEN_FONT_GEN_URL = ('https://gist.githubusercontent.com/ghxm/'
                    'af1616fc2d8b12f1823ad5e88eb309e0/raw/pen-font-gen.py')


def generate_footer_svg(now, out_path):
    """Generate the footer wordmark SVG. Returns the seed string on success."""
    script_path = os.path.join(tempfile.gettempdir(), 'pen_font_gen.py')
    urllib.request.urlretrieve(PEN_FONT_GEN_URL, script_path)
    spec = importlib.util.spec_from_file_location('pen_font_gen', script_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    seed = now.strftime('%Y%m%d%H%M%S')
    with tempfile.TemporaryDirectory() as tmp:
        mod.main(['--text', config.get('footer_logo_text'), '--n', '1',
                  '--seed', seed, '--out', tmp])
        svg = glob.glob(os.path.join(tmp, '*.svg'))[0]
        shutil.copyfile(svg, out_path)
    return seed


def _flatten_schedule(aggregated):
    """Walk an aggregated year->kw->date->[events] dict back into a flat list."""
    return [ev
            for year in aggregated.values()
            for kw in year.values()
            for day in kw.values()
            for ev in day]


def latest_change(events):
    """Most recent real change time across events, for an honest sitemap lastmod.

    Prefers last_modified, falling back to created, then start. Returns a
    tz-aware datetime or None when no event carries a usable timestamp.
    """
    times = []
    for e in events:
        raw = e.get('last_modified') or e.get('created') or e.get('start')
        if not raw:
            continue
        try:
            times.append(utils.ensure_tz(datetime.fromisoformat(raw), config.get('timezone')))
        except (ValueError, TypeError):
            continue
    return max(times) if times else None


def _w3c(dt):
    """Format a tz-aware datetime as a W3C/sitemap timestamp, or None."""
    return dt.isoformat(timespec='seconds') if dt is not None else None


# read in schedule
schedule_str = open(schedule_path, 'r').read()

schedule = json.loads(schedule_str)

# copy list to archive schedule
archive_schedule = schedule.copy()

archive_schedule = utils.remove_events(archive_schedule, cutoff_date=utils.ensure_tz(datetime.now(), tz=config.get('timezone')), remove='future')
schedule = utils.remove_events(schedule, cutoff_date=utils.ensure_tz(datetime.now(), tz=config.get('timezone')) + timedelta(hours=2), remove='past')

schedules = {'schedule': schedule, 'archive_schedule': archive_schedule}
date_weekdays = {'schedule': {}, 'archive_schedule': {}} # dict to store weekdays for each schedule

for schedule_name, schedule_ in schedules.items():

    # if an event is longer than 24h add it for each day
    schedule_modified = []

    for event in schedule_:
        if event['duration_seconds'] > 60*60*24:

            # get days
            if event['all_day']:
                days = [d for d in utils.daterange(utils.make_datetime(event['start']), utils.make_datetime(event['end']))]
            else:
                days = [d for d in utils.daterange(datetime.fromisoformat(event['start']), datetime.fromisoformat(event['end']))]

            for i, day in enumerate(days):
                event_copy = event.copy()
                event_copy['event_day_num'] = i+1
                event_copy['date'] = utils.ymd_string(day)
                event_copy['kw'] = utils.get_weeknum(day)
                schedule_modified.append(event_copy)
        else:
            event['event_day_num'] = 1
            schedule_modified.append(event)

    schedule_ = schedule_modified

    # aggregate schedule by day
    schedule_ = utils.aggregate_schedule(schedule_, groups=['kw_year', 'kw', 'date'])

    # make start_datetime and end_datetime into datetime objects
    for year in schedule_.keys():
        for kw in schedule_[year].keys():
            for date in schedule_[year][kw].keys():
                for event in schedule_[year][kw][date]:
                    event['date_datetime'] = utils.make_date(event['date'], config.get('timezone')) if event['date'] is not None else None
                    event['start_datetime'] = utils.ensure_tz(datetime.fromisoformat(event['start']), config.get('timezone')) if event['start'] is not None else None
                    event['end_datetime'] = utils.ensure_tz(datetime.fromisoformat(event['end']), config.get('timezone')) if event['end'] is not None else None

    # get a dict of date-weekdays
    ## get all dates
    dates = []
    for year in schedule_.keys():
        for kw in schedule_[year].keys():
            for date in schedule_[year][kw].keys():
                dates.append(date)

    date_weekdays[schedule_name] =  {date: utils.get_weekday(utils.make_date(date, tz=config.get('timezone'))) for date in dates}


    # sorting
    if schedule_name == 'archive_schedule':
        # sort years in reverse
        schedule_ = {year: schedule_[year] for year in sorted(schedule_.keys(), reverse=True)}
        # sort kw in reverse
        for year in schedule_.keys():
            schedule_[year] = {kw: schedule_[year][kw] for kw in sorted(schedule_[year].keys(), reverse=True)}
        # sort dates in reverse
        for year in schedule_.keys():
            for kw in schedule_[year].keys():
                schedule_[year][kw] = {date: schedule_[year][kw][date] for date in sorted(schedule_[year][kw].keys(), reverse=True)}

        # sort events by start_datetime in reverse
        for year in schedule_.keys():
            for kw in schedule_[year].keys():
                for date in schedule_[year][kw].keys():
                    schedule_[year][kw][date] = sorted(schedule_[year][kw][date], key=lambda x: x['start_datetime'], reverse=True)
    else:

        # sort by start_datetime
        for year in schedule_.keys():
            for kw in schedule_[year].keys():
                for date in schedule_[year][kw].keys():
                    schedule_[year][kw][date] = sorted(schedule_[year][kw][date], key=lambda x: x['start_datetime'])

    # add back to dict
    schedules[schedule_name] = schedule_



# copy files from data to site/
data = [f for f in os.listdir(utils.path_to_data_folder()) if not  os.path.isdir(os.path.join(utils.path_to_data_folder(), f)) and not f.startswith('.') or f.startswith('_')]

site_folder = utils.path_to_site_folder()
static_folder = utils.path_to_site_folder('static')

for f in data:
    shutil.copyfile(utils.path_to_data_folder(f), os.path.join(site_folder, f))
    # we also need to copy the files to the static folder due to legacy reasons
    shutil.copyfile(utils.path_to_data_folder(f), os.path.join(static_folder, f))


# FOOTER LOGO + GALLERY (optional, FOOTER_LOGO_ENABLED)
if config.get('footer_logo_enabled'):

    build_now = datetime.now(pytz.timezone(config.get('timezone')))
    site_url = config.get('site_url').rstrip('/')

    # generate the footer SVG; a failure must not break the build: keep an
    # existing footer.svg, else fetch the currently deployed one, else the
    # templates omit the footer via their path_exists guard
    footer_svg_path = os.path.join(site_folder, 'footer.svg')
    footer_seed = None
    try:
        footer_seed = generate_footer_svg(build_now, footer_svg_path)
    except Exception as e:
        warnings.warn('footer.svg generation failed ({}), falling back'.format(e))
        if not os.path.exists(footer_svg_path):
            try:
                urllib.request.urlretrieve(site_url + '/footer.svg', footer_svg_path)
            except Exception as e:
                warnings.warn('footer.svg fallback download failed ({}), footer omitted'.format(e))

    # inline the SVG into the pages: browsers rasterize SVG filters poorly
    # inside <img> (especially Safari on high-DPI screens), inline markup
    # renders them at device resolution; root width/height attrs are dropped
    # so the footer CSS controls the size via viewBox scaling
    if os.path.exists(footer_svg_path):
        with open(footer_svg_path) as f:
            svg_markup = f.read()
        svg_markup = re.sub(r'<\?xml[^?]*\?>\s*', '', svg_markup, count=1)
        svg_markup = re.sub(r'(<svg\b[^>]*?)\s+width="[^"]*"\s+height="[^"]*"', r'\1', svg_markup, count=1)
        env.globals['footer_svg'] = svg_markup

    # 30-day rolling backlog of generated logos; lives only on the deployed
    # site: inherit the live manifest + tarball, prune, add this build's logo
    logos_folder = os.path.join(site_folder, 'logos')
    os.makedirs(logos_folder, exist_ok=True)
    manifest_path = os.path.join(logos_folder, 'manifest.json')

    logos = []
    try:
        with urllib.request.urlopen(site_url + '/logos/manifest.json') as resp:
            logos = json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        warnings.warn('live logo manifest unavailable ({}), trying local'.format(e))
        if os.path.exists(manifest_path):
            with open(manifest_path) as f:
                logos = json.load(f)

    missing = {l['file'] for l in logos if not os.path.exists(os.path.join(logos_folder, l['file']))}
    if missing:
        try:
            tar_tmp = os.path.join(tempfile.gettempdir(), 'logos.tar.gz')
            urllib.request.urlretrieve(site_url + '/logos/logos.tar.gz', tar_tmp)
            with tarfile.open(tar_tmp, 'r:gz') as tar:
                for member in tar.getmembers():
                    name = os.path.basename(member.name)
                    if member.isfile() and name in missing and re.fullmatch(r'\d{14}\.svg', name):
                        with open(os.path.join(logos_folder, name), 'wb') as f:
                            f.write(tar.extractfile(member).read())
        except Exception as e:
            warnings.warn('logo tarball unavailable ({})'.format(e))

    # keep only entries inside the window whose file is actually present
    cutoff = build_now - timedelta(days=30)
    kept = []
    for logo in logos:
        logo_path = os.path.join(logos_folder, logo['file'])
        if datetime.fromisoformat(logo['datetime']) >= cutoff and os.path.exists(logo_path):
            kept.append(logo)
        elif os.path.exists(logo_path):
            os.remove(logo_path)
    logos = kept

    # only a freshly generated logo is added; a fallback footer is already
    # part of the backlog
    if footer_seed is not None:
        shutil.copyfile(footer_svg_path, os.path.join(logos_folder, footer_seed + '.svg'))
        logos.append({'file': footer_seed + '.svg', 'datetime': build_now.isoformat()})

    with open(manifest_path, 'w') as f:
        json.dump(logos, f)
    with tarfile.open(os.path.join(logos_folder, 'logos.tar.gz'), 'w:gz') as tar:
        for logo in logos:
            tar.add(os.path.join(logos_folder, logo['file']), arcname=logo['file'])

    # gallery page, calendar-shaped: year -> KW -> date, newest first
    if logos:
        entries = []
        for logo in logos:
            dt = utils.ensure_tz(datetime.fromisoformat(logo['datetime']), config.get('timezone'))
            entries.append({'file': logo['file'],
                            'datetime': logo['datetime'],
                            'time': dt.strftime('%H:%M'),
                            'date': utils.ymd_string(dt),
                            'kw': utils.get_weeknum(dt),
                            'kw_year': utils.get_weeknum_year(dt)})

        gallery = utils.aggregate_schedule(entries, groups=['kw_year', 'kw', 'date'])
        gallery = {year: {kw: {day: sorted(gallery[year][kw][day], key=lambda x: x['datetime'], reverse=True)
                               for day in sorted(gallery[year][kw].keys(), reverse=True)}
                          for kw in sorted(gallery[year].keys(), reverse=True)}
                   for year in sorted(gallery.keys(), reverse=True)}

        gallery_date_weekdays = {e['date']: utils.get_weekday(utils.make_date(e['date'], tz=config.get('timezone')))
                                 for e in entries}

        with open(os.path.join(logos_folder, 'index.html'), 'w') as f:
            f.write(env.get_template('logos.j2').render(config=config,
                                                        gallery=gallery,
                                                        gallery_date_weekdays=gallery_date_weekdays,
                                                        dict_has_key=utils.dict_has_key,
                                                        today=utils.get_today(),
                                                        now=build_now))
    else:
        warnings.warn('no logos available, gallery not rendered')



# NEWS

# read in news
news_path = utils.path_to_data_folder('news/')

news_paths = [os.path.join(news_path, f) for f in os.listdir(news_path) if f.endswith('.md') and not f.startswith('_')]

news = []

for news_path in news_paths:

    # read in file
    news_str = open(news_path, 'r').read()

    # parse yaml
    news_, content = [y for y in yaml.safe_load_all(news_str)]

    news_['id'] = news_path.split('/')[-1].replace('.md','')

    news_['weekday'] = utils.get_weekday(utils.make_date(news_.get('date'), config.get('timezone'))) if news_.get('date') else None


    # parse markdown
    news_['content'] = markdown.markdown(content, extensions=['markdown.extensions.meta', 'markdown.extensions.fenced_code', 'markdown.extensions.codehilite', 'markdown.extensions.toc'])

    # add to list
    news.append(news_)

# sort by id
news = sorted(news, key=lambda x: x['id'], reverse=True)

# put sticky news first
news = sorted(news, key=lambda x: x['sticky'] if x['sticky'] else False, reverse=True)

news_current = []
news_archive = []

for news_ in news:

    if news_.get('from') and utils.make_date(news_.get('from'), config.get('timezone')) < datetime.now(pytz.timezone(config.get('timezone'))).date():
        continue

    if (news_.get('to') and utils.make_date(news_.get('to'), config.get('timezone')) < datetime.now(pytz.timezone(config.get('timezone'))).date()) or \
        (not news_.get('sticky') and news_.get('date') and utils.make_date(news_.get('date'), config.get('timezone')) > datetime.now(pytz.timezone(config.get('timezone'))).date() + timedelta(days=10)):
        news_archive.append(news_)
    else:
        news_current.append(news_)




# VENUES

# read in venues
venues_path = utils.path_to_data_folder('venues/')

venues_paths = [os.path.join(venues_path, f) for f in os.listdir(venues_path) if f.endswith('.yml') and not f.startswith('_')]

venues = []

for venue_path in venues_paths:

    # read in file
    venue_str = open(venue_path, 'r').read()

    try:
        # parse yaml
        venue = yaml.safe_load(venue_str)

        venue['id'] = venue_path.split('/')[-1].replace('.yml','')

        # add to list
        venues.append(venue)
    except:
        warnings.warn('Could not parse venue file: ' + venue_path)


# sort by id
venues = sorted(venues, key=lambda x: x['id'])


# MAKE SITE

# Create archive
with open('site/archive.html', 'w') as f:
    f.write(template.render(config = config,
                            schedule=schedules['archive_schedule'],
                            news = news_archive,
                            venues=venues,
                            date_weekdays=date_weekdays['archive_schedule'],
                            today = utils.get_today(),
                            today_datetime = utils.get_today(return_date_obj=True),
                            now = datetime.now(pytz.timezone(config.get('timezone'))),
                            path_exists = lambda x: os.path.exists(x),
                            truncate = lambda x, n: x[:n] + '...' if len(x) > n else x,
                            value_display = lambda x: x if x is not None else '',
                            dict_has_key = utils.dict_has_key,
                            archive = True,
                            subset_view = None,
                            )
                            )

# Write the rendered template to a file
with open('site/index.html', 'w') as f:
    f.write(template.render(config = config,
                            schedule=schedules['schedule'],
                            news = news_current,
                            venues=venues,
                            date_weekdays=date_weekdays['schedule'],
                            today = utils.get_today(),
                            today_datetime = utils.get_today(return_date_obj=True),
                            now = datetime.now(pytz.timezone(config.get('timezone'))),
                            path_exists = lambda x: os.path.exists(x),
                            truncate = lambda x, n: x[:n] + '...' if len(x) > n else x,
                            value_display = lambda x: x if x is not None else '',
                            dict_has_key = utils.dict_has_key,
                            archive = False,
                            subset_view = None,
                            )
                            )


# SUBSET PAGES
#
# Generate per-year, per-month, and per-KW pages when the feature is enabled.
# Each subset page shows past + future combined for its period, reusing
# templates/index.j2 with a `subset_view` context dict.

sitemap_pages = [
    {'path': '', 'lastmod': _w3c(latest_change(_flatten_schedule(schedules['schedule'])))},
    {'path': 'archive', 'lastmod': _w3c(latest_change(_flatten_schedule(schedules['archive_schedule'])))},
]

if config.get('subset_pages_enabled'):

    # Build a flat, multi-day-exploded event list from data/events.json.
    # We can't reuse `schedules` because that's already aggregated; the
    # subset path needs to filter individual events by year/month/KW.
    raw_events = json.loads(open(schedule_path, 'r').read())

    all_events_exploded = []
    for event in raw_events:
        if event['duration_seconds'] > 60 * 60 * 24:
            if event['all_day']:
                days = [d for d in utils.daterange(
                    utils.make_datetime(event['start']),
                    utils.make_datetime(event['end']),
                )]
            else:
                days = [d for d in utils.daterange(
                    datetime.fromisoformat(event['start']),
                    datetime.fromisoformat(event['end']),
                )]
            for i, day in enumerate(days):
                ec = event.copy()
                ec['event_day_num'] = i + 1
                ec['date'] = utils.ymd_string(day)
                ec['kw'] = utils.get_weeknum(day)
                all_events_exploded.append(ec)
        else:
            ec = event.copy()
            ec['event_day_num'] = 1
            all_events_exploded.append(ec)

    # Derive calendar year + calendar month for each event from `start`.
    # The data already has `kw_year` and `year`, but the latter is also
    # calendar-based and could differ from `kw_year` at week boundaries.
    for e in all_events_exploded:
        if e['all_day']:
            start_dt = utils.make_datetime(e['start'])
        else:
            start_dt = datetime.fromisoformat(e['start'])
        e['_cal_year'] = '{:04d}'.format(start_dt.year)
        e['_cal_month'] = '{:02d}'.format(start_dt.month)

    subset_years = sorted({e['kw_year'] for e in all_events_exploded if e.get('kw_year')})
    subset_months = sorted({(e['_cal_year'], e['_cal_month']) for e in all_events_exploded})
    subset_kws = sorted({(e['kw_year'], e['kw']) for e in all_events_exploded
                          if e.get('kw_year') and e.get('kw')})

    site_url = config.get('site_url', '').rstrip('/')

    def _build_subset_view(view_type, **kwargs):
        """Precompute label/desc/canonical/breadcrumbs for a subset page."""
        if view_type == 'year':
            y = kwargs['year']
            label = y
            desc = 'Music events in Munich in {}.'.format(y)
            canonical = '{}/{}/'.format(site_url, y)
            breadcrumbs = [('Home', site_url + '/'), (y, canonical)]
        elif view_type == 'month':
            y, m = kwargs['year'], kwargs['month']
            month_name = calendar.month_name[int(m)]
            label = '{} {}'.format(month_name, y)
            desc = 'Music events in Munich in {} {}.'.format(month_name, y)
            canonical = '{}/{}/{}/'.format(site_url, y, m)
            breadcrumbs = [('Home', site_url + '/'),
                           (y, '{}/{}/'.format(site_url, y)),
                           (label, canonical)]
        elif view_type == 'kw':
            y, k = kwargs['year'], kwargs['kw']
            label = 'KW {} / {}'.format(k, y)
            desc = 'Music events in Munich in week {} of {}.'.format(int(k), y)
            canonical = '{}/{}/W{}/'.format(site_url, y, k)
            breadcrumbs = [('Home', site_url + '/'),
                           (y, '{}/{}/'.format(site_url, y)),
                           ('KW {}'.format(k), canonical)]
        else:
            raise ValueError(view_type)
        return {
            'type': view_type,
            'label': label,
            'desc': desc,
            'canonical': canonical,
            'breadcrumbs': breadcrumbs,
            **kwargs,
        }

    def _render_subset(filter_fn, subset_view, out_path):
        filtered = [e for e in all_events_exploded if filter_fn(e)]
        if not filtered:
            return None

        aggregated = utils.aggregate_schedule(filtered, groups=['kw_year', 'kw', 'date'])

        for y in aggregated:
            for kw in aggregated[y]:
                for dt in aggregated[y][kw]:
                    for ev in aggregated[y][kw][dt]:
                        ev['date_datetime'] = utils.make_date(ev['date'], config.get('timezone')) if ev['date'] else None
                        ev['start_datetime'] = utils.ensure_tz(datetime.fromisoformat(ev['start']), config.get('timezone')) if ev['start'] else None
                        ev['end_datetime'] = utils.ensure_tz(datetime.fromisoformat(ev['end']), config.get('timezone')) if ev['end'] else None

        # Sort ascending at every level (subset pages show oldest -> newest)
        aggregated = {y: aggregated[y] for y in sorted(aggregated.keys())}
        for y in aggregated:
            aggregated[y] = {kw: aggregated[y][kw] for kw in sorted(aggregated[y].keys())}
            for kw in aggregated[y]:
                aggregated[y][kw] = {dt: aggregated[y][kw][dt] for dt in sorted(aggregated[y][kw].keys())}
                for dt in aggregated[y][kw]:
                    aggregated[y][kw][dt] = sorted(aggregated[y][kw][dt],
                                                    key=lambda x: x['start_datetime'])

        sub_dates = [dt for y in aggregated for kw in aggregated[y] for dt in aggregated[y][kw]]
        sub_date_weekdays = {
            dt: utils.get_weekday(utils.make_date(dt, tz=config.get('timezone')))
            for dt in sub_dates
        }

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w') as f:
            f.write(template.render(
                config=config,
                schedule=aggregated,
                news=[],
                venues=venues,
                date_weekdays=sub_date_weekdays,
                today=utils.get_today(),
                today_datetime=utils.get_today(return_date_obj=True),
                now=datetime.now(pytz.timezone(config.get('timezone'))),
                path_exists=lambda x: os.path.exists(x),
                truncate=lambda x, n: x[:n] + '...' if len(x) > n else x,
                value_display=lambda x: x if x is not None else '',
                dict_has_key=utils.dict_has_key,
                archive=False,
                subset_view=subset_view,
            ))

        return latest_change(filtered)

    def _add_subset_page(path, lastmod):
        # Only list a page in the sitemap when _render_subset actually wrote it
        # (it returns None and skips when no events match the filter).
        if lastmod is not None:
            sitemap_pages.append({'path': path, 'lastmod': _w3c(lastmod)})

    for y in subset_years:
        lm = _render_subset(
            filter_fn=lambda e, y=y: e.get('kw_year') == y,
            subset_view=_build_subset_view('year', year=y),
            out_path='site/{}/index.html'.format(y),
        )
        _add_subset_page('{}/'.format(y), lm)

    for y, m in subset_months:
        lm = _render_subset(
            filter_fn=lambda e, y=y, m=m: e['_cal_year'] == y and e['_cal_month'] == m,
            subset_view=_build_subset_view('month', year=y, month=m),
            out_path='site/{}/{}/index.html'.format(y, m),
        )
        _add_subset_page('{}/{}/'.format(y, m), lm)

    for y, k in subset_kws:
        lm = _render_subset(
            filter_fn=lambda e, y=y, k=k: e['kw_year'] == y and e['kw'] == k,
            subset_view=_build_subset_view('kw', year=y, kw=k),
            out_path='site/{}/W{}/index.html'.format(y, k),
        )
        _add_subset_page('{}/W{}/'.format(y, k), lm)


# generate sitemap
# `now` is still passed because the github-pages branch's sitemap.j2 carries an
# extra hardcoded theater URL block that references it (content branches diverge).
with open('site/sitemap.xml', 'w') as f:
    f.write(sitemap_template.render(config = config,
                                    pages = sitemap_pages,
                                    now = datetime.now(pytz.timezone(config.get('timezone'))),
                                    default_lastmod = _w3c(datetime.now(pytz.timezone(config.get('timezone'))))
                                    ))

# generate robots.txt pointing crawlers at the sitemap
with open('site/robots.txt', 'w') as f:
    f.write('User-agent: *\nAllow: /\n\nSitemap: {}/sitemap.xml\n'.format(
        config.get('site_url', '').rstrip('/')))