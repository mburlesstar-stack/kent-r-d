"""Additional venue directory sources beyond venues4hire.org.

Sources with crawlable (server-rendered) pages:
  - weddingvenues.co.uk  (175 wedding venues, WordPress sitemap-driven)
  - wedding-venues.co.uk (curated exclusive venue directory)
"""
import gzip
import json
import re
import time
from typing import List, Optional, Dict
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .models import Venue, VenueType, SocialMedia
from .geo import matches_any

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}


class _BaseSource:
    def __init__(self, delay: float = 1.0, max_venues: Optional[int] = None):
        self.delay = delay
        self.max_venues = max_venues
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def fetch(self, url: str) -> Optional[BeautifulSoup]:
        try:
            time.sleep(self.delay)
            r = self.session.get(url, timeout=30)
            r.raise_for_status()
            return BeautifulSoup(r.text, 'lxml')
        except Exception as e:
            print(f"  [warn] fetch failed {url}: {e}")
            return None

    def fetch_sitemap(self, url: str) -> List[str]:
        try:
            r = self.session.get(url, timeout=40)
            content = r.content
            if content[:2] == b'\x1f\x8b':
                content = gzip.decompress(content)
            return re.findall(r'<loc>([^<]+)</loc>', content.decode('utf-8', 'ignore'))
        except Exception as e:
            print(f"  [warn] sitemap failed {url}: {e}")
            return []


class WeddingVenuesCo(_BaseSource):
    """Scraper for weddingvenues.co.uk - a 175+ venue UK wedding directory."""

    NAME = 'weddingvenues.co.uk'
    SITEMAPS = [f'https://weddingvenues.co.uk/job_listing-sitemap{i}.xml' for i in range(1, 4)]

    def _enumerate_venues(self) -> List[str]:
        urls = set()
        for sm in self.SITEMAPS:
            for u in self.fetch_sitemap(sm):
                if '/venue/' in u:
                    urls.add(u.rstrip('/'))
        return sorted(urls)

    @staticmethod
    def _jsonld(soup: BeautifulSoup) -> List[Dict]:
        data = []
        for tag in soup.find_all('script', type='application/ld+json'):
            try:
                obj = json.loads(tag.string or tag.get_text())
            except Exception:
                continue
            if isinstance(obj, list):
                data.extend(obj)
            else:
                data.append(obj)
        return data

    def scrape(self, location_filter: Optional[List[str]] = None) -> List[Venue]:
        urls = self._enumerate_venues()
        if self.max_venues:
            urls = urls[:self.max_venues]
        print(f"  [{self.NAME}] {len(urls)} venue pages to check...", flush=True)

        venues = []
        for url in urls:
            soup = self.fetch(url + '/')
            if soup is None:
                continue
            v = self._parse(soup, url)
            if v is None:
                continue
            if location_filter and not matches_any(v, location_filter):
                continue
            venues.append(v)
        return venues

    def _parse(self, soup: BeautifulSoup, url: str) -> Optional[Venue]:
        try:
            ld = self._jsonld(soup)
            entity = next((o for o in ld if o.get('@type') == 'LocalBusiness' or o.get('@type') == 'Venue'), None)
            if entity is None:
                entity = next((o for o in ld if isinstance(o.get('@type'), str)), None) if ld else None

            # name
            name = None
            h1 = soup.find('h1')
            if h1 and h1.get_text(strip=True):
                name = h1.get_text(strip=True).strip(' -')
            if not name:
                name = (entity or {}).get('name') if entity else None
            if not name and soup.title:
                name = re.sub(r'\s*[\|\-].*$', '', soup.title.text).strip()
            if not name:
                return None

            text = soup.get_text('\n', strip=True)
            lines = [l.strip() for l in text.split('\n') if l.strip()]

            # address / postcode
            address = None
            postcode = None
            addr = (entity or {}).get('address') if entity else None
            if isinstance(addr, dict):
                addr = ' '.join(str(addr.get(k, '')) for k in
                                ('streetAddress', 'addressLocality', 'addressRegion', 'postalCode')).strip()
            pc = re.search(r'\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b', text)
            if pc:
                postcode = pc.group(0)
            if addr and not address:
                address = addr
            if not address:
                m = re.search(r'Address[:\s]*([^\n]+)', text, re.I)
                if m:
                    address = m.group(1).strip()

            location = (entity or {}).get('address') or venue_city(text)
            if isinstance(location, dict):
                location = location.get('addressLocality', '')
            if not location:
                # "Venue Name | Kent" line
                pipe_line = next((l for l in lines if '|' in l and 'Kent' in l), None)
                if pipe_line:
                    m = re.search(r'\|\s*([A-Za-z ]+)\s*$', pipe_line)
                    location = m.group(1).strip() if m else 'Kent'
                else:
                    location = venue_city(name + ' ' + text) or 'Kent'

            # facilities
            facilities = []
            fac = soup.find('h3', string=re.compile(r'Facilities', re.I))
            if fac:
                parent = fac.find_parent()
                for label in parent.find_all_next(['li', 'div', 'span'], limit=40):
                    t = label.get_text(strip=True)
                    if t and len(t) < 60 and t not in facilities:
                        # stop conditions
                        if t.lower() in ('venue description', 'reviews', 'photo gallery', 'offers'):
                            break
                        facilities.append(t)
                    if len(facilities) >= 18:
                        break
            if not facilities:
                # fallback: text-block between "Venue Facilities" and "Venue Description"
                try:
                    fi = lines.index('Venue Facilities')
                except ValueError:
                    fi = None
                di = lines.index('Venue Description') if 'Venue Description' in lines else None
                if di is None:
                    di = lines.index('Venue Description') if any('Venue Description' in l for l in lines) else None
                if fi is not None:
                    end = di if di and di > fi else min(fi + 40, len(lines))
                    for t in lines[fi + 1:end]:
                        if t.lower() in ('venue description', 'reviews', 'photo gallery', 'offers', 'enquiry'):
                            break
                        if len(t) < 60 and not re.search(r'capacity|guests?|reception', t, re.I):
                            facilities.append(t)
                    facilities = facilities[:18]

            # description
            description = None
            desc = soup.find('h3', string=re.compile(r'Venue Description', re.I))
            if desc:
                dd = desc.find_next_sibling('p') or desc.find_next('p')
                if dd:
                    description = dd.get_text(' ', strip=True)[:900]
            if not description:
                di = next((i for i, l in enumerate(lines)
                           if re.search(r'venue description', l, re.I)), None)
                if di is not None:
                    body = []
                    for l in lines[di + 1:]:
                        low = l.lower()
                        if low in ('venue facilities', 'reviews', 'photo gallery', 'offers') or \
                           re.search(r'capacity[: ]+\d|guests?', low):
                            break
                        if len(l) > 40:
                            body.append(l)
                        if len(body) >= 4:
                            break
                    description = ' '.join(body)[:900] if body else None

            # capacities
            capacity = None
            caps = re.findall(r'(?:Ceremony|Breakfast|Reception)\s+capacity[:\s]*(\d+)\s*guests?',
                              text, re.I)
            if caps:
                capacity = f"Weekend: up to {max(int(c) for c in caps)} guests"
            else:
                m = re.search(r'sits?\s*(\d+)|up to\s*(\d+)\s*(?:guests?|delegates?|people)', text, re.I)
                if m:
                    n = m.group(1) or m.group(2)
                    capacity = f"up to {n} guests"

            # contacts
            email = None
            mailto = soup.find('a', href=lambda h: h and 'mailto:' in h)
            if mailto:
                email = mailto['href'].replace('mailto:', '').split('?')[0]
            if not email:
                em = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
                if em:
                    email = em.group(0)
            website = None
            tel = re.search(r'\b0\d{3,4}\s?\d{6,7}\b', text)
            phone = tel.group(0) if tel else None

            # social
            social = SocialMedia()
            content_links = soup.find_all('a', href=True)
            for a in content_links:
                href = a['href'].lower()
                if 'facebook.com' in href and 'venues4hire' not in href and not social.facebook:
                    social.facebook = a['href']
                elif 'instagram.com' in href and not social.instagram:
                    social.instagram = a['href']
                elif ('twitter.com' in href or 'x.com/' in href) and not social.twitter:
                    social.twitter = a['href']

            venue = Venue(
                name=name,
                location=location,
                venue_type=VenueType.WEDDING,
                website=website,
                capacity=capacity,
                parking='Car parking listed' if 'Car Parking' in facilities else None,
                catering=None,
                accommodation=f"{c} bedrooms" if (c := re.search(r'(\d+)\s+en-suite bedrooms?', text, re.I)) else None,
                facilities=facilities,
                contact_email=email,
                contact_phone=phone,
                social_media=social,
                description=description,
                address=address,
                postcode=postcode,
                source=self.NAME,
                additional_info={'source_url': url},
            )
            try:
                if venue.website is None:
                    for a in content_links:
                        h = a['href']
                        if h.startswith('http') and 'weddingvenues.co.uk' not in h and 'facebook' not in h.lower():
                            venue.website = h
                            break
            except Exception:
                pass
            return venue
        except Exception as e:
            print(f"  [warn] parse error {url}: {e}")
            return None


def venue_city(text: str) -> Optional[str]:
    for pat in [r'\b(Canterbury|Maidstone|Ashford|Tunbridge Wells|Sevenoaks|Tonbridge|Dartford|Folkestone|Kent)\b']:
        m = re.search(pat, text, re.I)
        if m:
            return m.group(1)
    return None


class WeddingVenuesCoUk(_BaseSource):
    """Scraper for wedding-venues.co.uk - small curated UK venue directory."""

    NAME = 'wedding-venues.co.uk'
    SITEMAP = 'https://wedding-venues.co.uk/venues-sitemap.xml'

    def scrape(self, location_filter: Optional[List[str]] = None) -> List[Venue]:
        urls = [u for u in self.fetch_sitemap(self.SITEMAP) if '/venues/' in u and u.rstrip('/').endswith(u.rsplit('/', 1)[1])]
        urls = sorted(set(urls))
        if self.max_venues:
            urls = urls[:self.max_venues]
        print(f"  [{self.NAME}] {len(urls)} venue pages to check...", flush=True)
        venues = []
        for url in urls:
            soup = self.fetch(url)
            if soup is None:
                continue
            name = None
            h1 = soup.find('h1')
            if h1:
                name = h1.get_text(strip=True)
            if not name and soup.title:
                name = re.sub(r'\s*[\|\-].*$', '', soup.title.text).strip()
            if not name:
                continue
            text = soup.get_text('\n', strip=True)
            lines = [l.strip() for l in text.split('\n') if l.strip()]

            # location indicator from breadcrumb / tagline line "County"
            location = None
            for l in lines[:40]:
                if re.search(r'\b(Kent|Canterbury|Maidstone|Ashford|Tunbridge|Sevenoaks|Tonbridge|Dartford|Folkestone)\b', l, re.I):
                    m = re.search(r'\b(Kent|Canterbury|Maidstone|Ashford|Tunbridge|Sevenoaks|Tonbridge|Dartford|Folkestone)\b', l, re.I)
                    location = m.group(1)
                    break

            pc = re.search(r'\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b', text)
            postcode = pc.group(0) if pc else None
            em = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
            tel = re.search(r'\b0\d{3,4}\s?\d{6,7}\b', text)

            website = None
            for a in soup.find_all('a', href=True):
                h = a['href']
                if h.startswith('http') and 'wedding-venues.co.uk' not in h and \
                   not any(d in h.lower() for d in ('facebook', 'instagram', 'twitter', 'x.com', 'linkedin')):
                    website = h
                    break

            social = SocialMedia()
            for a in soup.find_all('a', href=True):
                low = a['href'].lower()
                if 'facebook.com' in low and not social.facebook:
                    social.facebook = a['href']
                elif 'instagram.com' in low and not social.instagram:
                    social.instagram = a['href']
                elif ('twitter.com/' in low or 'x.com/' in low) and not social.twitter:
                    social.twitter = a['href']
                elif 'linkedin.com' in low and 'company' in low and not social.linkedin:
                    social.linkedin = a['href']

            v = Venue(
                name=name,
                location=location or 'Kent',
                venue_type=VenueType.WEDDING,
                website=website,
                capacity=None,
                contact_email=em.group(0) if em else None,
                contact_phone=tel.group(0) if tel else None,
                description=' '.join(l for l in lines if len(l) > 60)[:600] or None,
                address=None,
                postcode=postcode,
                social_media=social,
                source=self.NAME,
                additional_info={'source_url': url},
            )
            if location_filter and not matches_any(v, location_filter):
                continue
            venues.append(v)
        return venues