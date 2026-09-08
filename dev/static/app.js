let currentPage=1;
let totalPages=1;
let viewMode='grid';
let activeTab='venues';

// ---------------- Tab switching ----------------
function switchTab(tab){
  activeTab = tab;
  document.getElementById('tabVenues').classList.toggle('active', tab==='venues');
  document.getElementById('tabAudit').classList.toggle('active', tab==='audit');
  document.getElementById('venuesView').classList.toggle('hidden', tab!=='venues');
  document.getElementById('auditView').classList.toggle('hidden', tab!=='audit');
  if(tab==='audit' && !window.__auditLoaded){ fetchAudit(); window.__auditLoaded=true; }
  if(tab==='audit') checkAuditRunning();
  updateBadge();
}
function updateBadge(){
  const b = document.getElementById('totalBadge');
  if(activeTab==='audit'){
    if(window.__auditMeta && window.__auditMeta.exists!==false){
      b.textContent = `${window.__auditMeta.total||0} listings · avg ${Math.round(window.__auditMeta.avgScore||0)}%`;
    } else { b.textContent = 'no audit data'; }
  } else {
    fetch('/api/stats').then(r=>r.json()).then(s=>{ b.textContent=(s.total||0)+' venues'; });
  }
}

function getSelectedLocations(){
  return [...document.querySelectorAll('.loc-check:checked')].map(c=>c.value);
}
function getSelectedTypes(){
  return [...document.querySelectorAll('.type-check:checked')].map(c=>c.value);
}
function getSearch(){ return document.getElementById('searchInput').value.trim(); }
function getSort(){ return document.getElementById('sortSelect').value; }
function getPerPage(){ return parseInt(document.getElementById('perPage').value,10); }

async function fetchVenues(){
  const params = new URLSearchParams();
  const locs = getSelectedLocations();
  const types = getSelectedTypes();
  const search = getSearch();
  const sort = getSort();
  if(search) params.set('search', search);
  if(locs.length) params.set('locations', locs.join(','));
  if(types.length) params.set('types', types.join(','));
  params.set('page', currentPage);
  params.set('per_page', getPerPage());
  params.set('sort', sort);
  const res = await fetch('/api/venues?'+params.toString());
  const data = await res.json();
  renderVenues(data);
  renderStats(data.stats, data.source);
  renderPagination(data.page, data.total_pages, data.total);
  document.getElementById('totalBadge').textContent = data.total + ' venues';
  document.getElementById('sourceInfo').textContent = data.source ? 'Source: '+data.source : 'No data yet — run scraper';
  document.getElementById('resultInfo').textContent = `${data.total} venue${data.total!==1?'s':''} • page ${data.page}/${data.total_pages}`;
  totalPages = data.total_pages;
}

function renderVenues(data){
  const grid = document.getElementById('venueGrid');
  const tableWrap = document.getElementById('venueTableWrap');
  const tbody = document.getElementById('venueTableBody');
  const empty = document.getElementById('emptyState');
  const venues = data.venues;

  // expose current page's venues for index-based modal
  window.__venues = venues;

  if(!venues.length){
    grid.innerHTML='';
    tbody.innerHTML='';
    empty.classList.remove('hidden');
    if(viewMode==='grid') grid.classList.add('hidden'); else tableWrap.classList.add('hidden');
    return;
  }
  empty.classList.add('hidden');

  // Grid
  grid.innerHTML = venues.map((v,idx)=> cardHtml(v,idx)).join('');

  // Table
  tbody.innerHTML = venues.map((v,idx)=> `
    <tr>
      <td><strong>${esc(v.name||'')}</strong><br><span class="muted">${esc(v.location||'')}</span></td>
      <td>${esc(v.address||'')}<br><span class="pill">${esc(v.postcode||'')}</span></td>
      <td>${esc(v.venue_type||'')}</td>
      <td>${esc(v.capacity||'—')}</td>
      <td>${esc(v.postcode||'')}</td>
      <td>${esc(v.contact_phone||'')}<br><span class="muted">${esc(v.contact_name||'')}</span></td>
      <td class="actions-cell">${v.website?`<a href="${escAttr(v.website)}" target="_blank" rel="noopener">Website</a>`:'—'} <a href="#" onclick="openVenueModal(${idx}); return false;">Details</a></td>
    </tr>
  `).join('');

  // toggle view
  if(viewMode==='grid'){ grid.classList.remove('hidden'); tableWrap.classList.add('hidden'); }
  else { grid.classList.add('hidden'); tableWrap.classList.remove('hidden'); }
}

function cardHtml(v,idx){
  const facs = (v.facilities||'').split(',').map(s=>s.trim()).filter(Boolean).slice(0,4);
  const desc = (v.description||'').slice(0,130);
  const website = v.website ? `<a class="link-btn" href="${escAttr(v.website)}" target="_blank" rel="noopener">Website</a>` : '';
  const gmaps = v.postcode ? `<a class="link-btn" href="https://www.google.com/maps/search/${encodeURIComponent(v.address||v.postcode)}" target="_blank" rel="noopener">Map</a>` : '';
  return `<div class="card">
    <div class="card-top">
      <div class="card-type">${esc(v.venue_type||'Venue')}</div>
      <h3>${esc(v.name||'Unnamed')}</h3>
      <div class="card-meta"><span>📍 ${esc(v.location||'Kent')}</span> <span class="pill">${esc(v.postcode||'')}</span> <span class="pill">${esc(v.capacity||'')}</span></div>
      <div class="card-desc">${esc(desc)}${desc.length>=130?'…':''}</div>
      <div class="card-fac">${facs.map(f=>`<span>${esc(f)}</span>`).join('')}</div>
    </div>
    <div class="card-foot">
      <span class="muted" style="font-size:12px">${esc(v.contact_phone||'')} ${v.parking?'• '+esc(v.parking.slice(0,28)):''}</span>
      <span class="sep"></span>
      ${gmaps}
      ${website}
      <button class="link-btn primary" onclick="openVenueModal(${idx})">Details</button>
    </div>
  </div>`;
}

function renderStats(stats, source){
  const locEl = document.getElementById('statsLoc');
  const typeEl = document.getElementById('statsType');
  if(!stats) return;
  const locCounts = stats.loc_counts||{};
  const typeCounts = stats.type_counts||{};
  const locs = ['maidstone','canterbury','tunbridge-wells','ashford','sevenoaks','tonbridge','dartford','folkestone'];
  locEl.innerHTML = locs.map(l=>{
    const c = locCounts[l]||0;
    return `<div style="display:flex; justify-content:space-between; padding:4px 0; border-bottom:1px dashed #e2e8f0"><span>${l.replace('-',' ').replace(/\b\w/g,s=>s.toUpperCase())}</span><strong>${c}</strong></div>`;
  }).join('');
  typeEl.innerHTML = Object.entries(typeCounts).sort((a,b)=>b[1]-a[1]).map(([k,v])=>`<div style="display:flex; justify-content:space-between; padding:3px 0"><span>${esc(k)}</span><strong>${v}</strong></div>`).join('') || '<span class="muted">No data</span>';
}

function renderPagination(page, totalPages, total){
  const el = document.getElementById('pagination');
  if(totalPages<=1){ el.innerHTML=''; return; }
  let html='';
  html+=`<button class="page-btn" ${page<=1?'disabled':''} onclick="goPage(${page-1})">‹ Prev</button>`;
  const windowSize=5;
  let start=Math.max(1, page-2), end=Math.min(totalPages, start+windowSize-1);
  if(end-start<windowSize-1) start=Math.max(1,end-windowSize+1);
  for(let i=start;i<=end;i++){
    html+=`<button class="page-btn ${i===page?'active':''}" onclick="goPage(${i})">${i}</button>`;
  }
  if(end<totalPages) html+=`<span class="muted" style="align-self:center">… ${totalPages}</span>`;
  html+=`<button class="page-btn" ${page>=totalPages?'disabled':''} onclick="goPage(${page+1})">Next ›</button>`;
  el.innerHTML=html;
}
function goPage(p){ if(p<1||p>totalPages) return; currentPage=p; fetchVenues(); window.scrollTo({top:0, behavior:'smooth'}); }
function setView(v){
  viewMode=v;
  document.querySelectorAll('.view-btn').forEach(b=> b.classList.toggle('active', b.dataset.view===v));
  const data = {venues: []}; // re-render will fetch
  fetchVenues();
}
function toggleAll(kind, checked){
  document.querySelectorAll(kind==='location'?'.loc-check':'.type-check').forEach(c=> c.checked=checked);
  currentPage=1; fetchVenues();
}
function clearFilters(){
  document.getElementById('searchInput').value='';
  document.querySelectorAll('.loc-check, .type-check').forEach(c=> c.checked=true);
  document.getElementById('sortSelect').value='name';
  currentPage=1; fetchVenues();
}
function esc(s){ return (s||'').replace(/[&<>"']/g, m=> ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }
function escAttr(s){ return esc(s).replace(/"/g,'&quot;'); }

function openVenueModal(idx){
  const v = typeof idx === 'number' ? (window.__venues||[])[idx] : null;
  if(!v) return;
  const body = document.getElementById('modalBody');
  const facs = (v.facilities||'').split(',').map(s=>s.trim()).filter(Boolean);
  const socialLinks = ['facebook','instagram','twitter','linkedin','tiktok']
    .map(k=> v[k] ? `<a href="${escAttr(v[k])}" target="_blank" rel="noopener" class="social">${k.charAt(0).toUpperCase()+k.slice(1)}</a>` : '')
    .join('');
  body.innerHTML = `
    <h2>${esc(v.name)}</h2>
    <div class="muted">${esc(v.venue_type||'')} • ${esc(v.location||'')} • ${esc(v.postcode||'')}</div>
    <p style="margin:10px 0 0">${esc(v.address||'')}</p>
    <div class="detail-grid">
      <div class="detail-box"><h4>Capacity</h4><div>${esc(v.capacity||'—')}</div></div>
      <div class="detail-box"><h4>Parking</h4><div>${esc(v.parking||'—')}</div></div>
      <div class="detail-box"><h4>Contact</h4>
        <div>${v.contact_phone?`<a href="tel:${escAttr((v.contact_phone||'').replace(/[^0-9+]/g,''))}">${esc(v.contact_phone)}</a>`:'—'}<br>${esc(v.contact_name||'')}<br>${v.contact_email?`<a href="mailto:${escAttr(v.contact_email)}">${esc(v.contact_email)}</a>`:'—'}</div>
      </div>
      <div class="detail-box"><h4>Website</h4><div>${v.website?`<a href="${escAttr(v.website)}" target="_blank" rel="noopener">${esc(v.website)}</a>`:'—'}</div></div>
      <div class="detail-box"><h4>Catering</h4><div>${esc(v.catering||'—')}</div></div>
      <div class="detail-box"><h4>Accommodation</h4><div>${esc(v.accommodation||'—')}</div></div>
    </div>
    <div class="detail-box" style="margin:12px 0"><h4>Social</h4><div class="social-row">${socialLinks||'<span class="muted">None listed</span>'}</div></div>
    <div class="detail-box" style="margin:12px 0"><h4>Description</h4><div style="line-height:1.6">${esc(v.description||'No description')}</div></div>
    <div class="detail-box"><h4>Facilities</h4><div class="fac-list">${facs.length? facs.map(f=>`<span class="pill">${esc(f)}</span>`).join('') : '<span class="muted">No facilities listed</span>'}</div></div>
    <div style="margin-top:14px; display:flex; gap:8px; flex-wrap:wrap">
      ${v.website?`<a class="btn btn-primary" href="${escAttr(v.website)}" target="_blank" rel="noopener">Visit Website</a>`:''}
      ${v.postcode?`<a class="btn btn-outline" href="https://www.google.com/maps/search/${encodeURIComponent(v.address||v.postcode)}" target="_blank" rel="noopener">Open in Maps</a>`:''}
      ${v.source_url?`<a class="btn btn-ghost" href="${escAttr(v.source_url)}" target="_blank" rel="noopener">Source</a>`:''}
    </div>
  `;
  document.getElementById('modal').classList.remove('hidden');
}
function openModal(url, name){
  if(!url) return;
  window.open(url,'_blank');
}
function closeModal(){ document.getElementById('modal').classList.add('hidden'); }

function exportData(fmt){
  if(activeTab==='audit'){ exportAuditData(fmt); return; }
  const params = new URLSearchParams();
  const locs = getSelectedLocations();
  const types = getSelectedTypes();
  const search = getSearch();
  if(search) params.set('search', search);
  if(locs.length) params.set('locations', locs.join(','));
  if(types.length) params.set('types', types.join(','));
  window.location = '/api/export/'+fmt+'?'+params.toString();
}

// Scrape
async function startScrape(){
  const btn = document.getElementById('scrapeBtn');
  const status = document.getElementById('scrapeStatus');
  const logEl = document.getElementById('scrapeLog');
  const locs = getSelectedLocations();
  const delay = parseFloat(document.getElementById('scrapeDelay').value)||0.8;
  const limit = parseInt(document.getElementById('scrapeLimit').value,10)||0;
  btn.disabled=true; status.textContent='Starting…'; logEl.textContent='';
  try{
    const res = await fetch('/api/scrape', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({locations: locs, delay, limit})});
    const data = await res.json();
    if(!res.ok){ status.textContent = data.error||'Error'; btn.disabled=false; return; }
    status.textContent='Running…';
    pollScrape();
  }catch(e){ status.textContent='Error: '+e; btn.disabled=false; }
}
let pollTimer=null;
async function pollScrape(){
  const status = document.getElementById('scrapeStatus');
  const logEl = document.getElementById('scrapeLog');
  const btn = document.getElementById('scrapeBtn');
  try{
    const res = await fetch('/api/scrape/status');
    const s = await res.json();
    status.textContent = s.progress || (s.running?'Running…':'Done');
    logEl.textContent = (s.log||[]).join('\n');
    logEl.scrollTop = logEl.scrollHeight;
    if(s.running){
      pollTimer = setTimeout(pollScrape, 1200);
    } else {
      btn.disabled=false;
      if(s.last_result) status.textContent = `Done! ${s.last_result.total} venues`;
      if(s.error) status.textContent = 'Error: '+s.error;
      fetchVenues();
    }
  }catch(e){ status.textContent='Poll error'; btn.disabled=false; }
}

// Events
document.getElementById('searchInput').addEventListener('input', ()=>{ currentPage=1; fetchVenues(); });
document.getElementById('clearSearch').addEventListener('click', ()=>{ document.getElementById('searchInput').value=''; currentPage=1; fetchVenues(); });
document.getElementById('sortSelect').addEventListener('change', ()=>{ currentPage=1; fetchVenues(); });
document.getElementById('perPage').addEventListener('change', ()=>{ currentPage=1; fetchVenues(); });
document.querySelectorAll('.loc-check, .type-check').forEach(c=> c.addEventListener('change', ()=>{ currentPage=1; fetchVenues(); }));

// ---------------- KentVenues Audit ----------------
let auditPage=1;
let auditTotalPages=1;
let auditCatFilter='';
const auditDetailFilters={};   // field -> 'yes'|'no'|null
const AUDIT_DETAIL_FIELDS=[
  {key:'hasAddress', label:'Address', missing:'No address'},
  {key:'hasEmail',     label:'Email',     missing:'No email'},
  {key:'hasPhone',     label:'Phone',     missing:'No phone'},
  {key:'hasWebsite',   label:'Website',   missing:'No website'},
  {key:'hasCapacity',  label:'Capacity',  missing:'No capacity'},
  {key:'hasParking',   label:'Parking',   missing:'No parking'},
  {key:'hasCatering',  label:'Catering',  missing:'No catering'},
  {key:'hasAccommodation', label:'Accommodation', missing:'No accommodation'},
  {key:'hasAccessibility', label:'Accessibility', missing:'No accessibility'},
];

function scoreBadgeHtml(score){
  const cls = score>=70?'ok':(score>=40?'mid':'bad');
  return `<span class="score-badge ${cls}">${score}%</span>`;
}

async function fetchAudit(){
  const params = new URLSearchParams();
  const search = document.getElementById('auditSearchInput').value.trim();
  const sev = document.getElementById('auditSeverity').value;
  const un = document.getElementById('auditUnclaimed').checked;
  const sort = document.getElementById('auditSort').value;
  const pp = document.getElementById('auditPerPage').value;
  if(search) params.set('search', search);
  if(sev) params.set('severity', sev);
  if(auditCatFilter) params.set('category', auditCatFilter);
  if(un) params.set('unclaimed', '1');
  for(const [k,v] of Object.entries(auditDetailFilters)){
    if(v) params.set('detail_'+k, v);   // hasEmail=yes → detail_hasEmail=yes
  }
  params.set('sort', sort);
  params.set('page', auditPage);
  params.set('per_page', pp);
  const res = await fetch('/api/audit?'+params.toString());
  const data = await res.json();
  renderAudit(data);
  // first load: cache full results so detail pill counts stay stable while other filters change
  if(!window.__auditAllResults){
    try{
      const full = await fetch('/api/audit?per_page=500');
      const fd = await full.json();
      window.__auditAllResults = fd.results||[];
    }catch(e){}
  }
}

function renderAudit(data){
  const tbody = document.getElementById('auditTableBody');
  const empty = document.getElementById('auditEmptyState');
  const noData = document.getElementById('auditNoData');
  const rows = data.results||[];
  window.__auditResults = rows;
  window.__auditMeta = data.meta||{};

  // hero stat cards
  const st = data.stats||{};
  document.getElementById('aStatTotal').textContent = st.total ?? '—';
  document.getElementById('aStatAvg').textContent = st.avg_score!==undefined ? st.avg_score+'%' : '—';
  document.getElementById('aStatCritical').textContent = st.critical_venues ?? '—';
  document.getElementById('aStatWarn').textContent = st.warning_venues ?? '—';
  document.getElementById('aStatUnclaimed').textContent = st.unclaimed ?? '—';
  const m = data.meta||{};
  document.getElementById('aStatMeta').textContent = m.exists===false ? 'Not run yet' :
    (m.date ? 'Audited '+new Date(m.date).toLocaleString() : '');

  renderAuditCatBars(st);
  renderDetailPills(window.__auditAllResults||rows);
  updateBadge();

  if(m.exists===false || (!rows.length && st.total===0 && m.exists===false)){
    tbody.innerHTML='';
    document.getElementById('auditPagination').innerHTML='';
    empty.classList.add('hidden');
    noData.classList.remove('hidden');
    document.getElementById('auditResultInfo').textContent = 'No audit data';
    return;
  }
  noData.classList.add('hidden');

  if(!rows.length){
    tbody.innerHTML='';
    document.getElementById('auditPagination').innerHTML='';
    empty.classList.remove('hidden');
    document.getElementById('auditResultInfo').textContent = '0 listings match';
    return;
  }
  empty.classList.add('hidden');

  tbody.innerHTML = rows.map((v,idx)=>{
    const issues = v.issues||[];
    const c = issues.filter(i=>i.severity==='critical').length;
    const w = issues.filter(i=>i.severity==='warning').length;
    const s = issues.filter(i=>i.severity==='suggestion'||i.severity==='info').length;
    const flags = [
      v.unclaimed?'<span class="flag flag-unclaimed">Unclaimed</span>':'',
      (v.issues||[]).some(i=>/DEAD LISTING/i.test(i.text||''))?'<span class="flag flag-dead">Dead link</span>':''
    ].join('');
    return `<tr>
      <td>${scoreBadgeHtml(v.score)}</td>
      <td><strong>${esc(v.name||'')}</strong><br><a href="${escAttr(v.url)}" target="_blank" rel="noopener" class="small">${esc(v.slug||'')}</a></td>
      <td>${flags||'<span class="muted">—</span>'}</td>
      <td>${v.photoCount??0}</td>
      <td>${v.amenityCount??0}</td>
      <td>${v.descriptionLength||0} chars</td>
      <td>${c?`<span class="sev sev-critical">${c}C</span> `:''}${w?`<span class="sev sev-warning">${w}W</span> `:''}${s?`<span class="sev sev-suggestion">${s}S</span>`:''}${(!c&&!w&&!s)?'<span class="sev sev-ok">OK</span>':''}</td>
      <td><a href="#" onclick="openAuditModal(${idx}); return false;">Details</a></td>
    </tr>`;
  }).join('');

  document.getElementById('auditResultInfo').textContent =
    `${data.total} listing${data.total!==1?'s':''} • page ${data.page}/${data.total_pages}${auditCatFilter?` • category: ${auditCatFilter}`:''}`;
  auditTotalPages = data.total_pages||1;
  renderAuditPagination(data.page, data.total_pages, data.total);
}

function renderAuditCatBars(stats){
  const el = document.getElementById('auditCatBars');
  const cats = stats.category_counts||{};
  const total = stats.total||1;
  const label = c => ({description:'Description',capacity:'Capacity',photos:'Photos',facilities:'Facilities',parking:'Parking',catering:'Catering',accommodation:'Accommodation',accessibility:'Accessibility',address:'Address',contact:'Contact'}[c]||c);
  el.innerHTML = Object.entries(cats).sort((a,b)=>b[1].venues-a[1].venues).map(([cat,info])=>{
    const pct = Math.round((info.venues/total)*100);
    const active = auditCatFilter===cat?' active':'';
    return `<div class="cat-bar${active}" onclick="setAuditCategory('${cat}')" title="${info.venues} listings (${pct}%) — ${info.critical} critical">
      <div class="cat-bar-top"><span>${label(cat)}</span><strong>${info.venues}</strong></div>
      <div class="cat-bar-track"><div class="cat-bar-fill" style="width:${pct}%"></div></div>
    </div>`;
  }).join('') || '<span class="muted small">No data</span>';
}

function setAuditCategory(cat){
  auditCatFilter = auditCatFilter===cat ? '' : cat;
  auditPage=1; fetchAudit();
}

function toggleDetail(key){
  const cur = auditDetailFilters[key]||null;
  auditDetailFilters[key] = cur===null?'yes':(cur==='yes'?'no':null);
  if(!auditDetailFilters[key]) delete auditDetailFilters[key];
  auditPage=1; fetchAudit();
}
function clearAuditDetailFilters(){
  Object.keys(auditDetailFilters).forEach(k=> delete auditDetailFilters[k]);
  auditPage=1; fetchAudit();
}
function renderDetailPills(allResults){
  const el = document.getElementById('auditDetailPills');
  if(!el) return;
  el.innerHTML = AUDIT_DETAIL_FIELDS.map(f=>{
    const total = allResults.length;
    const withField = allResults.filter(v=> !!v[f.key]).length;
    const cur = auditDetailFilters[f.key]||null;
    const label = cur==='yes'?f.label : cur==='no'?f.missing : f.label;
    const badge = cur==='yes'?withField : cur==='no'?(total-withField) : '';
    const cls = cur==='yes'?'detail-pill active':cur==='no'?'detail-pill active missing':cur===null?'detail-pill':'detail-pill';
    return `<button class="${cls}" onclick="toggleDetail('${f.key}')">${esc(label)}${badge!==''?'<span class="detail-pill-badge">'+badge+'</span>':''}</button>`;
  }).join('');
}

function renderAuditPagination(page, totalPages, total){
  const el = document.getElementById('auditPagination');
  if(totalPages<=1){ el.innerHTML=''; return; }
  let html='';
  html+=`<button class="page-btn" ${page<=1?'disabled':''} onclick="goAuditPage(${page-1})">‹ Prev</button>`;
  const windowSize=5;
  let start=Math.max(1, page-2), end=Math.min(totalPages, start+windowSize-1);
  if(end-start<windowSize-1) start=Math.max(1,end-windowSize+1);
  for(let i=start;i<=end;i++){
    html+=`<button class="page-btn ${i===page?'active':''}" onclick="goAuditPage(${i})">${i}</button>`;
  }
  if(end<totalPages) html+=`<span class="muted" style="align-self:center">… ${totalPages}</span>`;
  html+=`<button class="page-btn" ${page>=totalPages?'disabled':''} onclick="goAuditPage(${page+1})">Next ›</button>`;
  el.innerHTML=html;
}
function goAuditPage(p){ if(p<1||p>auditTotalPages) return; auditPage=p; fetchAudit(); window.scrollTo({top:0, behavior:'smooth'}); }

function clearAuditFilters(){
  document.getElementById('auditSearchInput').value='';
  document.getElementById('auditSeverity').value='';
  document.getElementById('auditUnclaimed').checked=false;
  document.getElementById('auditSort').value='score';
  auditCatFilter=''; auditPage=1;
  Object.keys(auditDetailFilters).forEach(k=> delete auditDetailFilters[k]);
  fetchAudit();
}

function openAuditModal(idx){
  const v = (window.__auditResults||[])[idx];
  if(!v) return;
  const yn = b => b?'<span class="pill ok-pill">✓</span>':'<span class="pill no-pill">✗</span>';
  const emailPill = v.hasEmail
    ? `<span class="pill ok-pill" title="Found via ${esc(v.emailSource||'')}">✓ ${esc(v.emailValue||'')} <span class="muted">(${esc(v.emailSource||'')})</span></span>`
    : (v.emailFallback
        ? '<span class="pill no-pill" title="The form hidden field holds the KentVenues team address">✗ Email (form routes to KentVenues team)</span>'
        : '<span class="pill no-pill">✗ Email</span>');
  const issues = v.issues||[];
  const sevOrder = {critical:0, warning:1, suggestion:2, info:3};
  const sorted = [...issues].sort((a,b)=>(sevOrder[a.severity]??9)-(sevOrder[b.severity]??9));
  const sevChip = s => `<span class="sev sev-${s}">${s==='info'?'info':s}</span>`;
  const cats = [...new Set(issues.map(i=>i.category))];
  const body = document.getElementById('modalBody');
  body.innerHTML = `
    <h2>${esc(v.name||'')}</h2>
    <div class="muted" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      ${scoreBadgeHtml(v.score)}
      ${v.unclaimed?'<span class="flag flag-unclaimed">Unclaimed listing</span>':''}
      ${issues.some(i=>/DEAD LISTING/i.test(i.text||''))?'<span class="flag flag-dead">Dead link</span>':''}
      <a href="${escAttr(v.url)}" target="_blank" rel="noopener">View listing ↗</a>
    </div>
    <div class="detail-grid" style="margin-top:14px">
      <div class="detail-box"><h4>Photos</h4><div>${v.photoCount??0}</div></div>
      <div class="detail-box"><h4>Amenities</h4><div>${v.amenityCount??0}</div></div>
      <div class="detail-box"><h4>Description</h4><div>${v.descriptionLength||0} chars</div></div>
      <div class="detail-box"><h4>Rooms listed</h4><div>${v.roomCount??0}</div></div>
    </div>
    <div class="detail-box" style="margin:12px 0"><h4>Information present</h4>
      <div class="fac-list" style="gap:10px">
        ${emailPill}
        <span class="pill">Address ${yn(v.hasAddress)}</span>
        <span class="pill">Phone ${yn(v.hasPhone)}</span>
        <span class="pill">Website ${yn(v.hasWebsite)}</span>
        <span class="pill">Capacity ${yn(v.hasCapacity)}</span>
        <span class="pill">Parking ${yn(v.hasParking)}</span>
        <span class="pill">Catering ${yn(v.hasCatering)}</span>
        <span class="pill">Accommodation ${yn(v.hasAccommodation)}</span>
        <span class="pill">Accessibility ${yn(v.hasAccessibility)}</span>
      </div>
    </div>
    <div class="detail-box" style="margin:12px 0"><h4>Issues (${issues.length})</h4>
      ${sorted.length ? sorted.map(i=>`
        <div class="issue-block">
          <div class="issue-head">${sevChip(i.severity)} <span class="pill">${esc(i.category)}</span></div>
          <div class="issue-text">${esc(i.text)}</div>
          ${i.improvement?`<div class="issue-fix"><strong>Fix:</strong> ${esc(i.improvement)}</div>`:''}
        </div>`).join('') : '<span class="muted">No issues — model listing!</span>'}
    </div>
    <div style="margin-top:14px; display:flex; gap:8px; flex-wrap:wrap">
      <a class="btn btn-primary" href="${escAttr(v.url)}" target="_blank" rel="noopener">Open KentVenues Listing</a>
      ${cats.length?`<span class="muted" style="align-self:center">Categories: ${cats.join(', ')}</span>`:''}
    </div>
  `;
  document.getElementById('modal').classList.remove('hidden');
}

function exportAuditData(fmt){
  const params = new URLSearchParams();
  const search = document.getElementById('auditSearchInput').value.trim();
  const sev = document.getElementById('auditSeverity').value;
  const un = document.getElementById('auditUnclaimed').checked;
  if(search) params.set('search', search);
  if(sev) params.set('severity', sev);
  if(auditCatFilter) params.set('category', auditCatFilter);
  if(un) params.set('unclaimed', '1');
  for(const [k,v] of Object.entries(auditDetailFilters)){
    if(v) params.set('detail_'+k, v);
  }
  window.location = '/api/audit/export/'+fmt+'?'+params.toString();
}

// Audit run controls
function setAuditUi(running, text){
  ['auditBtn','auditRunBtn'].forEach(id=>{ const b=document.getElementById(id); if(b) b.disabled=running; });
  const s1=document.getElementById('auditStatus'); if(s1) s1.textContent=text;
  const s2=document.getElementById('auditViewStatus'); if(s2 && !/node audit\.js/.test(text)) s2.textContent=text;
}
async function startAudit(){
  setAuditUi(true, 'Starting…');
  const logEl = document.getElementById('auditLog');
  logEl.textContent='';
  try{
    const res = await fetch('/api/audit/run', {method:'POST'});
    const data = await res.json();
    if(!res.ok){ setAuditUi(false, data.error||'Error'); return; }
    setAuditUi(true, 'Running…');
    pollAudit();
  }catch(e){ setAuditUi(false, 'Error: '+e); }
}
let auditPollTimer=null;
async function pollAudit(){
  const logEl = document.getElementById('auditLog');
  try{
    const res = await fetch('/api/audit/run/status');
    const s = await res.json();
    setAuditUi(s.running, s.progress || (s.running?'Running…':'Done'));
    logEl.textContent = (s.log||[]).join('\n');
    logEl.scrollTop = logEl.scrollHeight;
    if(s.running){
      auditPollTimer = setTimeout(pollAudit, 1500);
    } else {
      if(s.error) setAuditUi(false, 'Error: '+s.error);
      else setAuditUi(false, s.last_result ? `Done in ${Math.round(s.last_result.time)}s` : 'Done');
      window.__auditLoaded=true;
      window.__auditAllResults=null;
      auditPage=1;
      if(activeTab==='audit') fetchAudit();
    }
  }catch(e){ setAuditUi(false, 'Poll error'); }
}
async function checkAuditRunning(){
  // reflect an already-running audit (e.g. started from the scrape panel) when opening the audit tab
  try{
    const s = await (await fetch('/api/audit/run/status')).json();
    if(s.running){ setAuditUi(true, s.progress||'Running…'); pollAudit(); }
  }catch(e){}
}

// Audit filter events
document.getElementById('auditSearchInput').addEventListener('input', ()=>{ auditPage=1; fetchAudit(); });
document.getElementById('auditClearSearch').addEventListener('click', ()=>{ document.getElementById('auditSearchInput').value=''; auditPage=1; fetchAudit(); });
document.getElementById('auditSeverity').addEventListener('change', ()=>{ auditPage=1; fetchAudit(); });
document.getElementById('auditUnclaimed').addEventListener('change', ()=>{ auditPage=1; fetchAudit(); });
document.getElementById('auditSort').addEventListener('change', ()=>{ auditPage=1; fetchAudit(); });
document.getElementById('auditPerPage').addEventListener('change', ()=>{ auditPage=1; fetchAudit(); });

// init
fetchVenues();
fetch('/api/stats').then(r=>r.json()).then(s=>{ document.getElementById('totalBadge').textContent = (s.total||0)+' venues'; });

document.addEventListener('keydown', e=>{ if(e.key==='Escape') closeModal(); });
