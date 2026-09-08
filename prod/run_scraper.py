import argparse
import sys
import os
import time
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from venue_scraper.models import Venue, VenueType
from venue_scraper.scraper import VenueScraper
from venue_scraper.sources import WeddingVenuesCo, WeddingVenuesCoUk
from venue_scraper.storage import VenueStorage
from venue_scraper.geo import LOCATIONS, detect_town
from venue_scraper.tags import infer_extra_tags
from venue_scraper.clean import clean_venue
from venue_scraper.enricher import Enricher


def parse_args():
    parser = argparse.ArgumentParser(
        description='Scrape venue information from Kent, UK (Maidstone, Canterbury, Tunbridge Wells, '
                    'Ashford, Sevenoaks, Tonbridge, Dartford, Folkestone)'
    )
    parser.add_argument(
        '--locations',
        nargs='+',
        choices=LOCATIONS + [l.replace('-', ' ') for l in LOCATIONS],
        default=LOCATIONS,
        help='Locations to scrape (default: all 8 locations)'
    )
    parser.add_argument(
        '--output',
        default='venues',
        help='Output filename base (without extension)'
    )
    parser.add_argument(
        '--format',
        choices=['csv', 'json', 'both'],
        default='both',
        help='Output format (default: both CSV and JSON)'
    )
    parser.add_argument(
        '--delay',
        type=float,
        default=0.5,
        help='Delay between requests in seconds (default: 0.5)'
    )
    parser.add_argument(
        '--sources',
        nargs='+',
        choices=['venues4hire', 'weddingvenues'],
        default=['venues4hire', 'weddingvenues'],
        help='Which directories to scrape (default: all)'
    )
    parser.add_argument(
        '--no-filter',
        action='store_true',
        help='Do not filter results by location (collect all venues per source)'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=0,
        help='Limit number of pages/venues scraped per source (0 = unlimited)'
    )
    parser.add_argument(
        '--no-enrich',
        action='store_true',
        help='Skip enriching venues from their own websites'
    )
    return parser.parse_args()


def scrape_sources(args):
    location_list = None if args.no_filter else [l.strip().replace(' ', '-') for l in args.locations]

    all_venues = []

    if 'venues4hire' in args.sources:
        print("=" * 60)
        print("Source 1/2: venues4hire.org (Kent county directory)")
        print("=" * 60)
        scraper = VenueScraper(delay=args.delay)
        all_venues += scraper.scrape_kent_venues(
            location_filter=location_list,
            max_pages=args.limit if args.limit else None
        )

    if 'weddingvenues' in args.sources:
        print("\n" + "=" * 60)
        print("Source 2/2: weddingvenues.co.uk (UK wedding venue directory)")
        print("=" * 60)
        sources = [
            WeddingVenuesCo(delay=args.delay, max_venues=args.limit if args.limit else None),
            WeddingVenuesCoUk(delay=args.delay, max_venues=args.limit if args.limit else None),
        ]
        for src in sources:
            all_venues += src.scrape(location_filter=location_list)

    # Dedupe by name + postcode
    seen = set()
    unique = []
    for v in all_venues:
        key = (v.name.strip().lower().rstrip(' -'), (v.postcode or '').strip().lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(v)

    # Enrich: town detection + inferred tags + data-quality cleanup
    if not args.no_enrich:
        enricher = Enricher(delay=max(0.25, args.delay), timeout=15)
        fetched = enricher.enrich_venues(unique)
        print(f"Enriched {fetched} venues from their own websites")
    else:
        print("Skipping website enrichment (--no-enrich)")

    for v in unique:
        clean_venue(v)
        town = detect_town(v)
        if town:
            v.additional_info['detected_town'] = town
        infer_extra_tags(v)

    return unique


def main():
    args = parse_args()
    storage = VenueStorage()

    print("=" * 60)
    print("KENT VENUE SCRAPER (MULTI-SOURCE)")
    print("=" * 60)
    print(f"Sources: {', '.join(args.sources)}")
    if not args.no_filter:
        print(f"Towns: {', '.join(args.locations)}")
    print(f"Delay: {args.delay}s")

    t0 = time.time()
    unique = scrape_sources(args)
    print(f"\nScraped & deduplicated in {time.time()-t0:.1f}s")

    print(f"\n{'='*60}")
    print(f"Total unique venues collected: {len(unique)}")
    print(f"{'='*60}")

    if args.format in ('csv', 'both'):
        csv_file = storage.save_to_csv(unique, f'{args.output}.csv')
        if csv_file:
            print(f"CSV saved to: {os.path.abspath(csv_file)}")
    if args.format in ('json', 'both'):
        json_file = storage.save_to_json(unique, f'{args.output}.json')
        if json_file:
            print(f"JSON saved to: {os.path.abspath(json_file)}")
    print()

    print(f"{'='*60}")
    print("SUMMARY BY TOWN:")
    loc_counts = {}
    for v in unique:
        town = v.additional_info.get('detected_town')
        if town:
            loc_counts[town] = loc_counts.get(town, 0) + 1
    for location in args.locations:
        slug = location.replace(' ', '-')
        print(f"  {location.title().replace('-', ' ')}: {loc_counts.get(slug, 0)} venues")

    print(f"\n{'='*60}")
    print("SUMMARY BY SOURCE:")
    src_counts = {}
    for v in unique:
        src_counts[v.source] = src_counts.get(v.source, 0) + 1
    for s, c in sorted(src_counts.items()):
        print(f"  {s}: {c} venues")

    print(f"\n{'='*60}")
    print("SUMMARY BY VENUE TYPE:")
    type_counts = {}
    for v in unique:
        t = v.venue_type.value
        type_counts[t] = type_counts.get(t, 0) + 1
    for t, c in sorted(type_counts.items()):
        print(f"  {t}: {c} venues")


if __name__ == '__main__':
    main()