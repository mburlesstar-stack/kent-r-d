const https = require('https');
const http = require('http');
const { JSDOM } = require('jsdom');
const fs = require('fs');
const path = require('path');

const BASE = 'https://www.kentvenues.co.uk';
const CONCURRENCY = 8;
const DELAY_MS = 200;
const OUT_DIR = path.join(__dirname, 'output');

function fetch(url, base) {
  return new Promise((resolve, reject) => {
    let target;
    try { target = new URL(url, base); } catch { return reject(new Error('Invalid URL')); }
    const req = https.get(target, { timeout: 15000, headers: { 'User-Agent': 'Mozilla/5.0 (compatible; VenueAuditor/1.0)' } }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        res.resume();
        return fetch(res.headers.location, target.href).then(resolve).catch(reject);
      }
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => resolve(data));
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
  });
}

function parse(html) {
  try {
    // swallow jsdom CSS parse warnings (Webflow pages have stylesheets jsdom can't parse)
    const virtualConsole = new (require('jsdom').VirtualConsole)();
    return new JSDOM(html, { virtualConsole }).window.document;
  } catch { return null; }
}

function text(doc, sel) {
  const el = doc.querySelector(sel);
  return el ? el.textContent.trim() : '';
}

function issue(category, severity, text, improvement) {
  return { category, severity, text, improvement };
}

// Extract real data from a venue page, ignoring Webflow template boilerplate.
function extractData(doc) {
  // DESCRIPTION — strip the "claim this listing" CTA that pads auto-generated descriptions
  const rawDesc = text(doc, '.venue-listing-rich');
  const unclaimed = /want to claim this listing/i.test(rawDesc);
  const desc = rawDesc.replace(/want to claim this listing.*$/is, '').trim();

  // PHOTOS — unique gallery image URLs (template copies are duplicated on every page)
  const photoUrls = new Set(
    Array.from(doc.querySelectorAll('.lightbox-product-image'))
      .map(el => (el.getAttribute('style') || '').match(/url\(["']?([^"')]+)["']?\)/))
      .filter(m => m && m[1])
      .map(m => m[1])
  );
  const photoCount = photoUrls.size;

  // AMENITIES — unique .amen-text values (the 80 icon-boxes are identical template junk on every page)
  const amenities = [...new Set(
    Array.from(doc.querySelectorAll('.amen-text')).map(a => a.textContent.trim()).filter(Boolean)
  )];
  const amenityBlob = amenities.join(' ').toLowerCase();

  // ROOMS — real room card links only (section header contains a template filter dropdown)
  const roomLinks = [...new Set(
    Array.from(doc.querySelectorAll('.rooms-section a[href*="/rooms/"]')).map(a => a.getAttribute('href'))
  )];
  const roomsText = Array.from(doc.querySelectorAll('.rooms-section a[href*="/rooms/"]'))
    .map(a => a.textContent.replace(/\s+/g, ' '))
    .join(' ').toLowerCase();

  // CONTACT EMAIL — multi-source detection.
  // The enquiry form's hidden input is the primary signal (it's where enquiries route),
  // but it's invisible on the page and sometimes holds the directory team's fallback
  // instead of the venue's address. Cross-check every source:
  //   1. hidden inputs in the venue enquiry form(s) — all wraps, all inputs
  //   2. mailto: links on the page
  //   3. email addresses written in the description text
  // Addresses on the directory's own domains route to the site team, not the venue.
  const EMAIL_EXACT = /^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$/i;
  const SITE_FALLBACK_EMAIL = /@(kentvenues|maidstonedigital)\.co\.uk$/i;
  const emailCandidates = [];
  const formWraps = doc.querySelectorAll('.cta8-form-wrap.is-venue');
  const wrapsToScan = formWraps.length ? formWraps : doc.querySelectorAll('.cta8-form-wrap');
  for (const wrap of wrapsToScan) {
    for (const input of wrap.querySelectorAll('input[type=hidden]')) {
      const v = (input.value || '').trim();
      if (EMAIL_EXACT.test(v)) emailCandidates.push({ value: v.toLowerCase(), source: 'form' });
    }
  }
  for (const a of doc.querySelectorAll('a[href^="mailto:" i]')) {
    const v = decodeURIComponent((a.getAttribute('href') || '').replace(/^mailto:/i, '')).split('?')[0].trim();
    if (EMAIL_EXACT.test(v)) emailCandidates.push({ value: v.toLowerCase(), source: 'mailto link' });
  }
  for (const m of desc.matchAll(/[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}/gi)) {
    emailCandidates.push({ value: m[0].toLowerCase(), source: 'description text' });
  }
  const formEmails = emailCandidates.filter(c => c.source === 'form');
  const emailIsSiteFallback = formEmails.length > 0 && formEmails.every(c => SITE_FALLBACK_EMAIL.test(c.value));
  const fallbackEmail = (formEmails.find(c => SITE_FALLBACK_EMAIL.test(c.value)) || {}).value || '';
  const venueEmailHit = emailCandidates.find(c => !SITE_FALLBACK_EMAIL.test(c.value));
  const email = venueEmailHit ? venueEmailHit.value : '';
  const emailSource = venueEmailHit ? venueEmailHit.source : '';

  // VENUE WEBSITE — embedded as an iframe (exclude generic maps/embeds)
  const website = Array.from(doc.querySelectorAll('iframe'))
    .map(f => (f.getAttribute('src') || '').trim())
    .find(src => /^https?:\/\//.test(src) && !/google|maps|embedly|youtube|vimeo|cdn\.|gstatic/i.test(src)) || '';

  const hasPhone = doc.querySelectorAll('a[href^="tel:"]').length > 0
    || /(?:\+44|0\s?1\d{3,4}|\b0\d{3}\s?\d{3}\s?\d{4})\s?\d[\d\s]{6,}/.test(desc);

  // ADDRESS — the venue owns a structured address block at .intro-title .location
  // (the footer's .location elements are just the directory's town-location filter, so scope it).
  // Fall back to a postcode written in the description text.
  const POSTCODE = /\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b/i;
  const introAddr = ((el => el ? el.textContent.replace(/\s+/g, ' ').trim() : '')(
    doc.querySelector('.intro-title .location')
  ));
  const hasAddress = POSTCODE.test(introAddr) || POSTCODE.test(desc);

  // Keyword checks are scoped to venue-owned content ONLY (never nav/footer/forms)
  const contentBlob = (desc + ' ' + amenityBlob + ' ' + roomsText).toLowerCase();

  // REVIEWS — the .reviews section is hidden (w-condition-invisible) when no real reviews exist
  const reviewsSection = doc.querySelector('.reviews');
  const hasReviews = reviewsSection ? !reviewsSection.className.includes('w-condition-invisible') : false;

  return {
    desc, unclaimed, photoCount, amenities, amenityBlob, roomLinks, roomsText,
    email, emailSource, emailIsSiteFallback, fallbackEmail,
    website, hasPhone, hasAddress,
    contentBlob, hasReviews
  };
}

function auditVenue(venue, doc) {
  const issues = [];
  let score = 100;
  const d = extractData(doc);

  // ============ 1. POOR DESCRIPTION ============
  if (d.unclaimed) {
    issues.push(issue('description', 'critical',
      'Listing is unclaimed — the description is auto-generated boilerplate',
      'Claim the listing and replace the auto-generated text with a real description (200+ words) covering character, history, setting and unique selling points'));
    score -= 15;
  }
  if (!d.desc || d.desc.length < 20) {
    issues.push(issue('description', 'critical',
      'Missing or extremely short venue description',
      'Write a detailed description (200+ words) covering the venue\'s character, history, setting, and what makes it unique'));
    score -= 20;
  } else if (d.desc.length < 100) {
    issues.push(issue('description', 'warning',
      `Description is very short (${d.desc.length} characters)`,
      'Expand the description to at least 200 characters covering key details like venue style, setting, and ideal event types'));
    score -= 10;
  } else if (d.desc.length < 200) {
    issues.push(issue('description', 'warning',
      `Description could be more detailed (${d.desc.length} characters)`,
      'Consider adding more details about the venue\'s atmosphere, capacity ranges, and unique features'));
    score -= 5;
  }

  // ============ 2. MISSING CAPACITY ============
  const capacityPatterns = [
    /\b\d{1,4}\s*(?:guests?|delegates?|people|covers?|persons?)\b/i,
    /\b(?:seats?|seated|standing|capacity|up to|max(?:imum)?|theatre|cabaret|boardroom|classroom|reception)\D{0,20}\d{1,4}\b/i,
    /\b\d{1,4}\s*(?:seated|standing|theatre|cabaret|boardroom|classroom)\b/i
  ];
  const hasCapacity = capacityPatterns.some(p => p.test(d.contentBlob));
  if (!hasCapacity) {
    issues.push(issue('capacity', 'critical',
      'No capacity information anywhere on the listing',
      'Add clear capacity figures: seated capacity, standing/reception capacity, and cabaret/boardroom/theatre layouts for each space'));
    score -= 15;
  }

  // ============ 3. MISSING PHOTOGRAPHS ============
  if (d.photoCount === 0) {
    issues.push(issue('photos', 'critical',
      'No photographs on the listing',
      'Add a minimum of 5 high-quality photographs showing the venue exterior, main spaces, and set-up examples'));
    score -= 20;
  } else if (d.photoCount <= 2) {
    issues.push(issue('photos', 'warning',
      `Only ${d.photoCount} photo(s) on the listing`,
      'Add more photos — listings with 5+ images convert significantly better. Cover different spaces, angles, and event set-ups'));
    score -= 10;
  } else if (d.photoCount <= 4) {
    issues.push(issue('photos', 'suggestion',
      `Only ${d.photoCount} photos — could add more`,
      'Aim for 8-10 photos covering exterior, each main space, and example event set-ups'));
    score -= 5;
  }

  // ============ 4. MISSING FACILITIES ============
  if (d.amenities.length === 0) {
    issues.push(issue('facilities', 'critical',
      'No facilities or amenities listed',
      'Add a complete amenities list: WiFi, AV equipment, heating, air conditioning, kitchen access, etc.'));
    score -= 15;
  } else if (d.amenities.length <= 2) {
    issues.push(issue('facilities', 'warning',
      `Only ${d.amenities.length} facilities listed (${d.amenities.join(', ')})`,
      'Expand the amenities list to include everything guests would want to know — WiFi, AV, parking, catering options, accessibility features'));
    score -= 5;
  }

  // ============ 5. MISSING PARKING ============
  const hasParking = /parking|car\s?park/i.test(d.amenityBlob) || /parking|car\s?park/i.test(d.desc);
  if (!hasParking) {
    issues.push(issue('parking', 'warning',
      'No parking information on the listing',
      'Add parking details: number of spaces, on-site vs nearby, disabled bays, EV charging, and any charges'));
    score -= 8;
  }

  // ============ 6. MISSING CATERING ============
  const cateringRe = /cater|restaurant|\bbar\b|cocktail|buffet|banquet|kitchen|refreshment|food|drinks?|dining|licensed/i;
  const hasCatering = cateringRe.test(d.amenityBlob) || cateringRe.test(d.desc);
  if (!hasCatering) {
    issues.push(issue('catering', 'warning',
      'No catering or food/drink information on the listing',
      'Clarify catering options: in-house catering, approved caterers list, BYO alcohol policy, and dietary accommodations'));
    score -= 8;
  }

  // ============ 7. MISSING ACCOMMODATION ============
  const accomRe = /accommodat|bedrooms?|overnight|hotel|b\s?&\s?b|bed and breakfast|sleep|staying?\b/i;
  const hasAccommodation = accomRe.test(d.amenityBlob) || accomRe.test(d.desc);
  if (!hasAccommodation) {
    issues.push(issue('accommodation', 'info',
      'No accommodation details on the listing',
      'If on-site accommodation exists, add room count, types and pricing. If not, mention nearby hotel options for wedding parties'));
    score -= 4;
  }

  // ============ 8. MISSING ACCESSIBILITY ============
  const accessRe = /wheelchair|accessib|step.?free|disabled|hearing loop|assistance|lift\b|accessible/i;
  const hasAccessibility = accessRe.test(d.amenityBlob) || accessRe.test(d.desc);
  if (!hasAccessibility) {
    issues.push(issue('accessibility', 'warning',
      'No accessibility information on the listing',
      'Add accessibility details: wheelchair access, step-free routes, accessible toilets, hearing loops, and accessible parking bays'));
    score -= 8;
  }

  // ============ 9. MISSING ADDRESS ============
  if (!d.hasAddress) {
    issues.push(issue('address', 'warning',
      'No full postal address on the listing',
      'Add the venue\'s full address (street, town, county, postcode) so visitors can find and map the venue'));
    score -= 8;
  }

  // ============ 10. MISSING CONTACT INFORMATION ============
  if (!d.email) {
    issues.push(issue('contact', 'critical',
      d.emailIsSiteFallback
        ? `No contact email for the venue — the enquiry form routes to the KentVenues team (${d.fallbackEmail}) instead of the venue`
        : 'No contact email address behind the enquiry form',
      'Set the venue\'s enquiry email so the contact form reaches the venue directly'));
    score -= 15;
  } else {
    if (d.emailIsSiteFallback || d.emailSource !== 'form') {
      // a real venue email exists on the page, but not in the enquiry form
      issues.push(issue('contact', 'warning',
        d.emailIsSiteFallback
          ? `Enquiry form sends to the KentVenues team (${d.fallbackEmail}) — the venue's real email (${d.email}) only appears via a ${d.emailSource}`
          : `The enquiry form has no venue email set — the venue's email (${d.email}) only appears via a ${d.emailSource}, not in the form`,
        'Set the venue\'s own enquiry email in the form so submitted enquiries reach the venue directly'));
      score -= 5;
    }
    if (!d.website) {
      issues.push(issue('contact', 'suggestion',
        'No venue website link on the listing',
        'Embed or link the venue\'s own website so visitors can research further'));
      score -= 3;
    }
    if (!d.hasPhone) {
      issues.push(issue('contact', 'suggestion',
        'No phone number displayed',
        'Add a direct phone number for enquirers who prefer to call'));
      score -= 2;
    }
  }

  // ============ EXTRAS ============
  if (!d.hasReviews) {
    issues.push(issue('description', 'suggestion',
      'No guest reviews or testimonials displayed',
      'Collect and display client testimonials to build trust and credibility'));
    score -= 3;
  }

  if (d.roomLinks.length === 0 && /castle|hotel|manor|hall|estate|barn|golf|stadium|centre/i.test(venue.name)) {
    issues.push(issue('facilities', 'suggestion',
      'Large venue has no individual rooms/spaces listed',
      'Break the venue into bookable spaces with individual descriptions, capacities, and photos'));
    score -= 3;
  }

  score = Math.max(0, Math.min(100, score));

  return {
    ...venue,
    issues,
    score,
    audited: true,
    unclaimed: d.unclaimed,
    descriptionLength: d.desc.length,
    photoCount: d.photoCount,
    amenityCount: d.amenities.length,
    hasCapacity,
    hasParking,
    hasCatering,
    hasAccommodation,
    hasAccessibility,
    hasAddress: d.hasAddress,
    hasContact: !!d.email,
    hasEmail: !!d.email,
    emailValue: d.email || '',
    emailSource: d.emailSource || '',
    emailFallback: d.emailIsSiteFallback || false,
    hasPhone: d.hasPhone,
    hasWebsite: !!d.website,
    roomCount: d.roomLinks.length,
    reviewCount: d.hasReviews ? 1 : 0
  };
}

function getSeverityBadge(issues) {
  if (issues.some(i => i.severity === 'critical')) return 'Critical';
  if (issues.some(i => i.severity === 'warning')) return 'Warning';
  if (issues.length === 0) return 'Good';
  return 'Suggestions';
}

function escapeCSV(val) {
  const s = String(val);
  if (s.includes(',') || s.includes('"') || s.includes('\n')) {
    return '"' + s.replace(/"/g, '""') + '"';
  }
  return s;
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function main() {
  console.log('=== KentVenues.co.uk Listing Auditor ===\n');

  console.log('[1/3] Fetching sitemap...');
  const sitemapXml = await fetch(BASE + '/sitemap.xml');

  const dom = new JSDOM(sitemapXml, { contentType: 'text/xml' });
  const doc = dom.window.document;
  const urls = doc.querySelectorAll('url loc');
  const venueUrls = [];
  urls.forEach(loc => {
    const url = loc.textContent.trim();
    if (url.includes('/venues/') && !url.includes('/rooms/')) {
      const slug = url.split('/venues/')[1].replace(/\/$/, '');
      if (slug) venueUrls.push(slug);
    }
  });
  console.log(`  Found ${venueUrls.length} venue URLs\n`);

  console.log(`[2/3] Auditing venues (concurrency: ${CONCURRENCY})...`);
  const results = [];
  let completed = 0;

  for (let i = 0; i < venueUrls.length; i += CONCURRENCY) {
    const batch = venueUrls.slice(i, i + CONCURRENCY);
    const batchResults = await Promise.all(batch.map(async (slug) => {
      const url = `${BASE}/venues/${encodeURIComponent(slug)}`;
      try {
        const html = await fetch(url);
        const vdoc = parse(html);
        if (!vdoc) throw new Error('parse error');

        // Detect dead/removed listings: redirect to 404 or a non-venue page
        const isVenuePage = !!vdoc.querySelector('h1.venue-heading')
          || !!vdoc.documentElement.getAttribute('data-wf-item-slug');
        if (!isVenuePage) {
          const is404 = /page not found/i.test(vdoc.title || '');
          completed++;
          return {
            slug, name: slug.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase()), url,
            score: 0, audited: true, unclaimed: true,
            issues: [issue('contact', 'critical',
              is404 ? 'DEAD LISTING — URL redirects to a 404 page (venue appears removed from the site)'
                    : 'DEAD LISTING — URL redirects away to a generic page (venue appears removed from the site)',
              'Remove the dead URL from the sitemap, or restore/redirect the listing to the venue\'s current page')],
            descriptionLength: 0, photoCount: 0, amenityCount: 0,
            hasCapacity: false, hasParking: false, hasCatering: false,
            hasAccommodation: false, hasAccessibility: false, hasAddress: false, hasContact: false,
            hasEmail: false, emailValue: '', emailSource: '', emailFallback: false, hasPhone: false, hasWebsite: false,
            roomCount: 0, reviewCount: 0
          };
        }

        const h1 = text(vdoc, 'h1.venue-heading');
        const name = h1 || slug.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
        const venue = { slug, name, url };
        const audited = auditVenue(venue, vdoc);
        completed++;
        if (completed % 25 === 0 || completed === venueUrls.length) {
          console.log(`  Progress: ${completed}/${venueUrls.length}`);
        }
        return audited;
      } catch (e) {
        completed++;
        return {
          slug, name: slug.replace(/-/g, ' '), url,
          score: 0, audited: true, unclaimed: false,
          issues: [issue('contact', 'critical', `Could not load page: ${e.message}`, 'Ensure the venue page is accessible')],
          descriptionLength: 0, photoCount: 0, amenityCount: 0,
          hasCapacity: false, hasParking: false, hasCatering: false,
          hasAccommodation: false, hasAccessibility: false, hasContact: false,
          hasEmail: false, emailValue: '', emailSource: '', emailFallback: false, hasPhone: false, hasWebsite: false,
          roomCount: 0, reviewCount: 0
        };
      }
    }));
    results.push(...batchResults);
    if (i + CONCURRENCY < venueUrls.length) await sleep(DELAY_MS);
  }

  console.log('\n[3/3] Generating reports...\n');

  const critical = results.filter(v => v.issues.some(i => i.severity === 'critical')).length;
  const warnings = results.filter(v => !v.issues.some(i => i.severity === 'critical') && v.issues.some(i => i.severity === 'warning')).length;
  const good = results.filter(v => v.issues.length === 0).length;
  const avgScore = results.reduce((a, v) => a + v.score, 0) / results.length;

  console.log('--- SUMMARY ---');
  console.log(`  Total venues:        ${results.length}`);
  console.log(`  Critical issues:     ${critical}`);
  console.log(`  Warnings:            ${warnings}`);
  console.log(`  Good listings:       ${good}`);
  console.log(`  Average score:       ${avgScore.toFixed(0)}%`);
  console.log('');

  const categories = ['description', 'capacity', 'photos', 'facilities', 'parking', 'catering', 'accommodation', 'accessibility', 'address', 'contact'];
  console.log('--- ISSUE BREAKDOWN ---');
  for (const cat of categories) {
    const count = results.filter(v => v.issues.some(i => i.category === cat)).length;
    const pct = ((count / results.length) * 100).toFixed(0);
    const bar = '█'.repeat(Math.round(pct / 5)) + '░'.repeat(20 - Math.round(pct / 5));
    console.log(`  ${cat.padEnd(16)} ${bar} ${count} (${pct}%)`);
  }

  // Summary CSV
  const summaryHeaders = ['Venue Name', 'URL', 'Score', 'Severity', 'Unclaimed Listing', 'Description Length', 'Photo Count', 'Amenity Count', 'Has Capacity', 'Has Parking', 'Has Catering', 'Has Accommodation', 'Has Accessibility', 'Has Address', 'Has Email', 'Email Address', 'Email Source', 'Has Phone', 'Has Website', 'Room Count', 'Issue Count', 'Critical Issues', 'Warnings', 'Suggestions'];
  const summaryRows = results.map(v => [
    v.name, v.url, v.score, getSeverityBadge(v.issues),
    v.unclaimed ? 'Yes' : 'No',
    v.descriptionLength, v.photoCount, v.amenityCount,
    v.hasCapacity ? 'Yes' : 'No', v.hasParking ? 'Yes' : 'No',
    v.hasCatering ? 'Yes' : 'No', v.hasAccommodation ? 'Yes' : 'No',
    v.hasAccessibility ? 'Yes' : 'No',
    v.hasAddress ? 'Yes' : 'No',
    v.hasEmail ? 'Yes' : 'No', v.emailValue || '', v.emailSource || '',
    v.hasPhone ? 'Yes' : 'No', v.hasWebsite ? 'Yes' : 'No',
    v.roomCount, v.issues.length,
    v.issues.filter(i => i.severity === 'critical').length,
    v.issues.filter(i => i.severity === 'warning').length,
    v.issues.filter(i => i.severity === 'suggestion' || i.severity === 'info').length
  ]);
  const summaryCsv = [summaryHeaders.map(escapeCSV).join(','), ...summaryRows.map(r => r.map(escapeCSV).join(','))].join('\n');
  fs.writeFileSync(path.join(OUT_DIR, 'kentvenues-audit-summary.csv'), '\ufeff' + summaryCsv, 'utf8');
  console.log(`\n  Summary CSV: output/kentvenues-audit-summary.csv`);

  // Detailed issues CSV
  const issueHeaders = ['Venue Name', 'URL', 'Score', 'Issue Category', 'Severity', 'Issue Description', 'Recommended Improvement'];
  const issueRows = [];
  for (const v of results) {
    for (const i of v.issues) {
      issueRows.push([v.name, v.url, v.score, i.category, i.severity, i.text, i.improvement]);
    }
  }
  const issuesCsv = [issueHeaders.map(escapeCSV).join(','), ...issueRows.map(r => r.map(escapeCSV).join(','))].join('\n');
  fs.writeFileSync(path.join(OUT_DIR, 'kentvenues-issues-detailed.csv'), '\ufeff' + issuesCsv, 'utf8');
  console.log(`  Issues CSV:   output/kentvenues-issues-detailed.csv`);

  // JSON for the dashboard
  fs.writeFileSync(path.join(OUT_DIR, 'kentvenues-audit-data.json'),
    JSON.stringify({ results, meta: { total: results.length, critical, warnings, good, avgScore, categories, date: new Date().toISOString() } }, null, 2), 'utf8');
  console.log(`  JSON Data:    output/kentvenues-audit-data.json`);

  generateHTMLReport(results, critical, warnings, good, avgScore, categories);
  console.log(`  HTML Report:  kentvenues-audit-report.html`);

  console.log('\n--- TOP 15 WORST LISTINGS ---');
  const worst = [...results].sort((a, b) => a.score - b.score).slice(0, 15);
  for (const v of worst) {
    console.log(`  ${String(v.score).padStart(3)}%  ${v.name}`);
    for (const i of v.issues.filter(x => x.severity === 'critical')) {
      console.log(`         CRITICAL [${i.category}]: ${i.text}`);
    }
  }

  console.log('\n--- TOP 15 BEST LISTINGS ---');
  const best = [...results].sort((a, b) => b.score - a.score).slice(0, 15);
  for (const v of best) {
    console.log(`  ${String(v.score).padStart(3)}%  ${v.name}  (${v.issues.length} issues)`);
  }

  console.log('\nDone!');
}

function generateHTMLReport(results, critical, warnings, good, avgScore, categories) {
  const esc = (s) => String(s || '').replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
  const getScoreColor = (s) => s >= 80 ? '#4ade80' : s >= 60 ? '#facc15' : s >= 40 ? '#fb923c' : '#f87171';
  const getSeverityBadgeHTML = (issues) => {
    if (issues.some(i => i.severity === 'critical')) return '<span class="badge critical">Critical</span>';
    if (issues.some(i => i.severity === 'warning')) return '<span class="badge warning">Warning</span>';
    if (issues.length === 0) return '<span class="badge ok">Good</span>';
    return '<span class="badge info">Suggestions</span>';
  };

  const sorted = [...results].sort((a, b) => a.score - b.score);

  const rows = sorted.map(v => {
    const sc = v.score;
    const scColor = getScoreColor(sc);
    const issuesHtml = v.issues.map(i => `<li class="${i.severity}">[${i.category}] ${i.text}</li>`).join('');
    const improvementsHtml = v.issues.map(i => `<li class="${i.severity}">${i.improvement}</li>`).join('');
    return `<tr>
      <td class="venue-name"><a href="${v.url}" target="_blank">${v.name}</a></td>
      <td><div class="score-bar"><div class="score-fill" style="width:${sc}%;background:${scColor}"></div></div><strong style="color:${scColor}">${sc}%</strong></td>
      <td>${getSeverityBadgeHTML(v.issues)}</td>
      <td>${v.descriptionLength}</td>
      <td>${v.photoCount}</td>
      <td>${v.amenityCount}</td>
      <td>${v.hasEmail ? '✓ ' + esc(v.emailValue || '') + ' (' + esc(v.emailSource || '') + ')' : (v.emailFallback ? '✗ form→KentVenues team' : '✗')}</td>
      <td><ul class="issue-list">${issuesHtml || '<li class="ok">All checks passed</li>'}</ul></td>
      <td><ul class="issue-list">${improvementsHtml || '<li class="ok">No improvements needed</li>'}</ul></td>
    </tr>`;
  }).join('\n');

  const catBreakdown = categories.map(cat => {
    const count = results.filter(v => v.issues.some(i => i.category === cat)).length;
    const pct = ((count / results.length) * 100).toFixed(0);
    return `<div class="cat-bar"><div class="cat-label">${cat}</div><div class="cat-track"><div class="cat-fill" style="width:${pct}%"></div></div><div class="cat-val">${count} (${pct}%)</div></div>`;
  }).join('\n');

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>KentVenues.co.uk Audit Report</title>
<style>
  :root { --bg:#0f1117; --surface:#1a1d27; --surface2:#232733; --border:#2e3344; --text:#e2e4ea; --dim:#8b90a0; --accent:#6c8cff; --green:#4ade80; --yellow:#facc15; --red:#f87171; --orange:#fb923c; --purple:#a78bfa; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:'Segoe UI',system-ui,sans-serif; background:var(--bg); color:var(--text); }
  .header { background:var(--surface); border-bottom:1px solid var(--border); padding:20px 32px; }
  .header h1 { font-size:20px; } .header h1 span { color:var(--accent); }
  .container { max-width:1400px; margin:0 auto; padding:24px 32px; }
  .stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:24px; }
  .stat { background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:16px; }
  .stat .label { font-size:11px; text-transform:uppercase; letter-spacing:.5px; color:var(--dim); }
  .stat .value { font-size:28px; font-weight:700; }
  .stat .value.grn { color:var(--green); } .stat .value.ylw { color:var(--yellow); }
  .stat .value.red { color:var(--red); } .stat .value.acc { color:var(--accent); } .stat .value.pur { color:var(--purple); }
  .cats { background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:20px; margin-bottom:24px; }
  .cats h2 { font-size:15px; margin-bottom:14px; }
  .cat-bar { display:flex; align-items:center; gap:10px; margin-bottom:8px; }
  .cat-label { width:130px; font-size:12px; text-transform:capitalize; }
  .cat-track { flex:1; height:8px; background:var(--surface2); border-radius:4px; overflow:hidden; }
  .cat-fill { height:100%; background:var(--accent); border-radius:4px; }
  .cat-val { width:80px; font-size:12px; color:var(--dim); text-align:right; }
  table { width:100%; border-collapse:collapse; background:var(--surface); border:1px solid var(--border); border-radius:10px; overflow:hidden; }
  thead th { background:var(--surface2); text-align:left; padding:10px 12px; font-size:11px; text-transform:uppercase; letter-spacing:.5px; color:var(--dim); border-bottom:1px solid var(--border); }
  tbody td { padding:8px 12px; border-bottom:1px solid var(--border); font-size:13px; vertical-align:top; }
  tbody tr:hover { background:var(--surface2); }
  .venue-name { font-weight:600; } .venue-name a { color:var(--accent); text-decoration:none; } .venue-name a:hover { text-decoration:underline; }
  .badge { display:inline-block; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:500; }
  .badge.critical { background:rgba(248,113,113,.15); color:var(--red); }
  .badge.warning { background:rgba(250,204,21,.15); color:var(--yellow); }
  .badge.ok { background:rgba(74,222,128,.15); color:var(--green); }
  .badge.info { background:rgba(108,140,255,.15); color:var(--accent); }
  .score-bar { width:50px; height:5px; background:var(--surface2); border-radius:3px; overflow:hidden; display:inline-block; vertical-align:middle; margin-right:4px; }
  .score-fill { height:100%; border-radius:3px; }
  .issue-list { list-style:none; }
  .issue-list li { padding:1px 0; font-size:12px; display:flex; gap:5px; align-items:baseline; }
  .issue-list li::before { content:''; width:5px; height:5px; border-radius:50%; flex-shrink:0; margin-top:4px; }
  .issue-list li.critical::before { background:var(--red); }
  .issue-list li.warning::before { background:var(--yellow); }
  .issue-list li.suggestion::before, .issue-list li.info::before { background:var(--purple); }
  .issue-list li.ok { color:var(--green); } .issue-list li.ok::before { background:var(--green); }
  .table-wrap { overflow-x:auto; }
  #searchBar { background:var(--surface); border:1px solid var(--border); color:var(--text); padding:8px 14px; border-radius:8px; font-size:13px; width:300px; margin-bottom:16px; }
  @media(max-width:768px){ .container{padding:16px;} #searchBar{width:100%;} }
</style>
</head>
<body>
<div class="header"><h1>KentVenues.co.uk <span>Audit Report</span></h1><p style="color:var(--dim);font-size:12px;margin-top:4px">${results.length} venues audited</p></div>
<div class="container">
  <div class="stats">
    <div class="stat"><div class="label">Total Venues</div><div class="value acc">${results.length}</div></div>
    <div class="stat"><div class="label">Critical Issues</div><div class="value red">${critical}</div></div>
    <div class="stat"><div class="label">Warnings</div><div class="value ylw">${warnings}</div></div>
    <div class="stat"><div class="label">Good Listings</div><div class="value grn">${good}</div></div>
    <div class="stat"><div class="label">Average Score</div><div class="value pur">${avgScore.toFixed(0)}%</div></div>
  </div>
  <div class="cats"><h2>Issue Breakdown by Category</h2>${catBreakdown}</div>
  <input type="text" id="searchBar" placeholder="Search venues..." oninput="document.querySelectorAll('tbody tr').forEach(r=>{r.style.display=r.textContent.toLowerCase().includes(this.value.toLowerCase())?'':'none'})">
  <div class="table-wrap">
    <table>
      <thead><tr><th>Venue</th><th>Score</th><th>Severity</th><th>Desc</th><th>Photos</th><th>Amenities</th><th>Contact</th><th>Issues</th><th>Improvements</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>
</div>
</body></html>`;

  fs.writeFileSync(path.join(OUT_DIR, 'kentvenues-audit-report.html'), html, 'utf8');
}

if (require.main === module) {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  main().catch(e => { console.error('Fatal:', e); process.exit(1); });
}

module.exports = { fetch, parse, auditVenue, extractData, issue };
