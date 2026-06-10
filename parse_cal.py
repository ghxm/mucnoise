import json
import logging
from collections import Counter
from datetime import datetime, timedelta

import pytz
import recurring_ical_events

import utils
from event import Event


logger = logging.getLogger(__name__)


def parse_cal(cal, allow_unaccepted=False, always_allow_senders=None,
              site_owner_email=None, include_recurring_events_days=14):
    """Walk an icalendar.Calendar and return a list of Event objects.

    Recurring events are expanded to single occurrences for the next
    `include_recurring_events_days` days. Non-recurring events pass through
    unchanged. A UID-occurrence count dedupes the base recurring component
    so it isn't emitted alongside its expansions.
    """
    always_allow_senders = always_allow_senders or []

    raw_recurring = recurring_ical_events.of(cal, components=["VEVENT"]).between(
        (2022, 3, 14),
        datetime.now(pytz.utc) + timedelta(days=include_recurring_events_days),
    )

    all_components = [e for e in cal.walk()]
    uid_counts = Counter([e['UID'] for e in raw_recurring if 'UID' in e.keys()])

    components = (
        [e for e in all_components if 'UID' in e.keys() and uid_counts[e['UID']] <= 1]
        + [e for e in raw_recurring if 'UID' in e.keys() and uid_counts[e['UID']] > 1]
    )

    events = []
    for component in components:
        try:
            ev = Event.from_ical_component(
                component,
                owner_email=site_owner_email,
                allow_unaccepted=allow_unaccepted,
                always_allow_senders=always_allow_senders,
            )
        except Exception as e:
            logger.warning(
                "event_parse_failed",
                extra={"uid": str(component.get("UID", "")), "error": str(e)},
            )
            continue
        if ev is not None:
            events.append(ev)
    return events


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s %(message)s',
)

try:
    config = utils.get_config()
except Exception as e:
    raise ValueError('Could not read config. Error: ' + str(e))

try:
    cal = utils.read_cal(config.get('cal_uri'))
except Exception as e:
    raise ValueError('Could not read calendar. Error: ' + str(e))

events = parse_cal(
    cal,
    allow_unaccepted=config.get('allow_unaccepted'),
    always_allow_senders=config.get('always_allow_senders'),
    site_owner_email=config.get('site_owner_email'),
    include_recurring_events_days=int(config.get('recurring_events_days', 14)),
)

logger.info("parsed_events", extra={"count": len(events)})


def _dump(event):
    # The old parser omitted last_modified when missing rather than emitting
    # null. Drop it here to keep the JSON/CSV/ICS/RSS output keys identical.
    d = event.model_dump()
    if d.get('last_modified') is None:
        d.pop('last_modified', None)
    return d


event_dicts = [_dump(e) for e in events]

outpaths = [
    utils.path_to_data_folder('events.json'),
    utils.path_to_data_folder('events.csv'),
    utils.path_to_data_folder('events.ics'),
    utils.path_to_data_folder('events.rss'),
]

for outp in outpaths:
    try:
        if outp.endswith('.json'):
            with open(outp, 'w') as f:
                json.dump(utils.schedule_to_json(event_dicts), f, indent=4)
        elif outp.endswith('.csv'):
            with open(outp, 'w') as f:
                f.write(utils.schedule_to_csv(event_dicts))
        elif outp.endswith('.ics'):
            with open(outp, 'w') as f:
                f.write(utils.schedule_to_ics(event_dicts))
        elif outp.endswith('.rss'):
            with open(outp, 'w') as f:
                f.write(utils.schedule_to_rss(event_dicts))
    except Exception as e:
        logger.error("output_write_failed", extra={"path": outp, "error": str(e)})
