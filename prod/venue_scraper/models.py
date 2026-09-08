from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional
from datetime import datetime


class VenueType(Enum):
    WEDDING = "Wedding Venue"
    MEETING_ROOM = "Meeting Room"
    CONFERENCE = "Conference Venue"
    PARTY = "Party Venue"
    CHRISTMAS_PARTY = "Christmas Party Venue"
    TRAINING = "Training Venue"
    CORPORATE = "Corporate Venue"
    HOTEL_EVENT_SPACE = "Hotel with Event Space"
    RESTAURANT_PRIVATE = "Restaurant with Private Room"


@dataclass
class SocialMedia:
    facebook: Optional[str] = None
    instagram: Optional[str] = None
    twitter: Optional[str] = None
    linkedin: Optional[str] = None
    tiktok: Optional[str] = None


@dataclass
class Venue:
    name: str
    location: str
    venue_type: VenueType
    website: Optional[str] = None
    capacity: Optional[str] = None
    parking: Optional[str] = None
    catering: Optional[str] = None
    accommodation: Optional[str] = None
    facilities: List[str] = field(default_factory=list)
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    social_media: SocialMedia = field(default_factory=SocialMedia)
    description: Optional[str] = None
    address: Optional[str] = None
    postcode: Optional[str] = None
    source: Optional[str] = None
    scraped_date: str = field(default_factory=lambda: datetime.now().isoformat())
    additional_info: dict = field(default_factory=dict)

    def _no_blank(self, value, no_label: str) -> str:
        return (value or '').strip() or no_label

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'location': self.location,
            'venue_type': self.venue_type.value,
            'website': self.website,
            'capacity': self.capacity,
            'parking': self._no_blank(self.parking, 'No parking'),
            'catering': self._no_blank(self.catering, 'No on-site catering'),
            'accommodation': self._no_blank(self.accommodation, 'No on-site accommodation'),
            'facilities': ', '.join(self.facilities) if self.facilities else '',
            'contact_name': self.contact_name,
            'contact_email': self.contact_email,
            'contact_phone': self.contact_phone,
            'facebook': self.social_media.facebook,
            'instagram': self.social_media.instagram,
            'twitter': self.social_media.twitter,
            'linkedin': self.social_media.linkedin,
            'tiktok': self.social_media.tiktok,
            'description': self.description,
            'address': self.address,
            'postcode': self.postcode,
            'source': self.source,
            'scraped_date': self.scraped_date,
            **self.additional_info
        }
