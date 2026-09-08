import re

from .models import Venue


def infer_extra_tags(venue: Venue):
    """Infer useful boolean flags from venue description, name and facilities."""
    text = ' '.join([
        venue.description or '',
        venue.name or '',
        ' '.join(venue.facilities),
    ]).lower()

    venue.additional_info['christmas_party'] = bool(
        re.search(r'christmas (part|din|meal|event)|festive|santa|new year', text))
    venue.additional_info['private_dining'] = bool(
        re.search(r'private (dining|room|party|hire)|function room|banquet|dining room', text))
    venue.additional_info['outdoor_space'] = bool(
        re.search(r'garden|terrace|grounds|marquee|lawn', text))
    venue.additional_info['wedding_licensed'] = bool(
        re.search(r'wedding|civil ceremon|marriag', text))
    venue.additional_info['parking_onsite'] = bool(
        re.search(r'onsite parking|car park|car parking|parking available', text))
    venue.additional_info['accommodation_onsite'] = bool(
        re.search(r'bedroom|guest room|overnight|accommodation|en-suite', text))