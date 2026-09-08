import os
import sys
import json
import csv
import glob
import threading
import re
import time
import subprocess
from datetime import datetime
from flask import Flask, render_template, jsonify, request, send_file, send_from_directory

# Windows console defaults to cp1252 which can't print the audit's unicode output
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

app = Flask(__name__)
ENV = os.environ.get("APP_ENV", "prod")

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'output')
LOCATIONS = ['maidstone','canterbury','tunbridge-wells','ashford','sevenoaks','tonbridge','dartford','folkestone']
VENUE_TYPES = ["Wedding Venue","Meeting Room","Conference Venue","Party Venue","Christmas Party Venue","Training Venue","Corporate Venue","Hotel with Event Space","Restaurant with Private Room"]
AUDIT_CATEGORIES = ['description','capacity','photos','facilities','parking','catering','accommodation','accessibility','address','contact']
AUDIT_FILE = os.path.join(OUTPUT_DIR, 'kentvenues-audit-data.json')

# Scrape state
scrape_state = {"running": False, "progress": "", "last_result": None, "error": None, "log": []}
_orig_print = print  # keep reference to avoid recursion when patching print

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    scrape_state["log"].append(entry)
    # keep last 100
    if len(scrape_state["log"]) > 100:
        scrape_state["log"] = scrape_state["log"][-100:]
    _orig_print(entry, flush=True)

def load_venues():
    """Load all venues from output JSON/CSV - prefers newest JSON (ignoring audit/export files)"""
    venues = []
    json_files = sorted(glob.glob(os.path.join(OUTPUT_DIR, "*.json")), key=os.path.getmtime, reverse=True)
    json_files = [f for f in json_files if not os.path.basename(f).startswith(('kentvenues-audit', '_audit_export', '_export'))]
    csv_files = sorted(glob.glob(os.path.join(OUTPUT_DIR, "*.csv")), key=os.path.getmtime, reverse=True)
    csv_files = [f for f in csv_files if not os.path.basename(f).startswith(('kentvenues-audit', '_audit_export', '_export'))]

    if json_files:
        try:
            with open(json_files[0], 'r', encoding='utf-8') as f:
                data = json.load(f)
                for row in data:
                    # normalize
                    venues.append(row)
            return venues, json_files[0]
        except Exception as e:
            print(f"Error loading json: {e}")

    if csv_files:
        try:
            with open(csv_files[0], 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    venues.append(row)
            return venues, csv_files[0]
        except Exception as e:
            print(f"Error loading csv: {e}")

    # Try demo files too
    for name in ['demo_quick.json', 'venues.json', 'venues.csv']:
        p = os.path.join(OUTPUT_DIR, name)
        if os.path.exists(p):
            try:
                if p.endswith('.json'):
                    with open(p, 'r', encoding='utf-8') as f:
                        return json.load(f), p
                else:
                    with open(p, 'r', encoding='utf-8') as f:
                        return list(csv.DictReader(f)), p
            except:
                pass
    return [], None

def filter_venues(venues, search="", locations=None, venue_types=None, capacity_min=None):
    filtered = venues
    if search:
        s = search.lower()
        filtered = [v for v in filtered if s in (v.get('name','') or '').lower()
                    or s in (v.get('location','') or '').lower()
                    or s in (v.get('address','') or '').lower()
                    or s in (v.get('postcode','') or '').lower()
                    or s in (v.get('description','') or '').lower()
                    or s in (v.get('facilities','') or '').lower()
                    or s in (v.get('venue_type','') or '').lower()]
    if locations:
        locs = [l.replace('-',' ').lower() for l in locations]
        def matches(v):
            combined = ' '.join([v.get('address','') or '', v.get('postcode','') or '', v.get('location','') or '', v.get('name','') or '']).lower()
            norm = re.sub(r'[^a-z]+','', combined)
            for loc in locs:
                loc_norm = re.sub(r'[^a-z]+','', loc)
                if loc_norm in norm:
                    return True
            # also check detected_town / location field directly
            dt = re.sub(r'[^a-z]+','', (v.get('detected_town','') or '').lower())
            if dt and any(dt == re.sub(r'[^a-z]+','', x) for x in locs):
                return True
            return False
        filtered = [v for v in filtered if matches(v)]
    if venue_types:
        vts = [x.lower() for x in venue_types]
        filtered = [v for v in filtered if (v.get('venue_type','') or '').lower() in vts]
    return filtered

@app.route('/')
def index():
    return render_template('index.html', locations=LOCATIONS, venue_types=VENUE_TYPES, audit_categories=AUDIT_CATEGORIES, env=ENV)

@app.route('/api/venues')
def api_venues():
    search = request.args.get('search','').strip()
    locations = request.args.getlist('locations')
    # support comma-separated too
    if len(locations)==1 and ',' in locations[0]:
        locations = [x.strip() for x in locations[0].split(',') if x.strip()]
    venue_types = request.args.getlist('types')
    if len(venue_types)==1 and ',' in venue_types[0]:
        venue_types = [x.strip() for x in venue_types[0].split(',') if x.strip()]
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 24))
    sort = request.args.get('sort','name')

    venues, source = load_venues()
    filtered = filter_venues(venues, search, locations or None, venue_types or None)

    # sorting
    if sort == 'name':
        filtered.sort(key=lambda x: (x.get('name') or '').lower())
    elif sort == 'location':
        filtered.sort(key=lambda x: (x.get('location') or '').lower())
    elif sort == 'capacity':
        filtered.sort(key=lambda x: (x.get('capacity') or ''))

    total = len(filtered)
    total_pages = (total + per_page -1)//per_page if per_page else 1
    start = (page-1)*per_page
    end = start + per_page
    page_items = filtered[start:end]

    # stats for current filter
    loc_counts = {}
    type_counts = {}
    for v in filtered:
        town = (v.get('detected_town') or v.get('location') or '').strip()
        # normalize town to our locations for stats
        low = town.lower().replace('-', ' ')
        mapped = None
        for loc in LOCATIONS:
            if loc.replace('-',' ') in low or low in loc:
                mapped = loc
                break
        if mapped:
            loc_counts[mapped] = loc_counts.get(mapped, 0)+1
        vt = v.get('venue_type') or 'Unknown'
        type_counts[vt] = type_counts.get(vt,0)+1

    return jsonify({
        "venues": page_items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "source": os.path.basename(source) if source else None,
        "stats": {"loc_counts": loc_counts, "type_counts": type_counts}
    })

@app.route('/api/stats')
def api_stats():
    venues, source = load_venues()
    total = len(venues)
    loc_counts = {}
    type_counts = {}
    for v in venues:
        town = v.get('detected_town') or v.get('location') or ''
        # try to map
        low = town.lower().replace('-', ' ')
        found=None
        for loc in LOCATIONS:
            if loc.replace('-',' ') in low:
                found=loc
                break
        if found:
            loc_counts[found] = loc_counts.get(found,0)+1
        vt = v.get('venue_type') or 'Unknown'
        type_counts[vt] = type_counts.get(vt,0)+1
    # also include file info
    files = []
    for p in sorted(glob.glob(os.path.join(OUTPUT_DIR, "*.*")), key=os.path.getmtime, reverse=True)[:5]:
        files.append({"name": os.path.basename(p), "size": os.path.getsize(p), "mtime": os.path.getmtime(p)})
    return jsonify({"total": total, "loc_counts": loc_counts, "type_counts": type_counts, "source": os.path.basename(source) if source else None, "files": files})

@app.route('/api/export/<fmt>')
def api_export(fmt):
    venues, source = load_venues()
    search = request.args.get('search','').strip()
    locations = request.args.getlist('locations')
    if len(locations)==1 and ',' in locations[0]:
        locations = [x.strip() for x in locations[0].split(',') if x.strip()]
    venue_types = request.args.getlist('types')
    if len(venue_types)==1 and ',' in venue_types[0]:
        venue_types = [x.strip() for x in venue_types[0].split(',') if x.strip()]
    filtered = filter_venues(venues, search, locations or None, venue_types or None)
    if fmt == 'json':
        tmp = os.path.join(OUTPUT_DIR, '_export.json')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(filtered, f, indent=2, ensure_ascii=False)
        return send_file(tmp, as_attachment=True, download_name='venues_export.json', mimetype='application/json')
    elif fmt == 'csv':
        if not filtered:
            return jsonify({"error": "no venues to export"}), 400
        tmp = os.path.join(OUTPUT_DIR, '_export.csv')
        fieldnames = filtered[0].keys()
        with open(tmp, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for row in filtered:
                w.writerow(row)
        return send_file(tmp, as_attachment=True, download_name='venues_export.csv', mimetype='text/csv')
    else:
        return jsonify({"error": "unknown format"}), 400

# ---------------- KentVenues.co.uk Listing Audit ----------------

audit_state = {"running": False, "progress": "", "last_result": None, "error": None, "log": []}

def log_audit(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    audit_state["log"].append(entry)
    if len(audit_state["log"]) > 200:
        audit_state["log"] = audit_state["log"][-200:]
    _orig_print(entry, flush=True)

def load_audit():
    """Load audit results JSON -> (results, meta) or (None, None)"""
    if not os.path.exists(AUDIT_FILE):
        return None, None
    try:
        with open(AUDIT_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        meta = data.get('meta', {}) or {}
        meta['file_mtime'] = datetime.fromtimestamp(os.path.getmtime(AUDIT_FILE)).isoformat(timespec='seconds')
        meta['exists'] = True
        return data.get('results', []), meta
    except Exception as e:
        print(f"Error loading audit data: {e}")
        return None, None

def filter_audit(results, search="", severity=None, category=None, unclaimed=False, detail_filters=None):
    filtered = results
    if search:
        s = search.lower()
        filtered = [v for v in filtered if s in (v.get('name','') or '').lower()
                    or s in (v.get('slug','') or '').lower()]
    if severity == 'critical':
        filtered = [v for v in filtered if any(i.get('severity') == 'critical' for i in v.get('issues', []))]
    elif severity == 'warning':
        filtered = [v for v in filtered if any(i.get('severity') == 'warning' for i in v.get('issues', []))]
    elif severity == 'suggestion':
        filtered = [v for v in filtered if any(i.get('severity') in ('suggestion', 'info') for i in v.get('issues', []))]
    elif severity == 'good':
        filtered = [v for v in filtered if not v.get('issues')]
    if category:
        filtered = [v for v in filtered if any(i.get('category') == category for i in v.get('issues', []))]
    if unclaimed:
        filtered = [v for v in filtered if v.get('unclaimed')]
    if detail_filters:
        for key, val in detail_filters.items():
            if val == 'yes':
                filtered = [v for v in filtered if v.get(key)]
            elif val == 'no':
                filtered = [v for v in filtered if not v.get(key)]
    return filtered

def audit_stats(results):
    total = len(results)
    if not total:
        return {"total": 0}
    def has_sev(v, sev): return any(i.get('severity') == sev for i in v.get('issues', []))
    cat_counts = {}
    for cat in AUDIT_CATEGORIES:
        venues_with = sum(1 for v in results if any(i.get('category') == cat for i in v.get('issues', [])))
        crit = sum(1 for v in results for i in v.get('issues', []) if i.get('category') == cat and i.get('severity') == 'critical')
        cat_counts[cat] = {"venues": venues_with, "critical": crit}
    buckets = {"0-20": 0, "21-40": 0, "41-60": 0, "61-80": 0, "81-100": 0}
    for v in results:
        s = v.get('score', 0) or 0
        if s <= 20: buckets["0-20"] += 1
        elif s <= 40: buckets["21-40"] += 1
        elif s <= 60: buckets["41-60"] += 1
        elif s <= 80: buckets["61-80"] += 1
        else: buckets["81-100"] += 1
    return {
        "total": total,
        "critical_venues": sum(1 for v in results if has_sev(v, 'critical')),
        "warning_venues": sum(1 for v in results if has_sev(v, 'warning')),
        "good_venues": sum(1 for v in results if not v.get('issues')),
        "unclaimed": sum(1 for v in results if v.get('unclaimed')),
        "avg_score": round(sum(v.get('score', 0) or 0 for v in results) / total, 1),
        "category_counts": cat_counts,
        "score_buckets": buckets,
    }

@app.route('/api/audit')
def api_audit():
    results, meta = load_audit()
    if results is None:
        return jsonify({"error": "no audit data yet — run the KentVenues audit from the Scrape panel",
                        "results": [], "total": 0, "page": 1, "total_pages": 1,
                        "stats": audit_stats([]), "meta": {"exists": False}})
    search = request.args.get('search', '').strip()
    severity = request.args.get('severity', '') or None
    category = request.args.get('category', '') or None
    unclaimed = request.args.get('unclaimed', '') in ('1', 'true', 'True')
    sort = request.args.get('sort', 'score')
    page = max(1, int(request.args.get('page', 1)))
    per_page = max(1, int(request.args.get('per_page', 24)))
    detail_filters = {}
    for key in ('hasAddress','hasEmail','hasPhone','hasWebsite',
                'hasCapacity','hasParking','hasCatering','hasAccommodation','hasAccessibility'):
        val = request.args.get('detail_'+key, '')
        if val in ('yes','no'):
            detail_filters[key] = val

    filtered = filter_audit(results, search, severity, category, unclaimed, detail_filters)

    def crit_count(v): return sum(1 for i in v.get('issues', []) if i.get('severity') == 'critical')
    if sort == 'score':
        filtered.sort(key=lambda v: ((v.get('score', 0) or 0), crit_count(v)))
    elif sort == 'score-desc':
        filtered.sort(key=lambda v: (-(v.get('score', 0) or 0), -crit_count(v)))
    elif sort == 'name':
        filtered.sort(key=lambda v: (v.get('name') or '').lower())
    elif sort == 'issues':
        filtered.sort(key=lambda v: (-len(v.get('issues', [])), (v.get('score', 0) or 0)))

    total = len(filtered)
    total_pages = (total + per_page - 1) // per_page if per_page else 1
    start = (page - 1) * per_page
    page_items = filtered[start:start + per_page]

    return jsonify({
        "results": page_items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "stats": audit_stats(filtered),
        "meta": meta,
    })

@app.route('/api/audit/stats')
def api_audit_stats():
    results, meta = load_audit()
    if results is None:
        return jsonify({"error": "no audit data yet", "stats": audit_stats([]), "meta": {"exists": False}}), 404
    return jsonify({"stats": audit_stats(results), "meta": meta})

@app.route('/api/audit/export/<fmt>')
def api_audit_export(fmt):
    results, meta = load_audit()
    if not results:
        return jsonify({"error": "no audit data to export"}), 400
    search = request.args.get('search', '').strip()
    severity = request.args.get('severity', '') or None
    category = request.args.get('category', '') or None
    unclaimed = request.args.get('unclaimed', '') in ('1', 'true', 'True')
    detail_filters = {}
    for key in ('hasAddress','hasEmail','hasPhone','hasWebsite',
                'hasCapacity','hasParking','hasCatering','hasAccommodation','hasAccessibility'):
        val = request.args.get('detail_'+key, '')
        if val in ('yes','no'):
            detail_filters[key] = val
    filtered = filter_audit(results, search, severity, category, unclaimed, detail_filters)

    if fmt == 'json':
        tmp = os.path.join(OUTPUT_DIR, '_audit_export.json')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({"results": filtered, "meta": meta}, f, indent=2, ensure_ascii=False)
        return send_file(tmp, as_attachment=True, download_name='kentvenues_audit_export.json', mimetype='application/json')

    elif fmt == 'csv':
        if not filtered:
            return jsonify({"error": "no venues match the current filters"}), 400
        def yn(b): return 'Yes' if b else 'No'
        def severity_of(v):
            if any(i.get('severity') == 'critical' for i in v.get('issues', [])): return 'Critical'
            if any(i.get('severity') == 'warning' for i in v.get('issues', [])): return 'Warning'
            if not v.get('issues'): return 'Good'
            return 'Suggestions'
        fieldnames = ['Venue Name','URL','Score','Severity','Unclaimed Listing','Description Length',
                      'Photo Count','Amenity Count','Has Capacity','Has Parking','Has Catering',
                      'Has Accommodation','Has Accessibility','Has Address','Has Email','Email Address','Email Source',
                      'Has Phone','Has Website','Room Count','Issue Count',
                      'Critical Issues','Warnings','Suggestions']
        tmp = os.path.join(OUTPUT_DIR, '_audit_export.csv')
        with open(tmp, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(fieldnames)
            for v in filtered:
                issues = v.get('issues', [])
                w.writerow([
                    v.get('name',''), v.get('url',''), v.get('score',0), severity_of(v),
                    yn(v.get('unclaimed')), v.get('descriptionLength',0), v.get('photoCount',0),
                    v.get('amenityCount',0), yn(v.get('hasCapacity')), yn(v.get('hasParking')),
                    yn(v.get('hasCatering')), yn(v.get('hasAccommodation')), yn(v.get('hasAccessibility')),
                    yn(v.get('hasAddress')),
                    yn(v.get('hasEmail')), v.get('emailValue',''), v.get('emailSource',''),
                    yn(v.get('hasPhone')), yn(v.get('hasWebsite')),
                    v.get('roomCount',0), len(issues),
                    sum(1 for i in issues if i.get('severity')=='critical'),
                    sum(1 for i in issues if i.get('severity')=='warning'),
                    sum(1 for i in issues if i.get('severity') in ('suggestion','info')),
                ])
        return send_file(tmp, as_attachment=True, download_name='kentvenues_audit_export.csv', mimetype='text/csv')

    else:
        return jsonify({"error": "unknown format"}), 400

def audit_worker():
    try:
        audit_state["running"] = True
        audit_state["error"] = None
        audit_state["log"] = []
        audit_state["progress"] = "Starting KentVenues audit..."
        log_audit("Running: node audit.js (467 listings, typically 3-5 minutes)")
        t0 = time.time()
        proc = subprocess.Popen(
            ['node', 'audit.js'],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace')
        for line in proc.stdout:
            msg = line.rstrip()
            if not msg:
                continue
            audit_state["log"].append(msg)
            if len(audit_state["log"]) > 300:
                audit_state["log"] = audit_state["log"][-300:]
            if 'Progress:' in msg:
                audit_state["progress"] = "Audit " + msg.strip().replace('Progress:', 'progress:')
            _orig_print(msg, flush=True)
        code = proc.wait()
        if code != 0:
            raise RuntimeError(f"node audit.js exited with code {code}")
        audit_state["last_result"] = {"time": round(time.time() - t0, 1)}
        audit_state["progress"] = f"Done! Audit completed in {time.time() - t0:.0f}s"
        log_audit("Audit complete — output/kentvenues-audit-data.json updated")
    except Exception as e:
        audit_state["error"] = str(e)
        audit_state["progress"] = f"Error: {e}"
        log_audit(f"AUDIT ERROR: {e}")
    finally:
        audit_state["running"] = False

@app.route('/api/audit/run', methods=['POST'])
def api_audit_run():
    if audit_state["running"]:
        return jsonify({"error": "audit already running"}), 409
    if scrape_state["running"]:
        return jsonify({"error": "venue scrape is running — wait for it to finish"}), 409
    thread = threading.Thread(target=audit_worker, daemon=True)
    thread.start()
    return jsonify({"started": True})

@app.route('/api/audit/run/status')
def api_audit_run_status():
    return jsonify(audit_state)

def scrape_worker(locations, delay, limit):
    try:
        scrape_state["running"] = True
        scrape_state["progress"] = "Starting scrape..."
        scrape_state["error"] = None
        scrape_state["log"] = []
        log(f"Scraping locations: {', '.join(locations) if locations else 'all Kent'} limit={limit} delay={delay}")
        from venue_scraper.scraper import VenueScraper
        from venue_scraper.storage import VenueStorage
        from venue_scraper.sources import WeddingVenuesCo, WeddingVenuesCoUk
        from venue_scraper.geo import detect_town
        from venue_scraper.tags import infer_extra_tags
        from venue_scraper.clean import clean_venue
        from venue_scraper.enricher import Enricher

        scraper = VenueScraper(delay=delay)
        # Patch print to log (only messages from the scraper; use log() directly)
        import builtins
        orig_print = builtins.print
        def patched_print(*args, **kwargs):
            msg = ' '.join(str(a) for a in args)
            if msg.strip():
                scrape_state["log"].append(msg.strip())
                if len(scrape_state["log"]) > 100:
                    scrape_state["log"] = scrape_state["log"][-100:]
            return _orig_print(*args, **kwargs)
        builtins.print = patched_print

        loc_filter = [l.strip().replace(' ', '-') for l in locations] if locations else None
        t0 = time.time()
        venues = scraper.scrape_kent_venues(location_filter=loc_filter, max_pages=limit if limit else None)
        wv = WeddingVenuesCo(delay=delay, max_venues=limit if limit else None)
        wv2 = WeddingVenuesCoUk(delay=delay, max_venues=limit if limit else None)
        for src in (wv, wv2):
            venues += src.scrape(location_filter=loc_filter)
        builtins.print = orig_print
        log(f"Scraped {len(venues)} raw venues in {time.time()-t0:.1f}s, deduplicating...")

        seen=set()
        unique=[]
        for v in venues:
            key=(v.name.strip().lower(), (v.postcode or '').strip().lower())
            if key in seen: continue
            seen.add(key)
            unique.append(v)
        log(f"Unique venues: {len(unique)} — enriching from own websites...")
        enricher = Enricher(delay=max(0.25, delay), timeout=15)
        enricher.enrich_venues(unique)
        for v in unique:
            clean_venue(v)
            town = detect_town(v)
            if town:
                v.additional_info['detected_town']=town
            infer_extra_tags(v)
        log(f"Unique venues: {len(unique)}")
        storage = VenueStorage(output_dir=OUTPUT_DIR)
        storage.save_to_csv(unique, 'venues.csv')
        storage.save_to_json(unique, 'venues.json')
        scrape_state["last_result"] = {"total": len(unique), "time": round(time.time()-t0,1), "file": "venues.json"}
        scrape_state["progress"] = f"Done! {len(unique)} venues saved."
        log(f"Saved to output/venues.csv + venues.json")
    except Exception as e:
        import traceback
        scrape_state["error"] = str(e)
        log(f"ERROR: {e}")
        log(traceback.format_exc())
        scrape_state["progress"] = f"Error: {e}"
    finally:
        scrape_state["running"] = False

@app.route('/api/scrape', methods=['POST'])
def api_scrape():
    if scrape_state["running"]:
        return jsonify({"error": "scrape already running", "state": scrape_state}), 409
    if audit_state["running"]:
        return jsonify({"error": "KentVenues audit is running — wait for it to finish"}), 409
    data = request.get_json() or {}
    locations = data.get('locations', LOCATIONS)
    # allow empty = all
    if not locations:
        locations = LOCATIONS
    delay = float(data.get('delay', 0.8))
    limit = int(data.get('limit', 0))  # 0 = unlimited, else max pages per type
    thread = threading.Thread(target=scrape_worker, args=(locations, delay, limit), daemon=True)
    thread.start()
    return jsonify({"started": True, "locations": locations, "delay": delay, "limit": limit})

@app.route('/api/scrape/status')
def api_scrape_status():
    return jsonify(scrape_state)

@app.route('/api/files')
def api_files():
    files = []
    for p in sorted(glob.glob(os.path.join(OUTPUT_DIR, "*.*")), key=os.path.getmtime, reverse=True):
        try:
            files.append({"name": os.path.basename(p), "size": os.path.getsize(p), "mtime": datetime.fromtimestamp(os.path.getmtime(p)).isoformat()})
        except:
            pass
    return jsonify(files)

if __name__ == '__main__':
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("Kent Venue Scraper Web UI [PROD]")
    print("Open http://127.0.0.1:5000")
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)
