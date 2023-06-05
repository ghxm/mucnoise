import requests
import icalendar
import os
import json
import recurring_ical_events
from collections import Counter
from datetime import datetime, timedelta, date
import pytz
import utils
import yaml
import warnings
import re

# function to parse the ics file and return a list of events
def parse_cal(cal, outpaths = [], allow_unaccepted = False, always_allow_senders = [], site_owner_email = None):

    events = []

    # get recurring events for the next three months
    raw_recurring_events = recurring_ical_events.of(cal, components=["VEVENT"]).between((2022,3,14), datetime.now(pytz.utc) + timedelta(days=14))

    # get ALL events
    raw_events = [e for e in cal.walk()]

    # count UIDs occurences in raw_events
    c = Counter([e['UID'] for e in raw_recurring_events if 'UID' in e.keys()])

    # non-recurring events without constraint + recurring events 3 months into to the future
    raw_events = [e for e in raw_events if 'UID' in e.keys() and c[e['UID']] <= 1] + [e for e in raw_recurring_events if 'UID' in e.keys() and c[e['UID']] > 1]

    for event in raw_events:

        event_dict = {}

        # get UID from event if set
        try:
            event_dict['uid'] = event.get('UID')

            event_dict['uid'] = re.sub(r'@.*', '', event_dict['uid'])

        except:
            raise Exception('No UID found in event! Ics file invalid?')

        try:
            # check for EXDATE rules in recurring events
            if 'EXDATE' in event.keys():
                if isinstance(event['EXDATE'], icalendar.prop.vDDDLists):
                    exdates = [d.dt for d in event['EXDATE'].dts]
                elif isinstance(event['EXDATE'], list):
                    exdates = [d.dts[0].dt for d in event['EXDATE']]
                if event['DTSTART'].dt in exdates:
                    continue

        except:
            pass

        # check whether event is actually an event
        if event.name != 'VEVENT':
            continue

        # check whether event is cancelled
        if event.get('STATUS') == 'CANCELLED':
            event_dict['cancelled'] = True
        else:
            event_dict['cancelled'] = False

        try:

            partstat = [a for a in event.get('attendee') if a.params.get('CN', '') == str(site_owner_email)][0].params.get('PARTSTAT')

        except:

            partstat = None

        if partstat is not None:
            if partstat == 'DECLINED':
                continue
            elif partstat in ['TENTATIVE', 'NEEDS-ACTION']:
                description = utils.remove_html_tags(description)

        # check whether event is confirmed
        sender = event.get('ORGANIZER', None)

        if sender is not None:

            sender = sender.split(':')[1]

            if sender not in always_allow_senders:

                if not allow_unaccepted:

                    if partstat is not None:
                        if partstat != 'ACCEPTED':
                            continue
                    else:

                        warnings.warn(f'Could not get parstat for event with UID {event.get("uid")}, skipping.')
                        continue



        # check whether event is all day
        if isinstance(event.get('DTSTART').dt, datetime):
            event_dict['all_day'] = False
        else:
            event_dict['all_day'] = True

        # check whether event is recurring
        if event.get('RRULE') is not None:
            event_dict['recurring'] = True
        else:
            event_dict['recurring'] = False

        # check whether event is a multi-day event
        if (not isinstance(event.get('DTSTART').dt, datetime) and event.get('DTSTART').dt != event.get('DTEND').dt) or (isinstance(event.get('DTSTART').dt, datetime) and event.get('DTSTART').dt.date() != event.get('DTEND').dt.date()):
            event_dict['multi_day'] = True
        else:
            event_dict['multi_day'] = False


        # GET EVENT ATTRIBUTES

        # get start time from event
        try:
            event_dict['start'] = event.get('DTSTART').dt
        except:
            raise Exception('No start time found in event! Ics file invalid?')

        # get end time from event
        try:
            event_dict['end'] = event.get('DTEND').dt
        except:
            raise Exception('No end time found in event! Ics file invalid?')

        # get duration from event
        try:
            event_dict['duration_seconds'] = (event_dict['end'] - event_dict['start']).total_seconds()
        except:
            raise Exception('Could not calculate duration for event!')



        # get url from event if set
        try:
            event_dict['url'] = event.get('URL')
        except:
            event_dict['url'] = None

        # get location from event if set
        try:
            event_dict['location'] = event.get('LOCATION')
        except:
            event_dict['location'] = None

        # get title from event if set
        try:
            event_dict['title'] = event.get('SUMMARY')
        except:
            event_dict['title'] = None


        # get description from event if set
        try:
            event_dict['description'] = event.get('DESCRIPTION')
        except:
            event_dict['description'] = None


        # PARSE DESCRIPTION, ADD/OVERWRITE CUSTOM ATTRIBUTES

        if event_dict['description'] is not None:

            yaml_dict = None

            # try to parse yaml from description
            yaml_desc, description = utils.split_yaml_text(event_dict['description'])

            if yaml_desc is not None:
                # parse yaml and add to event_dict
                try:
                    yaml_dict = yaml.safe_load(yaml_desc)
                except:
                    warnings.warn('Could not parse yaml from description. Ignoring.')
                    yaml_dict = None

            # parse yaml and add to event_dict
            if yaml_dict is not None:
                event_dict.update(yaml_dict)

            # parse description and add to event_dict
            if description is not None:
                event_dict['description'] = utils.clean_description(description)


        # ADD DATE ATTRIBUTES
        try:
            event_dict['year'] = utils.get_year(event_dict['start'])
        except:
            event_dict['year'] = None

        try:
            event_dict['date'] = utils.ymd_string(event_dict['start'])
        except:
            event_dict['date'] = None

        try:
            event_dict['kw'] = utils.get_weeknum(event_dict['start'])
        except:
            event_dict['kw'] = None

        try:
            event_dict['weekday_start'] = utils.get_weekday(event_dict['start'])
        except:
            event_dict['weekday_start'] = None

        try:
            if event_dict['all_day']:
                event_dict['weekday_end'] = utils.get_weekday(event_dict['end'] - timedelta(days=1))
            else:
                event_dict['weekday_end'] = utils.get_weekday(event_dict['end'])
        except:
            event_dict['weekday_end'] = None


        # add event to events list
        events.append(event_dict)

    return events



# get cal url from environment vars
cal_uri = os.environ.get('CAL_URI')

if cal_uri is None:
    raise ValueError('No calendar URI found in environment variables.')

# get cal
try:
    cal = utils.read_cal(cal_uri)
except Exception as e:
    raise ValueError('Could not read calendar. Error: ' + str(e))

# get outpaths from environment vars
outpaths = [
    utils.path_to_data_folder('events.json'),
    utils.path_to_data_folder('events.csv'),
    utils.path_to_data_folder('events.ics')
]

if len(outpaths) == 0:
    warnings.warn('No output paths found in environment variables.')

try:
    site_owner_email = os.environ.get('SITE_OWNER_EMAIL')
except:
    site_owner_email = None
    warnings.warn('No site owner email found in environment variables.')

# get allow_unaccepted from environment vars
allow_unaccepted = os.getenv("ALLOW_UNACCEPTED", 'False').lower() in ('true', '1', 't')

# get always_allow_senders from environment vars
always_allow_senders = json.loads(os.environ.get('ALWAYS_ALLOW_SENDERS', '[]'))

# parse cal
events = parse_cal(cal, outpaths, allow_unaccepted, always_allow_senders, site_owner_email)

# write events to outpaths
for outp in outpaths:
    if outp.endswith('.json'):
        events_json = utils.schedule_to_json(events)

        with open(outp, 'w') as f:
            json.dump(events_json, f, indent=4)

    elif outp.endswith('.csv'):
        events_csv = utils.schedule_to_csv(events)

        with open(outp, 'w') as f:
            f.write(events_csv)

    elif outp.endswith('.ics'):

        events_ics = utils.schedule_to_ics(events)

        with open(outp, 'w') as f:
            f.write(events_ics)









# get auto-trust addresses from environment data