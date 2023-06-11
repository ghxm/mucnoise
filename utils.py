import re
import requests
import yaml
import icalendar
from datetime import datetime, timedelta, date
import pytz
import os
import itertools
from collections import defaultdict
from feedgen.feed import FeedGenerator
import warnings
import json
import icalendar
import pandas as pd


def get_config(prefix = "", get_all = False):

    config = {}

    # get cal url from environment vars
    config['cal_uri'] = os.environ.get(prefix + 'CAL_URI')
    if config['cal_uri'] is None:
        del config['cal_uri']
        warnings.warn('No calendar URI found in environment variables.')

    # get cal url from environment vars
    config['cal_email'] = os.environ.get(prefix + 'CAL_EMAIL')
    if config['cal_email'] is None:
        del config['cal_email']
        warnings.warn('No calendar E-mail found in environment variables.')

    config['timezone'] = os.environ.get(prefix + 'TIMEZONE')
    if config['timezone'] is None:
        warnings.warn('No timezone found in environment variables. Assuming machine local timezone.')
        config['timezone'] = datetime.now().astimezone().tzinfo

    # get site title
    config['site_title'] = os.environ.get(prefix + 'SITE_TITLE')
    if config['site_title'] is None:
        del config['site_title']
        warnings.warn('No site title found in environment variables.')

    # get site url
    config['site_url'] = os.environ.get(prefix + 'SITE_URL')
    if config['site_url'] is None:
        del config['site_url']
        warnings.warn('No site url found in environment variables.')

    config['site_description'] = os.environ.get(prefix + 'SITE_DESCRIPTION', 'Event repsitory')
    if config['site_description'] is None:
        del config['site_description']
        warnings.warn('No site description found in environment variables.')

    # get site owner email
    config['site_owner_email'] = os.environ.get(prefix + 'SITE_OWNER_EMAIL')
    if config['site_owner_email'] is None:
        del config['site_owner_email']
        warnings.warn('No site owner email found in environment variables.')

    # get allow_unaccepted from environment vars
    config['allow_unaccepted'] = os.getenv(prefix + 'ALLOW_UNACCEPTED', 'False').lower() in ('true', '1', 't')

    # get always_allow_senders from environment vars
    config['always_allow_senders'] = json.loads(os.environ.get(prefix + 'ALWAYS_ALLOW_SENDERS', '[]'))

    # get recurring events days into the future from environment vars
    config['recurring_events_days'] = float(os.getenv(prefix + 'RECURRING_EVENTS_DAYS', '14'))

    if get_all:
        # get all environment variables
        config.update({key.lower(): val for key, val in dict(os.environ).items() if key.startswith(prefix)})

    return config

def dict_has_key(dict, key):

    if isinstance(key, (str, int, float)):
        return key in dict

    if callable(key):

        if any([key(k) for k in dict.keys()]):
            return True
        else:
            return False

def path_to_folder(filename=None, folder=None):
    """
    Get path to data folder.
    """

    if folder is None:
        raise ValueError('No folder specified.')

    if not folder.endswith('/'):
        folder = folder + '/'



    # get path of current file
    path = os.path.dirname(os.path.realpath(__file__))

    if filename is not None:
        return os.path.join(path, folder, filename)
    else:

        # get path of data folder
        return os.path.join(path, folder)

def path_to_site_folder(filename=None):
    """
    Get path to data folder.
    """

    return path_to_folder(filename, 'site/')
def path_to_data_folder(filename=None):
    """
    Get path to data folder.
    """

    return path_to_folder(filename, 'data/')

def read_cal(ics):

    if ics.startswith('http'):
        ics_string = requests.get(ics).text
    else:
        try:
            ics_string = open(ics).read()
        except FileNotFoundError:
            ics_string = ics

    cal = icalendar.Calendar.from_ical(ics_string)

    return cal

def remove_html_tags(text):
    """Remove html tags from a string"""
    clean = re.compile('<.*?>')
    return re.sub(clean, '', text)


def fix_html(text):
    """Fix html tags"""
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')

    return text

def split_yaml_text(text):

    # try to identify the yaml part

    # easy (with ---)
    yaml_match = re.search(r'^---\n.*\n---\n', text, flags=re.MULTILINE | re.DOTALL)

    if yaml_match:
        yaml_str = yaml_match.group(0)
        text = text.replace(yaml_str, '')

        # try to parse the yaml to exclude yases where --- might have been added for fun
        try:
            yaml.safe_load_all(yaml_str)
        except yaml.YAMLError as exc:
            yaml_str = None

        if yaml_str is not None:

            return yaml_str, text

    # hard (without ---)
    yaml_match = re.findall(r'^[a-z0-9]+:\s.*\n*(?:[ \t]+.*(?:\n|$))*', text, flags=re.MULTILINE)

    yaml_str = ''
    for m in yaml_match:
        yaml_str += m + '\n' if not m.endswith('\n') else m
        text = text.replace(m, '')

    return yaml_str, text

def clean_description(text):

    description = text

    description = re.sub('Join with Google Meet.*', '', description, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)
    description = re.sub('^[.]+(.|[\n\r\s])*skype(.|[\n\r\s])*', '', description, flags=re.IGNORECASE | re.MULTILINE)
    description = re.sub('^[.]+(.|[\n\r\s])*google(.|[\n\r\s])*', '', description, flags=re.IGNORECASE | re.MULTILINE)
    description = re.sub('^[.]+(.|[\n\r\s])*Google Meet(.|[\n\r\s])*', '', description,
                         flags=re.IGNORECASE | re.MULTILINE)
    description = re.sub('^.*Google Meet(.|[\n\r\s])*', '', description, flags=re.IGNORECASE | re.MULTILINE)
    description = re.sub('^.*meet\.(.|[\n\r\s])*', '', description, flags=re.IGNORECASE | re.MULTILINE)
    description = re.sub('^.*skype\.(.|[\n\r\s])*', '', description, flags=re.IGNORECASE | re.MULTILINE)
    description = re.sub('^.*google\.(.|[\n\r\s])*', '', description, flags=re.IGNORECASE | re.MULTILINE)
    description = re.sub('Dieser Termin enthält einen Videoanruf.*', '', description,
                         flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)
    description = re.sub('Teilnehmen.*', '', description, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)
    description = re.sub('This event contains.*', '', description, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)
    description = re.sub('This event has.*', '', description, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)

    return description


def schedule_to_json(schedule):

    schedule_json = []

    for event in schedule:

        event_json = {}

        for key, value in event.items():

            if key == 'start':
                event_json['start'] = value.isoformat()
            elif key == 'end':
                event_json['end'] = value.isoformat()
            elif key == 'created':
                event_json['created'] = value.isoformat()
            elif key == 'last_modified':
                event_json['last_modified'] = value.isoformat()
            else:
                event_json[key] = value

        schedule_json.append(event_json)

    return schedule_json

def schedule_to_ics(schedule):

    cal = icalendar.Calendar()

    for event in schedule:
        cal_event = icalendar.Event()
        for key, value in event.items():
            if key == 'start':
                cal_event.add('dtstart', value)
            elif key == 'end':
                cal_event.add('dtend', value)
            else:
                cal_event.add(key, value)
        cal.add_component(cal_event)

    return cal.to_ical().decode('utf-8')

def schedule_to_csv(schedule):
    import csv

    df = pd.DataFrame.from_records(schedule)
    csv = df.to_csv(index=False, quoting=csv.QUOTE_ALL, sep=',')

    return csv


def schedule_to_rss(schedule, author_email = get_config().get('site_owner_email', ''), url = get_config().get('site_url', ''), title = get_config().get('site_title', ''), content = get_config().get('site_description', ''), tz = get_config().get('timezone', 'Europe/Berlin')):

    if not str(url).endswith('/'):
        url += '/'

    tz = pytz.timezone(tz)

    fg = FeedGenerator()
    fg.id(str(url))
    fg.title(str(title))
    fg.description(str(content))
    fg.author({'name': str(title), 'email': str(author_email)})
    fg.link(href=str(url) + 'static/events.rss', rel='self')
    fg.language('en')
    fg.lastBuildDate(datetime.now(tz))

    for event in schedule:

            fe = fg.add_entry()
            fe.guid(str(event['uid']))
            fe.title(str(event.get('date')) + ': ' + str(event.get('title', '')))
            fe.link(href=event.get('url'))

            if 'created' in event:
                pub_date = event['created']
            else:
                pub_date = datetime.now(tz)

            if isinstance(pub_date, datetime):
                pub_date = pub_date.astimezone(tz)
            elif isinstance(pub_date, date):
                pub_date = datetime.combine(pub_date, datetime.min.time()).astimezone(tz)
            fe.pubDate(pub_date)


            if 'last_modified' in event:
                last_modified = event['last_modified']

                if isinstance(last_modified, datetime):
                    last_modified = last_modified.astimezone(tz)
                elif isinstance(last_modified, date):
                    last_modified = datetime.combine(last_modified, datetime.min.time()).astimezone(tz)
                fe.updated(last_modified)



            content = ''

            for key, value in event.items():
                if key not in ['uid', 'title', 'url', 'duration_seconds', 'kw', 'year', 'date', 'weekday_end', 'description', 'created']:
                    content += '\n\n' + str(key) + ': ' + str(value)

            content += '\n\n' + str(event['description'])

            fe.content(content)
            fe.source(str(url) + '#' + str(event['uid']))

            fe.description(str(event['description'][:80] + '...'))


    return fg.rss_str(pretty=True).decode('utf-8')

def daterange(start_date, end_date):
    for n in range(int((end_date - start_date).days)):
        yield start_date + timedelta(n)

def make_datetime(in_date, time = "00:00", tz="Europe/Berlin"):
    """
    Make datetime object from date and time.
    """

    if isinstance(in_date, datetime):
        in_date = in_date.date()
    elif isinstance(in_date, date):
        in_date = ymd_string(in_date)

    datetime_str = in_date + " " + time

    # create new date object

    # check date format (DD.MM.YYYY or YYYY-MM-DD)
    if len(in_date.split('.')) == 3:

        # format: DD.MM.YYYY
        format = "%d.%m.%Y %H:%M"

    else:

        # format: YYYY-MM-DD
        format = "%Y-%m-%d %H:%M"

    datetime_obj = datetime.strptime(datetime_str, format)


    # set timezone
    tz = pytz.timezone(tz)
    datetime_obj = tz.localize(datetime_obj)

    return datetime_obj

def make_date(in_date, tz):

    if isinstance(in_date, datetime):
        result = in_date.date()
    elif isinstance(in_date, date):
        result = in_date
    else:
        result = make_datetime(in_date, '00:00', tz).date()

    return result


def ensure_tz(dt, tz = "Europe/Berlin"):
    """
    Ensure that datetime object has timezone.
    """

    if dt.tzinfo is None:
        dt = pytz.timezone(tz).localize(dt)

    return dt

def ymd_string (in_date):


    # try to parse date
    if isinstance(in_date, str):
        try:
            out_date = datetime.strptime(in_date, '%d.%m.%Y')
        except ValueError:
            out_date = datetime.strptime(in_date, '%Y-%m-%d')
    elif isinstance(in_date, (datetime, date)):
        out_date = in_date
    else:
        raise ValueError('Date must be string or datetime object.')

    # convert to string
    out_date = out_date.strftime('%Y-%m-%d')

    return out_date

def get_weekday(date):

    return date.strftime('%A')

def get_year(date):

    return date.strftime('%Y')


def get_weeknum(date):

    # retrun the week number
    return date.strftime('%V')

def get_today(return_date_obj = False, tz ='Europe/Berlin'):

    # set timezone
    tz = pytz.timezone(tz)

    if return_date_obj:
        return datetime.now(tz).date()
    else:

        return datetime.now(tz).date().strftime('%Y-%m-%d')

def remove_past_events(schedule, cutoff_date=get_today(return_date_obj=True)):



    if isinstance(cutoff_date, datetime):
        # keep events that end before cutoff datetime
        schedule = [event for event in schedule if ensure_tz(datetime.fromisoformat(event['end'])) >= cutoff_date]


    elif isinstance(cutoff_date, date):
        # keep events that end on cutoff date

        schedule = [event for event in schedule if make_date(datetime.fromisoformat(event['end']), 'Europe/Berlin') >= cutoff_date if
                    event['end'] != '' and event['end'] is not None]


    return schedule

def nested_set(dic, keys, value):
    for key in keys[:-1]:
        dic = dic.setdefault(key, {})
    dic[keys[-1]] = value

def aggregate_schedule(schedule, groups = []):

    # sort by groups
    schedule.sort(key=lambda x: tuple(x[g] for g in groups))

    # group by groups
    schedule_grouped = itertools.groupby(schedule, key=lambda x: tuple(x[g] for g in groups))

    # create a dict for the aggregated schedule with the identified groups
    schedule_agg = defaultdict(dict)

    # set the events for each group(s)
    for group, events in schedule_grouped:

            nested_set(schedule_agg, group, list(events))


    return schedule_agg
