import csv
import json
import os
from typing import List
from datetime import datetime
from .models import Venue


class VenueStorage:
    def __init__(self, output_dir: str = 'output'):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def save_to_csv(self, venues: List[Venue], filename: str = None) -> str:
        if not venues:
            print("No venues to save")
            return ""

        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'venues_{timestamp}.csv'

        filepath = os.path.join(self.output_dir, filename)

        if not venues:
            return filepath

        fieldnames = venues[0].to_dict().keys()

        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for venue in venues:
                writer.writerow(venue.to_dict())

        print(f"Saved {len(venues)} venues to {filepath}")
        return filepath

    def save_to_json(self, venues: List[Venue], filename: str = None) -> str:
        if not venues:
            print("No venues to save")
            return ""

        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'venues_{timestamp}.json'

        filepath = os.path.join(self.output_dir, filename)

        data = [venue.to_dict() for venue in venues]

        with open(filepath, 'w', encoding='utf-8') as jsonfile:
            json.dump(data, jsonfile, indent=2, ensure_ascii=False)

        print(f"Saved {len(venues)} venues to {filepath}")
        return filepath

    def load_from_csv(self, filepath: str) -> List[Venue]:
        venues = []
        with open(filepath, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                venue = Venue(
                    name=row.get('name', ''),
                    location=row.get('location', ''),
                    venue_type=row.get('venue_type', ''),
                    website=row.get('website'),
                    capacity=row.get('capacity'),
                    parking=row.get('parking'),
                    catering=row.get('catering'),
                    accommodation=row.get('accommodation'),
                    facilities=row.get('facilities', '').split(', ') if row.get('facilities') else [],
                    contact_name=row.get('contact_name'),
                    contact_email=row.get('contact_email'),
                    contact_phone=row.get('contact_phone'),
                    description=row.get('description'),
                    address=row.get('address'),
                    postcode=row.get('postcode'),
                    source=row.get('source')
                )
                venues.append(venue)
        return venues

    def merge_venues(self, existing_file: str, new_venues: List[Venue]) -> List[Venue]:
        existing_venues = self.load_from_csv(existing_file)
        existing_names = {(v.name, v.location) for v in existing_venues}

        unique_new = [v for v in new_venues if (v.name, v.location) not in existing_names]
        return existing_venues + unique_new
