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
def parse_cal(cal, outpaths = [], allow_unaccepted = False, always_allow_senders = [], site_owner_email = None, include_recurring_events_days = 14):

    events = []

    # get recurring events for the next three months
    raw_recurring_events = recurring_ical_events.of(cal, components=["VEVENT"]).between((2022,3,14), datetime.now(pytz.utc) + timedelta(days=include_recurring_events_days))

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

        # get created from event if set
        try:
            event_dict['created'] = event.get('CREATED').dt
        except:
            event_dict['created'] = None

        if event_dict['created'] is None:
            try:
                event_dict['created'] = event.get('DTSTAMP').dt
            except:
                del event_dict['created']
                event_dict['created'] = None

        # get last updated from event if set
        try:
            event_dict['last_modified'] = event.get('LAST-MODIFIED').dt
        except:
            pass

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

            site_owner_re = re.compile(r'(mailto:)?' + str(site_owner_email), flags=re.IGNORECASE)

            partstat = [a for a in event.get('attendee') if site_owner_re.search(a.params.get('CN', ''))][0].params.get('PARTSTAT') \
                if isinstance(event.get('attendee'), list) else event.get('attendee').params.get('PARTSTAT') \
                if event.get('attendee') is not None and site_owner_re.search(event.get('attendee')) \
                else None

        except:

            partstat = None

        if partstat is not None:
            if partstat == 'DECLINED':
                continue


        # check whether event is confirmed
        sender = event.get('ORGANIZER', None)
        attendee = event.get('ATTENDEE', None)

        sender_attendee = [sender] if sender is not None else []
        sender_attendee.extend([attendee[0]] if attendee is not None and isinstance(attendee, list) and len(attendee) > 0 else [])

        if len(sender_attendee) > 0:

            sender_attendee = [s.split(':')[1] for s in sender_attendee if s is not None]

            if not any([se for se in sender_attendee if se in always_allow_senders]):

                if not allow_unaccepted and partstat is None:

                    warnings.warn(f'Could not get parstat for event with UID {event.get("uid")}, skipping.')
                    continue
                elif not allow_unaccepted and partstat != 'ACCEPTED':

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

        if event_dict['location'] is not None:
            if '\n' in event_dict['location']:
                event_dict['location'] = event_dict['location'].split('\n')[0]
            elif ',' in event_dict['location']:
                event_dict['location'] = event_dict['location'].split(',')[0]

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

            # clean from html
            event_dict['description'] = utils.clean_description(event_dict['description'])

            # try to parse yaml from description
            yaml_desc, description = utils.split_yaml_text(event_dict['description'])

            if yaml_desc is not None:
                # parse yaml and add to event_dict
                try:
                    yaml_dicts = yaml.safe_load_all(yaml_desc)
                except:
                    warnings.warn('Could not parse yaml from description. Ignoring.')
                    yaml_dicts = []

            # parse yaml and add to event_dict
            for yaml_dict in yaml_dicts:
                if yaml_dict is not None and isinstance(yaml_dict, dict):
                    event_dict.update(yaml_dict)
                else:
                    warnings.warn('Could not parse yaml from description. Contininuing without YAML attributes.')


            # parse description and add to event_dict
            if description is not None:
                if partstat is not None:
                    if partstat in ['TENTATIVE', 'NEEDS-ACTION']:
                        event_dict['description'] = utils.clean_description(description)
                    else:
                        event_dict['description'] = description
                else:
                    event_dict['description'] = description

                # remove leading <br> tags
                event_dict['description'] = re.sub(r'^\s*(<.{0,1}br>[\s]*)+', '', event_dict['description'])


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
            event_dict['kw_year'] = utils.get_weeknum_year(event_dict['start'])
        except:
            event_dict['kw_year'] = None

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


# get config
try:
    config = utils.get_config()
except Exception as e:
    raise ValueError('Could not read config. Error: ' + str(e))

# get cal
try:
    cal = utils.read_cal(config.get('cal_uri'))
except Exception as e:
    raise ValueError('Could not read calendar. Error: ' + str(e))

# get outpaths from environment vars
outpaths = [
    utils.path_to_data_folder('events.json'),
    utils.path_to_data_folder('events.csv'),
    utils.path_to_data_folder('events.ics'),
    utils.path_to_data_folder('events.rss')
]

if len(outpaths) == 0:
    warnings.warn('No output paths found in environment variables.')


# parse cal
events = parse_cal(cal, outpaths, allow_unaccepted=config.get('allow_unaccepted'), always_allow_senders=config.get('always_allow_senders'), site_owner_email=config.get('site_owner_email'))

# write events to outpaths
for outp in outpaths:
    if outp.endswith('.json'):

        try:
            events_json = utils.schedule_to_json(events)
            with open(outp, 'w') as f:
                json.dump(events_json, f, indent=4)
        except Exception as e:
            w = 'Could not create json file. Error: ' + str(e)
            warnings.warn(w)


    elif outp.endswith('.csv'):

        try:
            events_csv = utils.schedule_to_csv(events)
            with open(outp, 'w') as f:
                f.write(events_csv)
        except Exception as e:
            w = 'Could not create csv file. Error: ' + str(e)
            warnings.warn(w)


    elif outp.endswith('.ics'):


        try:
            events_ics = utils.schedule_to_ics(events)
            with open(outp, 'w') as f:
                f.write(events_ics)
        except Exception as e:
            w = 'Could not create ics file. Error: ' + str(e)
            warnings.warn(w)



    elif outp.endswith('.rss'):

        try:
            events_rss = utils.schedule_to_rss(events)
            with open(outp, 'w') as f:
                f.write(events_rss)
        except Exception as e:
            w = 'Could not create rss feed. Error: ' + str(e)
            warnings.warn(w)

