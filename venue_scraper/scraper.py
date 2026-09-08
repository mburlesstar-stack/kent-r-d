import requests
from bs4 import BeautifulSoup
import time
import re
from typing import List, Optional, Tuple
from urllib.parse import urljoin, parse_qsl
from fake_useragent import UserAgent
from tenacity import retry, stop_after_attempt, wait_exponential

from .models import Venue, VenueType, SocialMedia
from .geo import matches_any


class VenueScraper:
    """Scraper for Kent venue data from venues4hire.org and other UK directories."""

    BASE_URL = 'https://venues4hire.org'

    # Venue type ID to our VenueType mapping
    # Values: (venues4hire_type_id, our_venue_type)
    TYPE_MAPPING = {
        1: VenueType.PARTY,                 # Community Hall
        2: VenueType.PARTY,                 # Village Hall
        3: VenueType.PARTY,                 # Membership Club
        4: VenueType.CONFERENCE,            # Local Authority (Town Hall etc)
        5: VenueType.TRAINING,              # School / College / Library
        7: VenueType.HOTEL_EVENT_SPACE,     # Hotel / Conference Centre
        8: VenueType.MEETING_ROOM,          # Business Meeting Rooms
        10: VenueType.PARTY,                # Sports Club - Cricket
        11: VenueType.PARTY,                # Sports Club - Golf
        12: VenueType.PARTY,                # Sports Club - Rugby
        13: VenueType.PARTY,                # Sports Club - Other
        14: VenueType.RESTAURANT_PRIVATE,   # Pub / Restaurant
        15: VenueType.WEDDING,              # Castle
        16: VenueType.CONFERENCE,           # Museum
        17: VenueType.PARTY,                # Marquee Venue
        18: VenueType.WEDDING,              # Wedding Barn
        19: VenueType.WEDDING,              # Wedding Venue
        20: VenueType.CONFERENCE,           # Historic Venue
        21: VenueType.PARTY,                # Cinema
        25: VenueType.CORPORATE,            # Team Building Venue
        26: VenueType.PARTY,                # Fitness and Dance Centre
        27: VenueType.CORPORATE,            # Exhibition Space
        29: VenueType.TRAINING,             # Training Rooms
        30: VenueType.CONFERENCE,           # Theatre
        33: VenueType.PARTY,                # Showgrounds
    }

    def __init__(self, delay: float = 1.0):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-GB,en-US;q=0.7,en;q=0.3',
        })
        self.delay = delay

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=3, max=15))
    def _fetch(self, url: str) -> Optional[BeautifulSoup]:
        try:
            time.sleep(self.delay)
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return BeautifulSoup(response.text, 'lxml')
        except Exception as e:
            print(f"  [warn] Error fetching {url}: {e}")
            raise

    def _get_venue_links(self, soup: BeautifulSoup) -> List[str]:
        links = []
        seen = set()
        for link in soup.find_all('a', href=True):
            href = link['href']
            if '/venue/details/' in href and href not in seen:
                seen.add(href)
                links.append(href)
        return links

    def scrape_kent_venues(self, location_filter: Optional[List[str]] = None,
                           type_ids: Optional[List[int]] = None,
                           max_pages: int = None, max_vp_type: int = None) -> List[Venue]:
        """Scrape relevant venue types from Kent county, filtered by location.

        Args:
            location_filter: List of town names to keep venues from (or None for all).
            type_ids: Specific venues4hire type IDs to scrape (or None for all).
            max_pages: Limit number of pages scraped per type (None = all).
            max_vp_type: Limit number of venue detail pages fetched per type (None = all).
        """
        venues = []
        type_ids = type_ids or list(self.TYPE_MAPPING.keys())
        for type_id in type_ids:
            venue_type = self.TYPE_MAPPING.get(type_id)
            if venue_type is None:
                continue
            print(f"  [{venue_type.value}] scraping type {type_id}...", flush=True)
            page = 1
            page_count = 0
            while True:
                url = (f"{self.BASE_URL}/search/county-results?county=Kent&resultsView=list"
                       f"&VenueTypeId={type_id}&VenueSizeId=0&page={page}&pageSize=20#results")
                soup = self._fetch(url)
                if soup is None:
                    break

                links = self._get_venue_links(soup)
                if not links:
                    break

                if max_vp_type and page_count + len(links) > max_vp_type:
                    links = links[:max_vp_type - page_count]

                for link in links:
                    detail_soup = self._fetch(self.BASE_URL + link)
                    if detail_soup is None:
                        continue
                    venue = self._parse_venue_detail(detail_soup, venue_type, self.BASE_URL + link)
                    if venue:
                        if location_filter and not matches_any(venue, location_filter):
                            continue
                        venues.append(venue)
                    page_count += 1

                if max_pages and page >= max_pages:
                    break

                # Check if there is a next page
                page_nums = soup.find_all('a', href=lambda h: h and f'page={page + 1}' in h and 'pageSize' in h)
                if not page_nums:
                    break
                page += 1
                if max_vp_type and page_count >= max_vp_type:
                    break

        return venues

    def _matches_location(self, venue: Venue, locations: List[str]) -> bool:
        return matches_any(venue, locations)

    def _parse_venue_detail(self, soup: BeautifulSoup, venue_type: VenueType, source_url: str) -> Optional[Venue]:
        try:
            # Title format: "Name, Town, County - description... - Venues4Hire.org"
            title = soup.title.text if soup.title else ''

            # Venue name - h1 is generic "Details of over 29,000...", actual name is in h2
            name = None
            for h2 in soup.find_all('h2'):
                txt = h2.get_text(strip=True)
                # Skip GDPR / generic headers, take first venue-like h2
                if txt and 'GDPR' not in txt and len(txt) > 3:
                    # Strip suffixes like " - CanterburyVerified venue" / "Verified venue"
                    txt = re.sub(r'\s*Verified venue\s*$', '', txt)
                    txt = re.sub(r'\s*-\s*[A-Za-z ]*Verified.*$', '', txt)
                    txt = txt.strip(' -')
                    # Also strip trailing " - Location" that duplicates the title location
                    # e.g. "Marleybrook House - Canterbury" -> "Marleybrook House"
                    txt = re.sub(r'\s+-\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s*$', '', txt).strip()
                    name = txt
                    break
            if not name:
                h1 = soup.find('h1')
                if h1:
                    name = h1.get_text(strip=True)
            if not name or 'Details of over' in name:
                # fallback: parse from title "Name, Town, County -"
                if title:
                    name = title.split(',')[0].strip()
                    name = re.sub(r'\s*-\s*Venues4Hire.*$', '', name).strip()

            if not name:
                return None

            main = soup.find('div', class_='col-md-9') or soup
            text = main.get_text('\n', strip=True)
            lines = [l.strip() for l in text.split('\n') if l.strip()]

            # Extract location from title (second comma element)
            location = venue_type.value
            title_parts = [p.strip() for p in title.split('-')[0].split(',')]
            if len(title_parts) >= 2:
                location = title_parts[1]
            elif 'Kent' in title:
                location = 'Kent'

            # Extract address
            address = None
            postcode = None
            pc_match = re.search(r'\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b', text)
            if pc_match:
                postcode = pc_match.group(0)

            # Find address near the "Address" label
            addr_idx = None
            for i, line in enumerate(lines):
                if line.lower() == 'address':
                    addr_idx = i
                    break
            if addr_idx is not None:
                addr_parts = lines[addr_idx + 1:addr_idx + 6]
                addr_parts = [p for p in addr_parts if p and
                              not p.lower().startswith(('phone', 'contact', 'email', 'website', 'facebook', 'overview', 'facilities', 'rooms'))]
                address = ', '.join(addr_parts)
                if postcode and postcode not in address:
                    address = f"{address}, {postcode}"

            # Extract contact info (also check soup for mailto / social links)
            phone, contact_name, email = self._extract_contact(lines)
            # supplement email from mailto hrefs
            if not email:
                for a in soup.find_all('a', href=True):
                    if 'mailto:' in a['href']:
                        m = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', a['href'])
                        if m:
                            email = m.group(0)
                            break
            website, social = self._extract_website_and_social(lines)
            # supplement website/social from anchor hrefs
            for a in soup.find_all('a', href=True):
                href = a['href']
                if not website and href.startswith('http') and 'venues4hire' not in href and 'facebook' not in href and 'instagram' not in href:
                    # heuristic: first external http link after Website label is the venue site
                    if len(href) < 120 and '.' in href:
                        website = href
                if 'facebook.com' in href and not social.facebook:
                    if 'venues4hire' in href:
                        continue
                    social.facebook = href
                if 'instagram.com' in href and not social.instagram:
                    social.instagram = href
                if ('twitter.com' in href or 'x.com/' in href) and not social.twitter:
                    social.twitter = href
                if 'linkedin.com' in href and not social.linkedin:
                    social.linkedin = href

            # Extract capacity (venue size line)
            capacity = self._extract_capacity(lines)

            # Extract facilities
            facilities = self._extract_facilities(lines)

            # Extract accommodation
            accommodation = self._extract_accommodation(text, facilities)

            # Extract catering
            catering = self._extract_catering(text, facilities)

            # Extract description
            description = self._extract_description(lines)

            # Parking
            parking = self._extract_parking(text)

            venue = Venue(
                name=name,
                location=location,
                venue_type=venue_type,
                website=website,
                capacity=capacity,
                parking=parking,
                catering=catering,
                accommodation=accommodation,
                facilities=facilities,
                contact_name=contact_name,
                contact_email=email,
                contact_phone=phone,
                social_media=social,
                description=description,
                address=address,
                postcode=postcode,
                source='venues4hire.org',
                additional_info={'source_url': source_url}
            )
            return venue
        except Exception as e:
            print(f"  [warn] Error parsing venue detail: {e}")
            return None

    def _extract_contact(self, lines: List[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        phone = None
        contact_name = None
        email = None

        phone_idx = None
        for i, line in enumerate(lines):
            if line.lower() == 'phone':
                phone_idx = i
                break
        if phone_idx is not None and phone_idx + 1 < len(lines):
            phone = lines[phone_idx + 1]

        contact_idx = None
        for i, line in enumerate(lines):
            if line.lower().startswith('contact'):
                contact_idx = i
                break
        if contact_idx is not None and contact_idx + 1 < len(lines):
            contact_name = lines[contact_idx + 1].replace('Booking Administrator -', '').strip()

        # Email from mailto links
        email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '\n'.join(lines))
        if email_match:
            email = email_match.group(0)

        return phone, contact_name, email

    def _extract_website_and_social(self, lines: List[str]) -> Tuple[Optional[str], SocialMedia]:
        website = None
        social = SocialMedia()

        web_idx = None
        for i, line in enumerate(lines):
            if line.lower().startswith('website'):
                web_idx = i
                break
        if web_idx is not None and web_idx + 1 < len(lines):
            candidate = lines[web_idx + 1]
            if candidate.startswith(('http', 'www.')) and 'venues4hire' not in candidate:
                website = candidate

        for line in lines:
            low = line.lower()
            if 'facebook.com' in low and not social.facebook:
                if 'venues4hire' in low or 'venuefinder' in low or 'directory' in low:
                    continue
                social.facebook = line.strip()
            elif 'instagram.com' in low and not social.instagram:
                social.instagram = line.strip()
            elif ('twitter.com' in low or 'x.com/' in low) and not social.twitter:
                social.twitter = line.strip()
            elif 'linkedin.com' in low and not social.linkedin:
                social.linkedin = line.strip()

        return website, social

    def _extract_capacity(self, lines: List[str]) -> Optional[str]:
        size_idx = None
        for i, line in enumerate(lines):
            if line.lower().startswith('venue size'):
                size_idx = i
                break
        if size_idx is not None:
            # Value may be on same line or next line
            val = lines[size_idx].replace('Venue size', '').strip()
            next_val = lines[size_idx + 1].strip() if size_idx + 1 < len(lines) else ''
            if not val and next_val:
                val = next_val
            elif next_val and next_val != val and len(next_val) < 40 and '(' in next_val:
                # Only append if different (avoids duplication bug)
                val = (val + ' ' + next_val).strip() if val else next_val
            return val if val else None

        # Fallback: look for capacity patterns
        for line in lines:
            m = re.search(r'(?:capacity|seats?|up to)\s*:?\s*(\d[\d,]*\s*(?:-\s*\d+)?)', line, re.I)
            if m:
                return line
        return None

    def _extract_parking(self, text: str) -> Optional[str]:
        parking_idx = text.lower().find('onsite parking')
        if parking_idx >= 0:
            snippet = text[parking_idx:parking_idx + 100]
            return snippet.split('\n')[0].strip()
        return None

    @staticmethod
    def _sentence_containing(text: str, keywords: tuple, max_len: int = 260) -> Optional[str]:
        low = text.lower()
        for kw in keywords:
            idx = low.find(kw)
            if idx < 0:
                continue
            # expand to sentence boundaries
            start = text.rfind('.', 0, idx)
            start = text.rfind('\n', 0, idx + 1)
            for sep in ('\n', '. '):
                cand = text.rfind(sep, 0, idx)
                if cand > start:
                    start = cand
            end = text.find('\n', idx)
            d = text.find('. ', idx)
            end = d if 0 < d < end or end < 0 else end
            if end < 0 or end - idx > 120:
                end = idx + 120
            snippet = text[start + 1:end].strip()
            if len(snippet) > max_len:
                snippet = snippet[:max_len].rsplit(' ', 1)[0] + '…'
            return snippet or None
        return None

    def _extract_catering(self, text: str, facilities: List[str]) -> Optional[str]:
        # 1) Facility rows are authoritative (e.g. "Kitchen: Yes - Full")
        for f_item in facilities:
            low = f_item.lower()
            if low.startswith('kitchen') or 'catering' in low:
                return f_item[:200]
        # 2) Description sentence mentioning real catering
        for kw in ('event catering', 'catering facilities', 'self-catering', 'caterers',
                   'catering available', 'full catering', 'in-house catering',
                   'outside caterers are', 'cater for'):
            snippet = self._sentence_containing(text, (kw,))
            if snippet:
                return snippet
        return None

    def _extract_accommodation(self, text: str, facilities: List[str]) -> Optional[str]:
        # 1) Facility rows are authoritative
        for f_item in facilities:
            low = f_item.lower()
            if (low.startswith('overnight accommodation') or low.startswith('accommodation')
                    or low.startswith('bedroom') or low.startswith('guest room')
                    or low.startswith('rooms are available') or 'onsite accommodation' in low
                    or 'on-site accommodation' in low):
                return f_item[:200]
        # 2) Counts in the description ("38 bedrooms")
        for pat in (r'\b(\d{1,3})\s*(?:en[- ]?suite\s*)?(?:bedrooms?|guest rooms?)\b',
                    r'\b(?:offer|has|have)\s+(\d{1,3})\s*(?:en[- ]?suite\s*)?rooms?\b'):
            m = re.search(pat, text, re.I)
            if m:
                return f"{m.group(1)} bedrooms"
        # 3) Description sentence with a legitimate accommodation noun (not "accommodate")
        for kw in ('overnight accommodation', 'guest rooms', 'bed & breakfast',
                   'on-site accommodation', 'onsite accommodation', 'en suite bedrooms',
                   'en-suite bedrooms'):
            snippet = self._sentence_containing(text, (kw,))
            if snippet:
                return snippet
        return None

    # Facility rows whose value isn't always Yes/No/count
    _FACILITY_VALUE_EXPECTED = {
        'onsite parking', 'nearby parking', 'on-street parking', 'parking', 'disabled access',
        'disabled toilets', 'kitchen', 'tables', 'chairs', 'seating', 'bar', 'overnight accommodation',
        'accommodation', 'bedrooms', 'guest rooms', 'guest rooms available', 'wheelchair access',
        'hearing loop', 'induction loop', 'wifi', 'wi-fi', 'staging', 'projector', 'projector screen',
        'pa system', 'dance floor', 'stage', 'sound system', 'lighting', 'licenses held', 'licence',
        'license', 'licensing', 'catering', 'food', 'cloakroom', 'baby changing', 'toilets',
        'garden', 'marquee', 'function room', 'venue capacity', 'dining capacity',
    }

    def _extract_facilities(self, lines: List[str]) -> List[str]:
        facilities = []
        # Find Venue facilities section
        fac_start = None
        for i, line in enumerate(lines):
            if line.lower() == 'venue facilities':
                fac_start = i
                break
        if fac_start is not None:
            # Facilities are in pairs: name, value (e.g. "Onsite parking" / "34 spaces")
            i = fac_start + 1
            while i < len(lines):
                low = lines[i].lower()
                if low in ('other venue facilities', 'rooms', 'overview', 'venue map', 'report a problem', 'the', 'please ensure all fields are completed'):
                    # Check if it's transition to "Other venue facilities" - continue, else break
                    if low == 'other venue facilities':
                        i += 1
                        continue
                    break
                if low.startswith('explore the rooms') or low in ('description', 'capacity'):
                    break
                # Skip long sentences and form fields
                if len(lines[i]) > 60 or lines[i].lower() in ('yes', 'no'):
                    i += 1
                    continue
                # This is likely a facility name; check next line for value
                name = lines[i]
                value = lines[i+1] if i+1 < len(lines) else ''
                # Skip placeholder dashes (e.g. "--") used instead of real values
                if not name or re.fullmatch(r'[-–—_/\\]+', name):
                    i += 1
                    continue
                # Skip if name is actually a value or header
                if name.lower().startswith('we don') or 'adopt' in name.lower():
                    break
                if (value.strip() in ('--', '-', '–', '—', '_', '?', 'n/a', 'na', 'unknown', 'none') or
                        re.fullmatch(r'[-–—_/\\]+', value.strip())):
                    if len(name) < 40 and name.count(' ') <= 5 and name not in facilities:
                        facilities.append(name)
                    i += 1
                    continue
                # Known facility rows with free-form values (e.g. "Nearby parking / Within 40 metres")
                name_low = name.lower().strip().rstrip(':')
                if name_low in self._FACILITY_VALUE_EXPECTED and len(value) < 40 and value.count(' ') < 6:
                    if value.lower() in ('yes', 'no'):
                        facilities.append(name)
                    else:
                        fac_text = f"{name}: {value}"
                        if fac_text not in facilities:
                            facilities.append(fac_text)
                    i += 2
                    continue
                if value.lower() in ('yes', 'no', 'yes -', 'no -') or re.match(r'^\d+.*(spaces|tables|chairs|ft)', value.lower()) or 'yes -' in value.lower():
                    facilities.append(f"{name}: {value}" if value.lower() != 'yes' else name)
                    i += 2
                elif len(name) < 40 and name.lower() not in ('venue suitability',):
                    # Standalone facility without Yes/No value
                    if name.count(' ') <= 5:
                        facilities.append(name)
                    i += 1
                else:
                    i += 1
                if len(facilities) >= 15:
                    break
        # Fallback scan
        if not facilities:
            keywords = ['onsite parking', 'disabled access', 'kitchen', 'bar', 'stage', 'heating', 'wheelchair', 'wifi', 'projector', 'catering']
            for line in lines:
                if any(k in line.lower() for k in keywords) and len(line) < 50:
                    if line not in facilities:
                        facilities.append(line)
        return facilities[:15]

    def _extract_description(self, lines: List[str]) -> Optional[str]:
        # Description block is after "Venue size" value and before "Venue suitability"
        # Structure: ... "Venue type" / types / "Venue size" / size / [description paragraphs] / "Venue suitability"
        start_idx = None
        for i, line in enumerate(lines):
            if line.lower() == 'venue size':
                # description starts 2 lines after "Venue size"
                start_idx = i + 2
                break
            if line.lower().endswith('description') and i < 30:
                start_idx = i + 1
                break
        if start_idx is not None and start_idx < len(lines):
            # Skip metadata lines like venue type values that may be captured
            # Advance past "Venue type" values if present
            desc_parts = []
            for line in lines[start_idx:]:
                low = line.lower()
                if low in ('venue suitability', 'venue facilities', 'rooms', 'venue map', 'report a problem', 'overview', 'facilities', 'email venue', 'shortlist'):
                    break
                # Skip lines that are venue type listings (contain " / ")
                if ' / ' in line and any(k in low for k in ['venue', 'hall', 'commercial']):
                    continue
                # Skip single-word headers
                if low in ('venue type', 'venue size'):
                    continue
                # Stop before suitability boilerplate
                if 'this venue is suitable' in low:
                    break
                if len(line) > 5:
                    desc_parts.append(line)
            desc = ' '.join(desc_parts).strip()
            # Strip leading capacity duplication (e.g. "Extra Large (300+)" or "Medium (1-150)")
            desc = re.sub(r'^(Extra Large|Large|Medium|Small)\s*\(.*?\)\s*', '', desc).strip()
            if desc and len(desc) > 20:
                return desc[:900]
        return None


# Legacy sources kept as optional secondary scrapers
class DirectoryScrapers:
    """Secondary scrapers for additional directory sources."""

    def __init__(self, delay: float = 2.0):
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        })

    def scrape_venues4hire_kent_by_type(self, type_id: int, venue_type: VenueType) -> List[Venue]:
        """Scrape venues4hire by type without location filtering (calls main scraper)."""
        scraper = VenueScraper(delay=self.delay)
        return scraper.scrape_kent_venues(location_filter=None)