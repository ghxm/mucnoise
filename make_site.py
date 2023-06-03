import jinja2
import utils
import os
import json
from datetime import datetime
import pytz
import shutil

site_title = 'mucnoise.org'

schedule_path = utils.path_to_data_folder('events.json')


# Create a Jinja2 environment
env = jinja2.Environment(loader=jinja2.FileSystemLoader('templates'), extensions=['jinja2.ext.loopcontrols'])

# Load a template
template = env.get_template('index.j2')


# read in schedule
schedule_str = open(schedule_path, 'r').read()

schedule = json.loads(schedule_str)


schedule = utils.remove_past_events(schedule)


# aggregate schedule by day
schedule = utils.aggregate_schedule(schedule, groups=['year','kw','date'])

# make start_datetime and end_datetime into datetime objects
for year in schedule.keys():
    for kw in schedule[year].keys():
        for date in schedule[year][kw].keys():
            for event in schedule[year][kw][date]:
                event['date_datetime'] = utils.make_date(event['date'], 'Europe/Berlin') if event['date'] is not None else None
                event['start_datetime'] = datetime.fromisoformat(event['start']) if event['start'] is not None else None
                event['end_datetime'] = datetime.fromisoformat(event['end']) if event['end'] is not None else None

# get a dict of date-weekdays
## get all dates
dates = []
for year in schedule.keys():
    for kw in schedule[year].keys():
        for date in schedule[year][kw].keys():
            dates.append(date)


date_weekdays = {date: utils.get_weekday(utils.make_date(date, tz='Europe/Berlin')) for date in dates}


# copy files from data to site/static/
data = os.listdir(utils.path_to_data_folder())

static_folder = utils.path_to_site_folder('static')

for f in data:
    shutil.copyfile(utils.path_to_data_folder(f), os.path.join(static_folder, f))

# Write the rendered template to a file
with open('site/index.html', 'w') as f:
    f.write(template.render(site_title=site_title,schedule=schedule, date_weekdays=date_weekdays, today = utils.get_today(), today_datetime = utils.get_today(dt=True), now = datetime.now(pytz.timezone('Europe/Berlin')), path_exists = lambda x: os.path.exists(x)))

