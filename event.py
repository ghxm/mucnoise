"""Event model and ICS-component constructor.

Introduced for the parser refactor. Not yet wired into parse_cal.py.
"""
from __future__ import annotations

import logging
import re
from datetime import date as DateType, datetime, timedelta
from typing import Optional, Union

import icalendar
import yaml as yaml_lib
from pydantic import BaseModel, ConfigDict, field_serializer

import utils

logger = logging.getLogger(__name__)


class Event(BaseModel):
    model_config = ConfigDict(extra='allow', arbitrary_types_allowed=True)

    uid: str
    created: Optional[Union[datetime, DateType]] = None
    last_modified: Optional[Union[datetime, DateType]] = None
    cancelled: bool = False
    all_day: bool
    recurring: bool = False
    multi_day: bool = False
    start: Union[datetime, DateType]
    end: Union[datetime, DateType]
    duration_seconds: float
    url: Optional[str] = None
    location: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    year: Optional[str] = None
    date: Optional[str] = None
    kw: Optional[str] = None
    kw_year: Optional[str] = None
    weekday_start: Optional[str] = None
    weekday_end: Optional[str] = None

    # Pydantic's default JSON encoder normalizes +00:00 to 'Z'. Python 3.10's
    # datetime.fromisoformat (used by make_site.py) rejects 'Z'. Force stdlib
    # isoformat() to preserve the +00:00 form the old serializer emitted.
    @field_serializer('created', 'last_modified', 'start', 'end', when_used='json')
    def _serialize_dt(self, v):
        if v is None:
            return None
        return v.isoformat()

    @classmethod
    def from_ical_component(
        cls,
        component,
        *,
        owner_email: Optional[str] = None,
        allow_unaccepted: bool = False,
        always_allow_senders: Optional[list] = None,
    ) -> Optional["Event"]:
        if component.name != 'VEVENT':
            return None

        always_allow_senders = always_allow_senders or []

        uid = _extract_uid(component)
        if uid is None:
            logger.warning("skip", extra={"uid": None, "reason": "no_uid"})
            return None

        if _is_exdate_excluded(component):
            return None

        partstat = _owner_partstat(component, owner_email)
        if partstat == 'DECLINED':
            return None

        if not _passes_filter(component, partstat, allow_unaccepted, always_allow_senders, uid):
            return None

        try:
            start = component.get('DTSTART').dt
            end = component.get('DTEND').dt
        except Exception:
            logger.warning("skip", extra={"uid": uid, "reason": "missing_dtstart_or_dtend"})
            return None

        all_day = not isinstance(start, datetime)
        recurring = component.get('RRULE') is not None
        if all_day:
            multi_day = start != end
        else:
            multi_day = start.date() != end.date()
        cancelled = component.get('STATUS') == 'CANCELLED'

        data: dict = {
            'uid': uid,
            'cancelled': cancelled,
            'all_day': all_day,
            'recurring': recurring,
            'multi_day': multi_day,
            'start': start,
            'end': end,
            'duration_seconds': (end - start).total_seconds(),
            'url': component.get('URL'),
            'location': _normalize_location(component.get('LOCATION')),
            'title': component.get('SUMMARY'),
            'description': component.get('DESCRIPTION'),
        }

        created = _extract_created(component)
        if created is not None:
            data['created'] = created
        last_modified = _extract_last_modified(component)
        if last_modified is not None:
            data['last_modified'] = last_modified

        yaml_extras, cleaned_description = _parse_description(data['description'], partstat, uid)
        data['description'] = cleaned_description
        data.update(yaml_extras)

        data.update(_derive_date_fields(start, end, all_day))

        return cls.model_validate(data)


def _extract_uid(component) -> Optional[str]:
    uid = component.get('UID')
    if uid is None:
        return None
    return re.sub(r'@.*', '', str(uid))


def _is_exdate_excluded(component) -> bool:
    if 'EXDATE' not in component.keys():
        return False
    try:
        ex = component['EXDATE']
        if isinstance(ex, icalendar.prop.vDDDLists):
            exdates = [d.dt for d in ex.dts]
        elif isinstance(ex, list):
            exdates = [d.dts[0].dt for d in ex]
        else:
            return False
        return component['DTSTART'].dt in exdates
    except Exception:
        return False


def _extract_attendee_email(a) -> Optional[str]:
    try:
        if isinstance(a, icalendar.prop.vCalAddress):
            params = a.params
            if 'MAILTO' in params:
                return params.get('MAILTO')
            if 'EMAIL' in params:
                return params.get('EMAIL')
            if 'CN' in params:
                return params.get('CN')
            s = str(a)
            return s.split(':', 1)[1] if ':' in s else s
        s = str(a)
        if s.lower().startswith('mailto:'):
            return s.split(':', 1)[1]
        return s
    except Exception:
        return None


def _owner_partstat(component, owner_email: Optional[str]) -> Optional[str]:
    if owner_email is None:
        return None
    owner_re = re.compile(r'(mailto:)?' + str(owner_email), flags=re.IGNORECASE)
    attendees = component.get('attendee')
    if attendees is None:
        return None
    try:
        if isinstance(attendees, list):
            for a in attendees:
                email = _extract_attendee_email(a)
                if email and owner_re.search(email):
                    return a.params.get('PARTSTAT')
            return None
        email = _extract_attendee_email(attendees) or str(attendees)
        if owner_re.search(email):
            return attendees.params.get('PARTSTAT')
        return None
    except Exception:
        return None


def _passes_filter(component, partstat, allow_unaccepted, always_allow_senders, uid) -> bool:
    sender = component.get('ORGANIZER')
    attendee = component.get('ATTENDEE')
    candidates = [sender] if sender is not None else []
    if attendee is not None and isinstance(attendee, list) and len(attendee) > 0:
        candidates.append(attendee[0])
    candidates = [c for c in set(candidates) if c is not None]

    if not candidates:
        return True

    addresses = [str(c).split(':', 1)[1] for c in candidates if ':' in str(c)]
    if any(a in always_allow_senders for a in addresses):
        return True
    if allow_unaccepted:
        return True
    if partstat is None:
        logger.warning("skip", extra={"uid": uid, "reason": "no_partstat"})
        return False
    return partstat == 'ACCEPTED'


def _normalize_location(location):
    if location is None:
        return None
    s = str(location)
    if '\n' in s:
        return s.split('\n')[0]
    if ',' in s:
        return s.split(',')[0]
    return s


def _extract_created(component):
    try:
        v = component.get('CREATED')
        if v is not None:
            return v.dt
    except Exception:
        pass
    try:
        v = component.get('DTSTAMP')
        if v is not None:
            return v.dt
    except Exception:
        pass
    return None


def _extract_last_modified(component):
    try:
        v = component.get('LAST-MODIFIED')
        if v is not None:
            return v.dt
    except Exception:
        pass
    return None


def _parse_description(description, partstat, uid):
    if description is None:
        return {}, None
    try:
        cleaned = utils.clean_description(str(description))
        yaml_desc, body = utils.split_yaml_text(cleaned)
        extras: dict = {}
        if yaml_desc:
            for d in yaml_lib.safe_load_all(yaml_desc):
                if isinstance(d, dict):
                    extras.update(d)
        if body:
            body = body.strip()
        if not body:
            return extras, None
        if partstat in ('TENTATIVE', 'NEEDS-ACTION'):
            body = utils.clean_description(body)
        body = re.sub(r'^\s*(<.{0,1}br>[\s]*)+', '', body)
        body = re.sub(r'<p>', '', body)
        body = re.sub(r'</p>', '<br>', body)
        return extras, body
    except Exception as e:
        logger.warning("description_parse_failed", extra={"uid": uid, "error": str(e)})
        return {}, None


def _derive_date_fields(start, end, all_day) -> dict:
    fields: dict = {}
    try:
        fields['year'] = utils.get_year(start)
    except Exception:
        fields['year'] = None
    try:
        fields['date'] = utils.ymd_string(start)
    except Exception:
        fields['date'] = None
    try:
        fields['kw'] = utils.get_weeknum(start)
    except Exception:
        fields['kw'] = None
    try:
        fields['kw_year'] = utils.get_weeknum_year(start)
    except Exception:
        fields['kw_year'] = None
    try:
        fields['weekday_start'] = utils.get_weekday(start)
    except Exception:
        fields['weekday_start'] = None
    try:
        if all_day:
            fields['weekday_end'] = utils.get_weekday(end - timedelta(days=1))
        else:
            fields['weekday_end'] = utils.get_weekday(end)
    except Exception:
        fields['weekday_end'] = None
    return fields
