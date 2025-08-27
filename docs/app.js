async function loadData(){
  const res = await fetch("data.json?_=" + Date.now());
  const data = await res.json();
  return data.items || [];
}

function fmtDate(s){
  if(!s) return "";
  if(/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
  return s;
}

function renderRows(items){
  const tbody = document.querySelector("#tbody");
  tbody.innerHTML = "";
  for(const it of items){
    const latest = it.latest ? `${it.latest.version || ""}` : "";
    const latestDate = it.latest ? `${fmtDate(it.latest.date) || ""}` : "";
    const prev = it.previous ? `${it.previous.version || ""}` : "";
    const prevDate = it.previous ? `${fmtDate(it.previous.date) || ""}` : "";
    const statusBadge = it.latest ? `<span class="badge badge-ok">OK</span>` : `<span class="badge badge-warn">Check</span>`;
    const err = it.error ? `<div class="badge badge-warn" title="${it.error}">Parse issue</div>` : "";
    const dl = it.download_page ? `<a href="${it.download_page}" target="_blank" rel="noopener">BIOS page</a>` : "";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${statusBadge} ${err}</td>
      <td>${it.vendor || ""}</td>
      <td>${it.board || ""}</td>
      <td>${latest}</td>
      <td>${latestDate}</td>
      <td>${prev}</td>
      <td>${prevDate}</td>
      <td>${dl}</td>`;
    tbody.appendChild(tr);
  }
}

function sortBy(items, key, dir){
  return [...items].sort((a,b)=>{
    const av = key(a) ?? "";
    const bv = key(b) ?? "";
    if(av < bv) return dir === "asc" ? -1 : 1;
    if(av > bv) return dir === "asc" ? 1 : -1;
    return 0;
  });
}

function attachSort(items){
  const headers = document.querySelectorAll("th[data-key]");
  let current = {key:null, dir:"asc"};
  headers.forEach(h=>{
    h.addEventListener("click", ()=>{
      const k = h.getAttribute("data-key");
      current.dir = (current.key === k && current.dir === "asc") ? "desc" : "asc";
      current.key = k;
      let sorted = items;
      if(k === "vendor") sorted = sortBy(items, it=> (it.vendor||"").toLowerCase(), current.dir);
      if(k === "board") sorted = sortBy(items, it=> (it.board||"").toLowerCase(), current.dir);
      if(k === "latestDate") sorted = sortBy(items, it=> it.latest?.date || "", current.dir);
      renderRows(sorted);
    });
  });
}

function attachSearch(baseItems){
  const input = document.querySelector("#search");
  const vendorSel = document.querySelector("#vendorSel");
  function apply(){
    const q = input.value.trim().toLowerCase();
    const v = vendorSel.value;
    let items = baseItems.filter(it=>{
      const hit = (it.board||"").toLowerCase().includes(q) || (it.vendor||"").toLowerCase().includes(q) ||
                  (it.latest?.version||"").toLowerCase().includes(q) || (it.previous?.version||"").toLowerCase().includes(q);
      const vmatch = v === "ALL" || (it.vendor === v);
      return hit && vmatch;
    });
    renderRows(items);
  }
  input.addEventListener("input", apply);
  vendorSel.addEventListener("change", apply);
  apply();
}

(async function(){
  const items = await loadData();
  renderRows(items);
  attachSort(items);
  attachSearch(items);
})();
