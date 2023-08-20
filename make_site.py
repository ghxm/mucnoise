import jinja2
import utils
import os
import json
from datetime import datetime, timedelta, date
import pytz
import shutil
import warnings
import yaml


config = utils.get_config(get_all=True)

schedule_path = utils.path_to_data_folder('events.json')


# Create a Jinja2 environment
env = jinja2.Environment(loader=jinja2.FileSystemLoader('templates'), extensions=['jinja2.ext.loopcontrols'])

# Load a template
template = env.get_template('index.j2')
sitemap_template = env.get_template('sitemap.j2')


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
    schedule_ = utils.aggregate_schedule(schedule_, groups=['year', 'kw', 'date'])

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



# copy files from data to site/static/
data = [f for f in os.listdir(utils.path_to_data_folder()) if not  os.path.isdir(os.path.join(utils.path_to_data_folder(), f)) and not f.startswith('.') or f.startswith('_')]

static_folder = utils.path_to_site_folder('static')

for f in data:
    shutil.copyfile(utils.path_to_data_folder(f), os.path.join(static_folder, f))


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
                            venues=venues,
                            date_weekdays=date_weekdays['archive_schedule'],
                            today = utils.get_today(),
                            today_datetime = utils.get_today(return_date_obj=True),
                            now = datetime.now(pytz.timezone(config.get('timezone'))),
                            path_exists = lambda x: os.path.exists(x),
                            truncate = lambda x, n: x[:n] + '...' if len(x) > n else x,
                            value_display = lambda x: x if x is not None else '',
                            dict_has_key = utils.dict_has_key,
                            archive = True
                            )
                            )

# Write the rendered template to a file
with open('site/index.html', 'w') as f:
    f.write(template.render(config = config,
                            schedule=schedules['schedule'],
                            venues=venues,
                            date_weekdays=date_weekdays['schedule'],
                            today = utils.get_today(),
                            today_datetime = utils.get_today(return_date_obj=True),
                            now = datetime.now(pytz.timezone(config.get('timezone'))),
                            path_exists = lambda x: os.path.exists(x),
                            truncate = lambda x, n: x[:n] + '...' if len(x) > n else x,
                            value_display = lambda x: x if x is not None else '',
                            dict_has_key = utils.dict_has_key,
                            archive = False
                            )
                            )


# generate sitemap
with open('site/sitemap.xml', 'w') as f:
    f.write(sitemap_template.render(config = config,
                                    pages = ['', 'archive'],
                                    now = datetime.now(pytz.timezone(config.get('timezone')))
                                    ))