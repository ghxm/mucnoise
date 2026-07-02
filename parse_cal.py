import json
import logging
from collections import Counter
from datetime import datetime, timedelta

import pytz
import recurring_ical_events

import utils
from event import Event, _derive_date_fields


logger = logging.getLogger(__name__)

# Sentinel values marking "do not propagate this field" on overwrite carriers.
# '__none__' is canonical; '<none>' only survives in real calendar fields
# because description-YAML values are HTML-stripped before parsing.
NONE_SENTINELS = ('__none__', '<none>')

# Calendar-level fields of a carrier event that patch the target by default.
DEFAULT_PATCH_FIELDS = ('title', 'location', 'description', 'url')


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


def _is_carrier(event):
    return 'overwrite' in (event.model_extra or {})


def _is_sentinel(value):
    return isinstance(value, str) and value.strip().lower() in NONE_SENTINELS


def _is_empty(value):
    if value is None:
        return True
    if isinstance(value, str) and (value.strip() == '' or _is_sentinel(value)):
        return True
    return False


def _as_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).lower() in ('true', '1', 't')


def _build_patch(carrier):
    """Translate a carrier event into (target_uid, set_values, delete_keys, overwrite_time).

    set_values are merged onto the target's dict; delete_keys are removed from
    it (clearing YAML-extra keys without serializing a literal None).
    """
    extras = dict(carrier.model_extra or {})
    target_uid = str(extras.pop('overwrite') or '').strip()

    controls = {
        k[len('overwrite_'):]: _as_bool(extras.pop(k))
        for k in [k for k in extras if k.startswith('overwrite_')]
    }
    overwrite_time = controls.pop('time', False)

    candidates = {f: getattr(carrier, f) for f in DEFAULT_PATCH_FIELDS}
    candidates.update(extras)

    set_values = {}
    delete_keys = set()
    for attr, val in candidates.items():
        rule = controls.pop(attr, None)
        if rule is False:
            continue
        if rule is True:
            if _is_empty(val):
                if attr in DEFAULT_PATCH_FIELDS:
                    set_values[attr] = None
                else:
                    delete_keys.add(attr)
            else:
                set_values[attr] = val
            continue
        if not _is_empty(val):
            set_values[attr] = val

    # Leftover True controls name YAML-extra keys the carrier doesn't carry a
    # value for: treat as "clear on target". Declared model fields outside
    # DEFAULT_PATCH_FIELDS (start, uid, ...) are not patchable this way.
    for attr, rule in controls.items():
        if not rule:
            continue
        if attr in Event.model_fields:
            logger.warning(
                "overwrite_control_ignored",
                extra={"uid": carrier.uid, "attr": attr},
            )
            continue
        delete_keys.add(attr)

    return target_uid, set_values, delete_keys, overwrite_time


def _time_patch(carrier):
    start, end = carrier.start, carrier.end
    all_day = not isinstance(start, datetime)
    if all_day:
        multi_day = start != end
    else:
        multi_day = start.date() != end.date()
    return {
        'start': start,
        'end': end,
        'all_day': all_day,
        'multi_day': multi_day,
        'duration_seconds': (end - start).total_seconds(),
        **_derive_date_fields(start, end, all_day),
    }


def _bump_last_modified(target, carrier):
    """RSS readers honor <updated>; reflect carrier edits on the patched event."""
    try:
        if carrier.last_modified is None:
            return {}
        if target.last_modified is None or carrier.last_modified > target.last_modified:
            return {'last_modified': carrier.last_modified}
    except TypeError:
        pass
    return {}


def _patch_event(target, set_values, delete_keys):
    data = {**target.model_dump(), **set_values}
    for k in delete_keys:
        data.pop(k, None)
    return Event.model_validate(data)


def _carrier_as_standalone(carrier):
    """Publish an orphaned carrier as a normal event: strip control keys,
    null/remove sentinel-valued fields."""
    data = carrier.model_dump()
    for k in [k for k in data if k == 'overwrite' or k.startswith('overwrite_')]:
        del data[k]
    for k, v in list(data.items()):
        if _is_sentinel(v):
            if k in Event.model_fields:
                data[k] = None
            else:
                del data[k]
    return Event.model_validate(data)


def apply_overwrites(events, show_orphaned=False):
    """Apply owner-created overwrite carriers to their target events.

    Carriers (events with an `overwrite: <uid>` description-YAML key) patch
    all events sharing the target uid and are dropped from the output. Time
    fields only propagate via `overwrite_time: true` and only when the patch
    is unambiguous (single target occurrence, non-recurring carrier).
    """
    carriers = [e for e in events if _is_carrier(e)]
    normal = [e for e in events if not _is_carrier(e)]
    if not carriers:
        return events

    # Expanded recurring carriers share uid and description; keep the first.
    seen = set()
    unique_carriers = []
    for c in carriers:
        if c.uid not in seen:
            seen.add(c.uid)
            unique_carriers.append(c)

    out = list(normal)
    patched_count = 0
    orphan_count = 0
    for carrier in unique_carriers:
        target_uid, set_values, delete_keys, overwrite_time = _build_patch(carrier)
        target_idx = [i for i, e in enumerate(out) if e.uid == target_uid] if target_uid else []

        if not target_idx:
            orphan_count += 1
            logger.warning(
                "overwrite_orphaned",
                extra={"uid": carrier.uid, "target": target_uid, "shown": show_orphaned},
            )
            if show_orphaned:
                out.append(_carrier_as_standalone(carrier))
            continue

        if overwrite_time:
            if len(target_idx) > 1 or carrier.recurring:
                logger.warning(
                    "overwrite_time_skipped_ambiguous",
                    extra={"uid": carrier.uid, "target": target_uid,
                           "occurrences": len(target_idx)},
                )
            else:
                set_values = {**set_values, **_time_patch(carrier)}

        for i in target_idx:
            merged = {**set_values, **_bump_last_modified(out[i], carrier)}
            out[i] = _patch_event(out[i], merged, delete_keys)
        patched_count += len(target_idx)

    logger.info(
        "applied_overwrites",
        extra={"carriers": len(unique_carriers), "patched": patched_count,
               "orphaned": orphan_count},
    )
    return out


def drop_hidden(events):
    """Drop events whose description YAML sets `hidden: true`.

    Runs after apply_overwrites so a carrier can hide its target
    (`hidden: true`) or un-hide it (`hidden: false` / `overwrite_hidden: true`
    with no value). A non-true `hidden` key is stripped from the event so it
    never appears in any output.
    """
    kept = []
    hidden_count = 0
    for e in events:
        extras = e.model_extra or {}
        if 'hidden' in extras:
            if _as_bool(extras['hidden']):
                hidden_count += 1
                logger.info("event_hidden", extra={"uid": e.uid})
                continue
            data = e.model_dump()
            data.pop('hidden', None)
            e = Event.model_validate(data)
        kept.append(e)
    if hidden_count:
        logger.info("dropped_hidden_events", extra={"count": hidden_count})
    return kept


def _dump(event):
    # The old parser omitted last_modified when missing rather than emitting
    # null. Drop it here to keep the JSON/CSV/ICS/RSS output keys identical.
    d = event.model_dump()
    if d.get('last_modified') is None:
        d.pop('last_modified', None)
    return d


if __name__ == '__main__':
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

    events = apply_overwrites(events, show_orphaned=config.get('show_orphaned_overwrites', False))

    events = drop_hidden(events)

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
