# mucnoise event repository

Create a website showcasing events, inspired by [nyc-noise.com](https://www.nyc-noise.com), based on a shared calendar (e.g. Google, Proton). It can be deployed on GitHub Pages (see [this site.yml](/../github-pages/.github/workflows/site.yml) for an example using GitHub Actions) for an example that deploys [mucnoise.com](https://mucnoise.com).

Note: This has been tested with Proton calendars only and is not guaranteed to work with other providers.

## Basic usage

### Installation

1. Clone this repository: `git clone git@github.com:ghxm/mucnoise.git`

2. Install dependencies: `pip install -r requirements.txt`

3. Create a new calendar in your calendar provider (e.g. Google, Proton)
4. Get the calendar's public/shared URL

### Configuration

The site can be configured using environment variables (to allow for easy deployment using GitHub Pages). The following variables are available:

```
CAL_URI - The URI of the calendar to use
CAL_EMAIL - The email address of the calendar to use for invites
TIMEZONE - The timezone to use for the calendar
SITE_TITLE - The title of the site
SITE_URL - The URL of the site
SITE_DESCRIPTION - The description of the site
SITE_OWNER_EMAIL - The email address of the site owner
ALLOW_UNACCEPTED - Whether to allow unaccepted events to be shown
ALWAYS_ALLOW_SENDERS - A comma-separated list of email addresses whose events are always shown (accepted or not) in json style (e.g. ["test@test.com"])
RECURRING_EVENTS_DAYS - The number of days to show recurring events for
```


You can also prefix the variables with to avoid conflicts with other variables (make sure to set the prefix either in `utils.get_config` directly or whenever retreiving the prefix in `parse_cal.py` and `make_site.py`).


### Deployment

1. Run `python parse_cal.py` to parse the calendar and create a JSON/ICAL/CSV/RSS files containing the events
2. Run `python make_site.py` to create the site
3. Copy the site folder to your webserver or use GitHub Pages to deploy it


## Events

### Event properties

Properties for events can be set in YAML format using the event description in the calendar. Currently, only the url property is supported. In the future this may be extended to allow for more properties (categories, ticket price, accessibility).

Example:

```
url: https://example.com
```

In addition to the properties, the event can contain a normal description to be shown under the event title in the table view.

Note: If your event description contains texts similar to YAML syntax, make sure to wrap the properties in `---` to avoid parsing errors.

Example:

```
---
url: https://example.com
---
This is a description.
```

### Event invites

The is configured to allow invites to be sent to the event owner. The owner's email address is configured using the `CAL_EMAIL` environment variable. The `ALLOW_UNACCEPTED` environment variable can be used to allow unaccepted events to be shown on the site. If not set, only accepted events will be shown. Additionally, a list of email addresses can be configured using the `ALWAYS_ALLOW_SENDERS` environment variable. Events from these senders will always be shown, regardless of whether they have been accepted or not.


## Venues

The site can display a list of venues. Venues can be added by creating YAML files in the `data/venues` folder. The file name is used as the id of the venue. Currently, only, the following fields are supported:

```
name: The name of the venue
address: The address of the venue
address_url: The URL of the venue's address
url: The URL of the venue
```

Note: Files starting with an underscore (`_`) are ignored.

Examples can be found in [the `venues` folder of the `github-pages` deployment branch](../github-pages/data/venues).



## News

Similar to the venues, you can also display a list of small news articles / announcements. Examples can also be found in the [`github-pages` deployment branch](../github-pages/data/news).
