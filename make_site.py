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


# read in schedule
schedule_str = open(schedule_path, 'r').read()

schedule = json.loads(schedule_str)


schedule = utils.remove_past_events(schedule, cutoff_date=utils.ensure_tz(datetime.now(), tz=config.get('timezone')) + timedelta(hours=2))

# if an event is longer than 24h add it for each day
schedule_modified = []

for event in schedule:
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

schedule = schedule_modified


# aggregate schedule by day
schedule = utils.aggregate_schedule(schedule, groups=['year','kw','date'])

# make start_datetime and end_datetime into datetime objects
for year in schedule.keys():
    for kw in schedule[year].keys():
        for date in schedule[year][kw].keys():
            for event in schedule[year][kw][date]:
                event['date_datetime'] = utils.make_date(event['date'], config.get('timezone')) if event['date'] is not None else None
                event['start_datetime'] = utils.ensure_tz(datetime.fromisoformat(event['start']), config.get('timezone')) if event['start'] is not None else None
                event['end_datetime'] = utils.ensure_tz(datetime.fromisoformat(event['end']), config.get('timezone')) if event['end'] is not None else None

# get a dict of date-weekdays
## get all dates
dates = []
for year in schedule.keys():
    for kw in schedule[year].keys():
        for date in schedule[year][kw].keys():
            dates.append(date)


date_weekdays = {date: utils.get_weekday(utils.make_date(date, tz=config.get('timezone'))) for date in dates}

# sort by start_datetime
for year in schedule.keys():
    for kw in schedule[year].keys():
        for date in schedule[year][kw].keys():
            schedule[year][kw][date] = sorted(schedule[year][kw][date], key=lambda x: x['start_datetime'])


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

# @TODO replace individual variables with config dict

# Write the rendered template to a file
with open('site/index.html', 'w') as f:
    f.write(template.render(config = config,
                            schedule=schedule,
                            venues=venues,
                            date_weekdays=date_weekdays,
                            today = utils.get_today(),
                            today_datetime = utils.get_today(return_date_obj=True),
                            now = datetime.now(pytz.timezone(config.get('timezone'))),
                            path_exists = lambda x: os.path.exists(x),
                            truncate = lambda x, n: x[:n] + '...' if len(x) > n else x,
                            value_display = lambda x: x if x is not None else '',
                            dict_has_key = utils.dict_has_key
                            )
                            )

