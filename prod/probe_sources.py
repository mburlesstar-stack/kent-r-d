import requests
import gzip
import re

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
S = requests.Session(); S.headers.update(HEADERS)

def get_uris(url):
    r = S.get(url, timeout=30)
    c = r.content
    if c[:2] == b'\x1f\x8b':
        c = gzip.decompress(c)
    return re.findall(r'<loc>([^<]+)</loc>', c.decode('utf-8','ignore'))

# Build unique venue url list from the 3 job_listing sitemaps
allu = set()
for i in range(1, 4):
    allu |= set(u for u in get_uris(f'https://weddingvenues.co.uk/job_listing-sitemap{i}.xml') if '/venue/' in u)
allu = sorted(allu)
print('unique weddingvenues.co.uk venues:', len(allu))

# Probe structure of Hythe Imperial (a Kent venue)
r = S.get('https://weddingvenues.co.uk/venue/hythe-imperial-hotel/', timeout=25)
s = r.text
# Strip tags roughly
plain = re.sub(r'<script.*?</script>', '', s, flags=re.S)
plain = re.sub(r'<style.*?</style>', '', plain, flags=re.S)
plain = re.sub(r'<[^>]+>', '\n', plain)
lines = [l.strip() for l in plain.split('\n') if l.strip()]
print("\n=== Hythe Imperial detail text (lines 30-90) ===")
for i, l in enumerate(lines[30:95], 30):
    print(f"{i}: {l[:110]}")