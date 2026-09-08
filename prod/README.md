# Kent Venue Scraper

Scrapes event/wedding/party venue listings across 8 Kent towns, collecting name,
location, website, venue type, capacity, parking, catering, accommodation,
facilities, contact details and social media.

## Target locations

Maidstone, Canterbury, Tunbridge Wells, Ashford, Sevenoaks, Tonbridge, Dartford, Folkestone

## Venue types covered

- Wedding Venues (incl. wedding barns, castles)
- Meeting Rooms
- Conference Venues
- Party Venues (incl. marquee venues)
- Training Venues
- Corporate Venues
- Hotels with Event Space
- Restaurants with Private Rooms / Pubs

## Installation

```
pip install -r requirements.txt
```

## Usage

Collect all venues in the 8 target towns (both CSV + JSON):

```
python run_scraper.py
```

Speed up with a smaller delay (be polite to the source site):

```
python run_scraper.py --delay 0.3
```

### Options

| Flag | Description |
|------|-------------|
| `--locations` | Only scrape specific towns, e.g. `--locations maidstone ashford` |
| `--output` | Output filename base (default: `venues`) |
| `--format` | `csv`, `json` or `both` (default: both) |
| `--delay` | Seconds between requests (default: `0.8`) |
| `--no-filter` | Collect all Kent venues, not just the 8 towns |
| `--limit` | Limit pages scraped per venue type (for quick tests) |

### Example

Collect only Maidstone + Canterbury wedding and hotel venues:

```
python run_scraper.py --locations maidstone canterbury --delay 0.4
```

## Web UI

A polished Flask dashboard for browsing, filtering and exporting venues without touching the CLI.

```
pip install -r requirements.txt
python app.py
# open http://127.0.0.1:5000
```

**Features**

- Search across name / postcode / facilities / description
- Toggle 8 towns (Maidstone, Canterbury, Tunbridge Wells, Ashford, Sevenoaks, Tonbridge, Dartford, Folkestone) + 9 venue types
- Grid (cards) ↔ Table view, sort by name/location/capacity, 24/48/96 per page
- Live stats per town/type for current filter
- Venue detail modal with capacity, parking, catering, accommodation, contact, facilities, maps link
- Export filtered view to CSV / JSON (same data as scraper)
- **Scrape panel**: pick towns, set delay + max pages/type, run scraper in background with live log (uses same `VenueScraper` + `detect_town` logic)
- API: `GET /api/venues?search=&locations=&types=&page=&per_page=&sort=` , `GET /api/stats`, `POST /api/scrape`, `GET /api/scrape/status`, `GET /api/export/csv|json`

Files: `app.py` + `templates/index.html` + `static/style.css` + `static/app.js`

## Output

Results are saved to:

- `output/venues.json` - full JSON export
- `output/venues.csv` - spreadsheet-friendly CSV

Each venue row includes: name, location, venue type, website, capacity, parking,
catering, accommodation, facilities, contact name/email/phone, Facebook/Instagram/
Twitter/LinkedIn, description, address, postcode, source URL, detected town,
christmas_party / private_dining / wedding_licensed flags.

## How it works

- Data source: `venues4hire.org` (29,000+ UK venue listings, filtered to Kent county)
- Searches 11 venue-type categories in Kent, paginates all results
- Fetches each venue detail page and parses structured fields
- Dedupes by name + postcode
- Detects town from postcode prefix / address text (e.g. `TN24` -> Ashford)
- Infers extra tags (Christmas party suitability, private dining, wedding licences)
  from description text

Note: count for the 8 towns is limited to venues whose listing explicitly
references those towns - nearby villages in the same district are not counted.