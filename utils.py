import re
import requests
import yaml
import icalendar
from datetime import datetime, timedelta, date
import pytz
import os
import itertools
from collections import defaultdict


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
        yaml = yaml_match.group(0)
        text = text.replace(yaml, '')

        # try to parse the yaml to exclude yases where --- might have been added for fun
        try:
            yaml = yaml.safe_load(yaml)
        except yaml.YAMLError as exc:
            yaml = None

        if yaml is not None:

            return yaml, text

    # hard (without ---)
    yaml_match = re.findall(r'^[a-z0-9]+:\s.*\n*(?:[ \t]+.*(?:\n|$))*', text, flags=re.MULTILINE)

    yaml = ''
    for m in yaml_match:
        yaml += m + '\n' if not m.endswith('\n') else m
        text = text.replace(m, '')

    return yaml, text

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
            else:
                event_json[key] = value

        schedule_json.append(event_json)

    return schedule_json

def schedule_to_ics(schedule):
    import icalendar

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
    import pandas as pd

    df = pd.DataFrame.from_records(schedule)
    csv = df.to_csv(index=False, quoting=csv.QUOTE_ALL, sep=',')

    return csv

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




def ymd_string (in_date):
    from datetime import datetime, timedelta, date

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

def get_today(dt = False, tz = 'Europe/Berlin'):

    # set timezone
    tz = pytz.timezone(tz)

    if dt:
        return datetime.now(tz).date()
    else:

        return datetime.now(tz).date().strftime('%Y-%m-%d')

def remove_past_events(schedule, date=get_today(dt=True)):

    # filter past events
    schedule = [event for event in schedule if make_date(datetime.fromisoformat(event['end']), 'Europe/Berlin') >= date if
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
