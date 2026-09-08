import re
from typing import List, Optional

from .models import Venue

# Target towns (slug form)
LOCATIONS = [
    'maidstone',
    'canterbury',
    'tunbridge-wells',
    'ashford',
    'sevenoaks',
    'tonbridge',
    'dartford',
    'folkestone',
]

# Postcode prefix -> town mapping for the target Kent towns
POSTCODE_TOWN_MAP = {
    # Maidstone
    ('ME', '1'): 'maidstone', ('ME', '2'): 'maidstone', ('ME', '3'): 'maidstone',
    ('ME', '4'): 'maidstone', ('ME', '5'): 'maidstone', ('ME', '14'): 'maidstone',
    ('ME', '15'): 'maidstone', ('ME', '16'): 'maidstone', ('ME', '17'): 'maidstone',
    ('ME', '18'): 'maidstone', ('ME', '19'): 'maidstone', ('ME', '20'): 'maidstone',
    # Canterbury
    ('CT', '1'): 'canterbury', ('CT', '2'): 'canterbury', ('CT', '3'): 'canterbury',
    ('CT', '4'): 'canterbury', ('CT', '5'): 'canterbury', ('CT', '6'): 'canterbury',
    ('CT', '7'): 'canterbury',
    # Folkestone (incl. Hythe/Dymchurch nearby on CT21-22? those are CT* - offset nearby, keep folkestone for CT18-20 only)
    ('CT', '18'): 'folkestone', ('CT', '19'): 'folkestone', ('CT', '20'): 'folkestone',
    # Tunbridge Wells
    ('TN', '1'): 'tunbridge-wells', ('TN', '2'): 'tunbridge-wells', ('TN', '3'): 'tunbridge-wells',
    ('TN', '4'): 'tunbridge-wells',
    # Ashford
    ('TN', '23'): 'ashford', ('TN', '24'): 'ashford', ('TN', '25'): 'ashford',
    ('TN', '26'): 'ashford', ('TN', '27'): 'ashford', ('TN', '28'): 'ashford',
    ('TN', '29'): 'ashford', ('TN', '30'): 'ashford',
    # Sevenoaks
    ('TN', '13'): 'sevenoaks', ('TN', '14'): 'sevenoaks', ('TN', '15'): 'sevenoaks',
    # Tonbridge
    ('TN', '8'): 'tonbridge', ('TN', '9'): 'tonbridge', ('TN', '10'): 'tonbridge',
    ('TN', '11'): 'tonbridge', ('TN', '12'): 'tonbridge',
    # Dartford
    ('DA', '1'): 'dartford', ('DA', '2'): 'dartford', ('DA', '3'): 'dartford',
    ('DA', '4'): 'dartford', ('DA', '5'): 'dartford', ('DA', '9'): 'dartford',
}

TOWN_ALIASES = {
    'maidstone': ['maidstone', 'teston', 'barming', 'larkfield', 'aylesford', 'colin dickens'],
    'canterbury': ['canterbury', 'bridge', 'harbledown', 'wincheap', 'sturry'],
    'tunbridge-wells': ['tunbridge wells', 'tunbridge-wells', 'royal tunbridge wells', 'speldhurst', 'pembury', 'langton', 'crowborough'],
    'ashford': ['ashford', 'willesborough', 'kingsnorth', 'kennington', 'singleton', 'beaver'],
    'sevenoaks': ['sevenoaks', 'otford', 'kemsing', 'seal', 'westeham', 'hever', 'edenbridge'],
    'tonbridge': ['tonbridge', 'hadlow', 'hildenborough'],
    'dartford': ['dartford', 'wilmington', 'swanley', 'hextable'],
    'folkestone': ['folkestone', 'cheriton', 'sandgate', 'hythe', 'saltwood', 'shorncliffe'],
}


def normalize(s: Optional[str]) -> str:
    return re.sub(r'[^a-z]+', '', (s or '').lower())


def postcode_prefix(postcode: Optional[str]):
    m = re.match(r'\s*([A-Z]{1,2})(\d{1,2})', (postcode or '').strip().upper())
    if m:
        return m.group(1), m.group(2)
    return None, None


def detect_town(venue: Venue) -> Optional[str]:
    """Detect the target town for a venue from postcode prefix or text aliases."""
    area, dist = postcode_prefix(venue.postcode)
    if area and dist:
        town = POSTCODE_TOWN_MAP.get((area, dist))
        if town:
            return town
        # has a valid UK postcode but not in any of our 8 Kent towns
        return None

    # No valid postcode → use text aliases as fallback
    combined = ' '.join([venue.name or '', venue.address or '', venue.location or ''])
    norm = normalize(combined)
    for town_slug, aliases in TOWN_ALIASES.items():
        for alias in aliases:
            if normalize(alias) in norm:
                return town_slug
    return None


def matches_any(venue: Venue, locations: List[str]) -> bool:
    """True if venue belongs to any of the given town slugs."""
    if not locations:
        return True
    town = detect_town(venue)
    if town and town in locations:
        return True
    # for venues with a valid UK postcode but no match → reject immediately
    if venue.postcode and re.match(r'^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$',
                                   venue.postcode.strip().upper()):
        return False
    # text substring fallback only for venues with no valid postcode
    combined = normalize(' '.join([venue.name or '', venue.address or '', venue.location or '']))
    slugs = [s.replace('-', ' ') for s in locations]
    return any(normalize(s) in combined for s in slugs)