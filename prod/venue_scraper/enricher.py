"""Enrich venues by visiting their own website and harvesting social links,
contact emails and phone numbers that the directories omit."""
import re
import time
from typing import List, Optional, Dict

import requests
from bs4 import BeautifulSoup

from .models import Venue, SocialMedia
from .clean import normalize_phone, EMAIL_RE

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

SKIP_DOMAINS = ('facebook.com', 'instagram.com', 'twitter.com', 'x.com', 'linkedin.com',
                'venues4hire.org', 'weddingvenues.co.uk', 'wedding-venues.co.uk', 'venuefinder.com',
                'google.com', 'bing.com', 'yellowpages', 'yell.com', 'cylex', 'netmums',
                'foursquare')

# generic/role addresses preferred over personal-looking ones
PREFERRED_EMAIL = re.compile(r'\b(?:info|hello|enquiries|enquiry|events|bookings|booking|contact|'
                             r'weddings|sales|office|mail|reception|team)@', re.I)
ROBOT_EMAIL = re.compile(r'(png|jpg|jpeg|gif|webp|svg|sentry|@2x|\.css|\.js)$', re.I)


class Enricher:
    def __init__(self, delay: float = 0.4, timeout: int = 15):
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._domain_cache: Dict[str, Optional[dict]] = {}

    def _fetch(self, url: str):
        try:
            time.sleep(self.delay)
            r = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            if r.status_code != 200:
                return None
            return BeautifulSoup(r.text, 'lxml')
        except Exception:
            return None

    def _scrape_links(self, soup) -> SocialMedia:
        social = SocialMedia()
        for a in soup.find_all('a', href=True):
            h = a['href'].strip()
            low = h.lower()
            if 'share' in low or 'sharer' in low or '#' in h:
                continue
            if 'facebook.com' in low and not social.facebook:
                social.facebook = h
            elif ('instagram.com' in low or 'instagr.am' in low) and not social.instagram:
                social.instagram = h
            elif ('twitter.com/' in low or 'x.com/' in low) and not social.twitter:
                social.twitter = h
            elif 'linkedin.com' in low and 'company' in low and not social.linkedin:
                social.linkedin = h
            elif 'tiktok.com' in low and not social.tiktok:
                social.tiktok = h
        return social

    def _scrape_email(self, soup, text: str) -> Optional[str]:
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if 'mailto:' in href:
                m = EMAIL_RE.search(a['href'])
                if m and not ROBOT_EMAIL.search(m.group(0)):
                    return m.group(0).lower()
        cands = [m.group(0) for m in EMAIL_RE.finditer(text)]
        for c in cands:
            if ROBOT_EMAIL.search(c):
                continue
            if 'example.com' in c or 'sentry' in c:
                continue
            if PREFERRED_EMAIL.search(c):
                return c.lower()
        for c in cands:
            if ROBOT_EMAIL.search(c):
                continue
            if 'example.com' in c:
                continue
            return c.lower()
        return None

    @staticmethod
    def _scrape_phone(soup, text: str) -> Optional[str]:
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if href.startswith('tel:'):
                return normalize_phone(a['href'][4:])
        uk = re.search(r'(?:\+44\s?|0)\d{2,4}[\s\-)(]*\d{3,4}[\s\-]*\d{3,4}', text)
        if uk:
            return normalize_phone(uk.group(0))
        return None

    def enrich(self, v: Venue) -> bool:
        """Enrich a single venue from its website. Returns True if a page was fetched."""
        base = (v.website or '').strip()
        if not base:
            return False
        low = base.lower()
        if any(d in low for d in SKIP_DOMAINS):
            return False

        try:
            from urllib.parse import urlparse, urljoin
            domain = urlparse(base).netloc
        except Exception:
            domain = ''

        cached = self._domain_cache.get(domain)
        if cached is not None:
            self._apply(v, cached)
            return False

        soup = self._fetch(base)
        if soup is None:
            self._domain_cache[domain] = {}
            return False

        text = soup.get_text(' ', strip=True)
        data = {
            'social': self._scrape_links(soup),
            'email': self._scrape_email(soup, text),
            'phone': self._scrape_phone(soup, text),
        }
        self._domain_cache[domain] = data
        self._apply(v, data)
        return True

    def _apply(self, v: Venue, data: dict):
        social = data.get('social') or SocialMedia()
        if not v.social_media.facebook and social.facebook:
            v.social_media.facebook = social.facebook
        if not v.social_media.instagram and social.instagram:
            v.social_media.instagram = social.instagram
        if not v.social_media.twitter and social.twitter:
            v.social_media.twitter = social.twitter
        if not v.social_media.linkedin and social.linkedin:
            v.social_media.linkedin = social.linkedin
        if not v.social_media.tiktok and getattr(social, 'tiktok', None):
            v.social_media.tiktok = social.tiktok
        if not v.contact_email and data.get('email'):
            v.contact_email = data['email']
        if not v.contact_phone and data.get('phone'):
            v.contact_phone = data['phone']

    def enrich_venues(self, venues: List[Venue], limit: Optional[int] = None) -> int:
        """Enrich venues that are missing emails or social profiles. Returns count fetched."""
        done = 0
        for i, v in enumerate(venues):
            if limit and done >= limit:
                break
            needs = (not v.contact_email) or (not (v.social_media.instagram or
                                                   v.social_media.twitter or v.social_media.linkedin))
            if not needs:
                continue
            fetched = self.enrich(v)
            if fetched:
                done += 1
                if done % 20 == 0:
                    print(f"  [enrich] visited {done} websites so far", flush=True)
        print(f"  [enrich] visited {done} venue websites", flush=True)
        return done