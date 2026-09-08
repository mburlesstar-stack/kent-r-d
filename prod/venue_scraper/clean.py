"""Cleaning helpers: UK phone normalisation and per-venue field cleanup."""
import re
from typing import Optional

EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
SOCIAL_DOMAINS = ('facebook.com', 'instagram.com', 'twitter.com', 'x.com/',
                  'linkedin.com', 'youtube.com', 'tiktok.com', 'pinterest.com')


def _split_numbers(raw: str):
    parts = re.split(r'[/,;\n]+', raw or '')
    return [p.strip() for p in parts if p.strip()]


def _format_uk(digits: str) -> str:
    """Format an 11-digit (or 10-digit) UK number in national format."""
    n = len(digits)
    if n == 13 and digits.startswith('44'):
        digits, n = '0' + digits[2:], 11
    if n == 12 and digits.startswith('44'):
        digits, n = '0' + digits[2:], 11
    if digits.startswith('0') and n == 11:
        if digits.startswith('020'):
            return f"{digits[:3]} {digits[3:7]} {digits[7:]}"
        if digits.startswith('0300'):
            return f"{digits[:4]} {digits[4:7]} {digits[7:]}"
        if digits.startswith('0800'):
            return f"{digits[:4]} {digits[4:7]} {digits[7:]}"
        return f"{digits[:5]} {digits[5:]}"
    if digits.startswith('0') and n == 10:
        if digits.startswith('02'):
            return f"{digits[:3]} {digits[3:6]} {digits[6:]}"
        return f"{digits[:4]} {digits[4:]}"
    return None


def normalize_phone(raw: Optional[str]) -> Optional[str]:
    """Normalize a UK phone string to national format, e.g. '01622 717473'."""
    if not raw:
        return None
    out = []
    for part in _split_numbers(raw):
        p = part.lower()
        # cut off extensions
        for sep in (' ext', ' x ', ' extension', ' ext.', ' x.'):
            if sep in ' ' + p:
                p = p.split(sep)[0]
                break
        s = re.sub(r'[^0-9+]', '', p)
        if s.startswith('+44'):
            s = '0' + s[3:]
        elif s.startswith('0044'):
            s = '0' + s[4:]
        elif s.startswith('440'):
            s = '0' + s[2:]
        elif s.startswith('44') and len(s) == 12:
            s = '0' + s[2:]
        if not s.startswith('0'):
            # bare national like '1622 717473'
            if len(s) in (9, 10):
                s = '0' + s
            else:
                continue
        formatted = _format_uk(s)
        if formatted:
            out.append(formatted)
    return ' / '.join(out) if out else None


def _website_to_social(url: str) -> Optional[str]:
    low = url.lower()
    for dom in SOCIAL_DOMAINS:
        if dom in low:
            return dom.split('.')[0] if dom != 'x.com/' else 'twitter'
    return None


def _clean_main_website(v) -> Optional[str]:
    """Return a clean external website (not a social/mailto/directory URL) or None."""
    w = (v.website or '').strip()
    if not w:
        return None
    if w.lower().startswith('mailto:'):
        return None
    if '@' in w and '.' in w and not w.startswith('http'):
        return None
    if not re.match(r'^https?://', w, re.I):
        w = 'http://' + w
    low = w.lower()
    for dom in SOCIAL_DOMAINS + ('venues4hire.org', 'weddingvenues.co.uk',
                                 'wedding-venues.co.uk', 'venuefinder.com'):
        if dom in low:
            return None
    return w


def clean_venue(v):
    """Apply shared data-quality cleanup to a venue (in place)."""
    if v.contact_phone:
        v.contact_phone = normalize_phone(v.contact_phone)

    if v.contact_email:
        email = v.contact_email.strip().strip('.;>').lower()
        m = EMAIL_RE.search(email)
        v.contact_email = m.group(0) if m else None

    # Website: avoid social/directory URLs masquerading as websites
    w = _clean_main_website(v)
    if w is None and v.website:
        dom = _website_to_social(v.website)
        if dom == 'facebook' and not v.social_media.facebook:
            v.social_media.facebook = v.website
        elif dom == 'instagram' and not v.social_media.instagram:
            v.social_media.instagram = v.website
        elif dom == 'twitter' and not v.social_media.twitter:
            v.social_media.twitter = v.website
        elif dom == 'linkedin' and not v.social_media.linkedin:
            v.social_media.linkedin = v.website
    v.website = w

    # Facilities: drop dash placeholders, zero-count values, and duplicates
    cleaned = []
    for f in (v.facilities or []):
        f = (f or '').strip()
        if not f:
            continue
        if re.fullmatch(r'[-–—_/\\]+', f):
            continue
        # "Onsite parking: 0 spaces" → just "Onsite parking"
        zero_m = re.match(r'^([^:]+):\s*0\s+\w', f)
        if zero_m:
            f = zero_m.group(1)
        if f not in cleaned:
            cleaned.append(f)
    v.facilities = cleaned[:20]

    return v