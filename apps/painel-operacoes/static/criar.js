/* Criar site — interface ÚNICA (fusão de /obs/criacao + /obs/studio, 2026-08-05).
   As duas telas chamavam a MESMA API e mantinham duas linguagens visuais pro mesmo
   trabalho. Aqui a lógica das duas convive sem campo duplicado. */
const $ = i => document.getElementById(i);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let TIER = "", AUTOFILL = {}, LEAD = null, MOD = null, selEstilo = null, selReceita = null, tmr = 0;

function aba(n) {
  document.querySelectorAll(".aba").forEach(a => a.classList.toggle("on", a.dataset.p === n));
  document.querySelectorAll(".painel").forEach(p => p.classList.toggle("on", p.id === "p-" + n));
}
function toast(t) {
  const el = $("toast"); el.textContent = t; el.classList.add("on");
  setTimeout(() => el.classList.remove("on"), 2600);
}

/* ─────────── autofill por nome (só campo VAZIO; o que você digitou vence) ─────────── */
async function autofill() {
  const nome = $("nome").value.trim(); if (!nome) return;
  const cat = LEADCAT[nome];
  if (cat && !$("nicho").value) $("nicho").value = cat;   // fallback instantâneo
  let d; try { d = await (await fetch("/api/criacao/lead?nome=" + encodeURIComponent(nome))).json(); }
  catch (e) { return; }
  if (!d || !d.achou) { $("af").textContent = ""; return; }
  const posto = [], diverg = [];
  for (const [id, val] of [["nicho", d.nicho], ["whatsapp", d.whatsapp], ["publico", d.publico],
                           ["cidade", d.cidade], ["email", d.email], ["diferenciais", d.diferenciais]]) {
    if (!val || !$(id)) continue;
    const atual = $(id).value.trim();
    if (!atual) { $(id).value = val; posto.push(id); AUTOFILL[id] = val; }
    else if (atual !== String(val).trim()) diverg.push([id, val]);
  }
  TIER = d.tier || "";
  if (d.tier && $("tier")) { $("tier").value = d.tier; verEscopo(); }
  window.__DIVERG = diverg;
  $("af").innerHTML = posto.length
    ? `✅ autopreenchido de <b>${esc(d.fonte)}</b>${d.tier ? " · " + esc(d.tier) : ""}: ${posto.join(", ")}`
    : `ℹ️ lead achado em ${esc(d.fonte)}`;
  // O dado velho NÃO vence calado: quando o CRM diverge, oferece a troca campo a campo.
  if (diverg.length) {
    $("af").innerHTML += `<div style="margin-top:6px">⚠️ o CRM tem valor diferente em ${diverg.length} campo(s):
      ${diverg.map(([id, v]) => `<button type="button" class="btn sec" style="margin:3px 4px 0 0;font-size:.74rem;padding:4px 10px"
        onclick="usarDoCRM('${esc(id)}')">${esc(id)} → ${esc(String(v).slice(0, 30))}</button>`).join("")}</div>`;
  }
  carregarModelos();
}
function usarDoCRM(id) {
  const par = (window.__DIVERG || []).find(([k]) => k === id);
  if (!par) return;
  $(id).value = par[1]; AUTOFILL[id] = par[1];
  window.__DIVERG = (window.__DIVERG || []).filter(([k]) => k !== id);
  autofill();
}
/* Sugestão de leads no campo nome (datalist). Sem isto o JP digita o nome inteiro e
   erra a grafia — e aí o autofill não casa com o CRM. */
const LEADCAT = {};
async function carregarLeads() {
  try {
    const d = await (await fetch("/api/leads-alvo")).json();
    const visto = new Set();
    $("leads").innerHTML = (d.leads || []).filter(l => {
      if (visto.has(l.nome)) return false;
      visto.add(l.nome); LEADCAT[l.nome] = l.categoria; return true;
    }).map(l => `<option value="${esc(l.nome)}">`).join("");
  } catch (e) { }
}

$("nome").addEventListener("change", autofill);
$("nome").addEventListener("blur", autofill);
$("nicho").addEventListener("input", () => { clearTimeout(tmr); tmr = setTimeout(carregarModelos, 450); });

/* ─────────── entrada pelo card da Prospecção (?lead=) + ciclo fechado ─────────── */
async function carregarLeadDoCard() {
  const id = new URLSearchParams(location.search).get("lead");
  if (!id) return;
  let d; try { d = await (await fetch(`/api/studio/lead/${encodeURIComponent(id)}`)).json(); } catch (e) { return; }
  if (!d.achou) { $("af").textContent = "lead não encontrado no CRM"; return; }
  LEAD = d;
  const c = d.campos || {};
  for (const [k, v] of [["nome", c.nome], ["nicho", c.nicho], ["whatsapp", c.whatsapp],
                        ["publico", c.publico], ["cidade", c.cidade], ["diferenciais", c.diferenciais]])
    if (v && $(k) && !$(k).value.trim()) $(k).value = v;
  if (d.tier) { $("tier").value = d.tier; TIER = d.tier; verEscopo(); }
  if (d.ingerir_site && d.site_atual) $("b-site").value = d.site_atual;
  const extra = [];
  if (d.decisor) extra.push(`Decisor (QSA): ${d.decisor}`);
  if (d.cnpj) extra.push(`CNPJ: ${d.cnpj}`);
  if (d.achado) extra.push(`Achado da prospecção: ${d.achado}`);
  if (extra.length && !$("copy_livre").value.trim()) $("b-form").value = extra.join("\n");
  $("af").innerHTML = `✅ <b>lead #${d.prospect_id}</b> do CRM (campos marcados como <b>inferido</b>)`
    + (d.decisor ? ` · decisor <b>${esc(d.decisor)}</b>` : "")
    + (d.fala ? `<div class="hint" style="margin-top:5px"><b>FALE ISTO:</b> ${esc(d.fala)}</div>` : "");
  carregarModelos();
}

/* ─────────── escopo do tier ─────────── */
async function verEscopo() {
  const t = $("tier").value || TIER || "T1";
  try {
    const d = await (await fetch("/api/criacao/escopo?tier=" + encodeURIComponent(t))).json();
    $("escopo").innerHTML = `<b>${esc(d.tier)} executa ${(d.escopo || []).length} entregas:</b> ${(d.escopo || []).map(esc).join(" · ")}`;
  } catch (e) { }
}

/* ─────────── modelos: morfismo + estrutura, preview com o CSS REAL do motor ─────────── */
async function carregarModelos() {
  const nicho = $("nicho").value.trim();
  if (!nicho) { $("m-estilos").innerHTML = '<div class="vazio">preencha o nicho para ver os modelos</div>'; $("m-receitas").innerHTML = ""; return; }
  const q = new URLSearchParams({ nicho, tier: $("tier").value, nome: $("nome").value.trim() });
  try { MOD = await (await fetch("/api/studio/modelos?" + q)).json(); } catch (e) { return; }
  let tag = $("css-modelos");
  if (!tag) { tag = document.createElement("style"); tag.id = "css-modelos"; document.head.appendChild(tag); }
  tag.textContent = MOD.estilos.map(e => e.css_preview || "").join("\n");
  const a = MOD.auto, ac = Object.entries(a.acento || {})[0];
  $("m-auto").textContent = `— automático: ${a.estilo || "tema do motor"}${ac ? ` com ${ac[1]} em ${ac[0]}` : ""} · estrutura "${a.receita}" · segmento ${MOD.segmento || "genérico"}`;
  $("m-estilos").innerHTML = MOD.estilos.map(e => `
    <div class="mod${selEstilo === e.valor ? " on" : ""}" onclick="pickEstilo('${esc(e.valor)}')">
      ${e.auto ? '<span class="flag">AUTO</span>' : ""}
      <section class="amostra pv-${esc(e.valor)}"><div class="peca">${esc(e.rotulo)}</div></section>
      <div class="rot">${esc(e.rotulo)}</div><div class="dsc">${esc(e.desc || "")}</div></div>`).join("");
  $("m-receitas").innerHTML = MOD.receitas.map(r => `
    <div class="mod${selReceita === r.nome ? " on" : ""}" onclick="pickReceita('${esc(r.nome)}')">
      ${r.auto ? '<span class="flag">AUTO</span>' : ""}
      <div class="wf">${r.ordem.map((s, i) => `<i class="${i === 0 ? "hero" : (i % 3 === 1 ? "meio" : (i % 3 === 2 ? "curto" : ""))}" title="${esc(s)}"></i>`).join("")}</div>
      <div class="rot">${esc(r.nome)}</div><div class="ordem">${esc(r.ordem.join(" › "))}</div></div>`).join("");
  mostrarSel();
}
function pickEstilo(v) { selEstilo = selEstilo === v ? null : v; $("estilo").value = selEstilo ?? ""; carregarModelos(); }
function pickReceita(v) { selReceita = selReceita === v ? null : v; carregarModelos(); }
function mostrarSel() {
  $("g-sel").textContent = `pele: ${selEstilo === null ? "automático" : (selEstilo || "tema do motor")} · `
    + `estrutura: ${selReceita === null ? "automática" : selReceita}`
    + (selEstilo !== null || selReceita !== null ? " (escolha manual)" : "");
}

/* ─────────── GERAR (upload real + ciclo fechado com o card) ─────────── */
async function gerar() {
  const nome = $("nome").value.trim(), nicho = $("nicho").value.trim();
  if (!nome || !nicho) { $("res").innerHTML = '<div class="err">Nome e nicho são obrigatórios.</div>'; return; }
  const fd = new FormData();
  for (const k of ["nome", "nicho", "whatsapp", "publico", "cor", "copy_livre", "cidade", "email", "diferenciais"])
    fd.append(k, $(k) ? $(k).value : "");
  fd.append("tier", $("tier").value || TIER || "");
  if (selEstilo !== null) fd.append("estilo", selEstilo);
  if (selReceita !== null) fd.append("receita_nome", selReceita);
  fd.append("autofill", JSON.stringify(AUTOFILL));
  if (LEAD && LEAD.prospect_id) fd.append("lead_id", LEAD.prospect_id);
  if ($("foto").files[0]) fd.append("foto", $("foto").files[0]);
  if ($("video").files[0]) fd.append("video", $("video").files[0]);
  for (const f of ($("fotos").files || [])) fd.append("fotos", f);
  $("btn").disabled = true; $("btn").textContent = "⏳ gerando (copy + template + deploy)…";
  try {
    const d = await (await fetch("/api/criacao/gerar", { method: "POST", body: fd })).json();
    if (d.ok) {
      let volta = "";
      if (LEAD && LEAD.prospect_id) {
        try {
          const rr = await (await fetch(`/api/studio/lead/${LEAD.prospect_id}/demo`, {
            method: "POST", headers: { "content-type": "application/json" },
            body: JSON.stringify({ url: d.url }) })).json();
          volta = rr.ok ? `<br>🔗 link já está no card do lead #${LEAD.prospect_id}` : "";
        } catch (e) { }
      }
      $("res").innerHTML = `<div class="ok">✅ Publicado:
        <a href="${esc(d.url)}" target="_blank" rel="noopener">${esc(d.url)}</a><br>
        estrutura: <b>${esc(d.estrutura || "default")}</b> · pele: ${esc(d.estilo || "—")}
        · ${d.fotos || 0} foto(s) · ${d.segundos || "?"}s${volta}</div>`;
      carregarSites();
    } else {
      $("res").innerHTML = `<div class="err">Falhou: ${esc(d.erro || "erro")}
        <div class="hint" style="margin-top:6px">Seu formulário e os arquivos subidos foram
        PRESERVADOS — é só gerar de novo. Não recarregue a página.</div></div>`;
    }
  } catch (e) { $("res").innerHTML = `<div class="err">Erro de rede: ${esc(e.message)}</div>`; }
  $("btn").disabled = false; $("btn").textContent = "🚀 Gerar site";
}

/* ─────────── INGESTÃO ─────────── */
function proc(p) {
  const r = [];
  for (const [k, v] of Object.entries(p || {})) if (v) r.push(`<span class="p ${esc(v)}">${esc(k)}: ${esc(v)}</span>`);
  return r.length ? `<div class="proc">${r.join("")}</div>` : "";
}
async function ingerir() {
  const nome = $("nome").value.trim();
  if (!nome) { $("b-res").innerHTML = '<div class="err">Preencha o nome do negócio na aba Criar.</div>'; return; }
  $("b-res").innerHTML = '<div class="ok">consolidando… (buscando site atual, se houver)</div>';
  const corpo = { nome, site_url: $("b-site").value.trim(), formulario: $("b-form").value,
                  fotos: +$("b-fotos").value || 0, videos: +$("b-videos").value || 0, usar_crm: true };
  let d;
  try { d = await (await fetch("/api/criacao/ingerir", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(corpo) })).json(); }
  catch (e) { $("b-res").innerHTML = `<div class="err">erro de rede: ${esc(e.message)}</div>`; return; }
  const m = d.material || {};
  // o material consolidado alimenta a aba Criar — não se digita duas vezes
  for (const [k, v] of [["nicho", m.nicho], ["whatsapp", m.whatsapp], ["cidade", m.cidade],
                        ["email", m.email], ["publico", m.publico], ["diferenciais", m.diferenciais]])
    if (v && $(k) && !$(k).value.trim()) $(k).value = v;
  let v = {};
  try { v = await (await fetch("/api/criacao/validar-tier", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ...m, tier: $("tier").value, modo: "demo" }) })).json(); }
  catch (e) { v = { mensagem: "não deu pra validar o tier", faltas: [] }; }
  const fontes = (d.fontes || []).map(f => `${f.ok ? "✓" : "✗"} ${esc(f.tipo)}${f.erro ? " — " + esc(f.erro) : ""}`).join(" · ");
  $("b-res").innerHTML = `<div class="${v.ok ? "ok" : "err"}"><b>${esc(v.mensagem || "")}</b></div>
    ${(v.faltas || []).map(f => `<div class="falta">• <b>${esc(f.campo)}</b> (${esc(f.tier)}) — ${esc(f.porque)}</div>`).join("")}
    <div class="falta" style="margin-top:10px">${d.campos_reais}/${d.campos_total} campos do cliente · ${fontes}</div>
    ${proc(d.proveniencia)}
    <div class="falta" style="margin-top:8px">↳ os campos preenchidos foram copiados pra aba <b>Criar</b>.</div>`;
  carregarModelos();
}

/* ─────────── SITES GERADOS ─────────── */
function selo(s) {
  if (s.status === "no ar") return '<span class="selo">NO AR</span>';
  return `<span class="selo ruim">${esc(String(s.status).toUpperCase())}</span>`;
}
async function carregarSites() {
  let d; try { d = await (await fetch("/api/studio/galeria")).json(); }
  catch (e) { $("grade").innerHTML = `<div class="vazio">falhou: ${esc(e.message)}</div>`; return; }
  const S = d.sites || [];
  $("g-placar").innerHTML = `
    <div class="meta"><div class="t">SITES</div><div class="n">${d.total}</div><div class="d">${S.filter(x => x.status === "no ar").length} no ar</div></div>
    <div class="meta"><div class="t">ESTRUTURAS</div><div class="n">${d.estruturas_distintas}</div><div class="d">esqueletos diferentes</div></div>
    <div class="meta"><div class="t">DIVERSIDADE</div><div class="n">${d.diversidade}%</div><div class="d">${d.repetidos} repetindo esqueleto</div></div>`;
  $("grade").innerHTML = S.length ? S.map(s => `<div class="site">
    <div class="shot">${String(s.status).startsWith("órfão")
      ? '<div class="vazio2">registro sem arquivo</div>'
      : `<iframe src="${esc(s.url)}" loading="lazy" sandbox="allow-scripts" title="preview de ${esc(s.slug)}" tabindex="-1" aria-hidden="true"></iframe>`}${selo(s)}</div>
    <div class="corpo">
      <div class="nome">${esc(s.titulo || s.cliente || s.slug)}</div>
      <div class="secs">${(s.secoes || []).map(x => `<span class="sec">${esc(x)}</span>`).join("") || '<span class="sec">sem seções</span>'}</div>
      <div class="rodape">
        <span>${esc(s.segmento || "—")} · ${s.kb || 0}kb${s.iguais > 0 ? ` · <span class="aviso">mesmo esqueleto de ${s.iguais}</span>` : ""}</span>
        <span style="white-space:nowrap"><a href="${esc(s.url)}" target="_blank" rel="noopener">abrir ↗</a>
        <button class="btn perigo" style="padding:4px 10px;font-size:.74rem" onclick="apagar('${esc(s.slug)}')">🗑</button></span>
      </div></div></div>`).join("") : '<div class="vazio">nenhum site gerado ainda</div>';
}
async function apagar(slug) {
  if (!confirm(`Apagar o site "${slug}"?\n\nRemove a pasta em /var/www/sites e o registro.\nIRREVERSÍVEL.`)) return;
  const fd = new FormData(); fd.append("slug", slug);
  try {
    const d = await (await fetch("/api/criacao/apagar", { method: "POST", body: fd })).json();
    toast(d.ok ? `🗑 ${slug} apagado` : `falhou: ${d.erro || "erro"}`); carregarSites();
  } catch (e) { toast("erro de rede"); }
}
async function limparOrfaos() {
  if (!confirm("Remover do registro os sites que não existem mais em disco?")) return;
  const d = await (await fetch("/api/criacao/limpar-orfaos", { method: "POST" })).json();
  toast(`🧹 ${(d.removidos || []).length} órfão(s) removido(s)`); carregarSites();
}

/* ─────────── APRENDIZADO ─────────── */
async function carregarRefs() {
  let d; try { d = await (await fetch("/api/criacao/referencias")).json(); } catch (e) { return; }
  if ($("rseg").options.length === 0)
    $("rseg").innerHTML = (d.segmentos || []).map(s => `<option>${esc(s)}</option>`).join("");
  const R = d.referencias || [];
  $("rlista").innerHTML = R.length ? R.map(r => `<div class="ref">
      <span class="tag">${esc(r.tag || "—")}</span>
      <span class="hint">${esc(r.segmento || "?")}</span>
      <span class="hint" style="flex:1">${esc(((r.receita || {}).ordem || []).join(" › ") || "sem estrutura lida")}</span>
      ${r.aprovada ? '<span class="sec">no pool</span>' : `<button class="btn sec" style="padding:4px 10px;font-size:.74rem" onclick="aprovarRef(${r.id})">aprovar</button>`}
      <button class="btn perigo" style="padding:4px 10px;font-size:.74rem" onclick="apagarRef(${r.id})">🗑</button>
    </div>`).join("") : '<div class="vazio">nenhuma referência ainda</div>';
}
async function subirRef() {
  const fs = $("rimg").files;
  if (!fs || !fs.length) { $("rres").innerHTML = '<div class="err">escolha ao menos um print</div>'; return; }
  const fd = new FormData(); fd.append("segmento", $("rseg").value);
  if (fs.length > 1) { for (const f of fs) fd.append("imagens", f); }
  else { fd.append("imagem", fs[0]); fd.append("tag", $("rtag").value); }
  const url = fs.length > 1 ? "/api/criacao/referencias/lote" : "/api/criacao/referencia";
  $("rbtn").disabled = true; $("rbtn").textContent = `🧠 lendo ${fs.length}…`;
  try {
    const d = await (await fetch(url, { method: "POST", body: fd })).json();
    $("rres").innerHTML = `<div class="${d.ok ? "ok" : "err"}">${d.ok
      ? `✅ ${d.salvas !== undefined ? d.salvas + " referência(s) aprendida(s)" : "referência aprendida"}${d.falhas ? ` · ${d.falhas} falharam` : ""}`
      : esc(d.erro || "falhou")}</div>`;
    carregarRefs();
  } catch (e) { $("rres").innerHTML = `<div class="err">${esc(e.message)}</div>`; }
  $("rbtn").disabled = false; $("rbtn").textContent = "🧠 Ensinar estrutura";
}
async function scrapRef() {
  const url = $("rurl").value.trim(), gal = $("rgal").value;
  if (!url && !gal) { $("rres").innerHTML = '<div class="err">informe uma URL ou escolha uma galeria</div>'; return; }
  const fd = new FormData();
  fd.append("segmento", $("rseg").value); fd.append("url", url);
  fd.append("galeria", gal); fd.append("limite", $("rlim").value || "12");
  $("rsbtn").disabled = true; $("rsbtn").textContent = "🌐 lendo estrutura…";
  try {
    const d = await (await fetch("/api/criacao/referencias/scrap", { method: "POST", body: fd })).json();
    $("rres").innerHTML = `<div class="${d.ok ? "ok" : "err"}">${d.ok
      ? (d.salvas !== undefined ? `✅ ${d.salvas}/${d.tentadas} site(s) viraram referência` : `✅ estrutura: ${(d.ordem || []).join(" › ")}`)
      : esc(d.motivo || d.erro || "falhou")}</div>`;
    carregarRefs();
  } catch (e) { $("rres").innerHTML = `<div class="err">${esc(e.message)}</div>`; }
  $("rsbtn").disabled = false; $("rsbtn").textContent = "🌐 Aprender do site / galeria";
}
async function aprovarRef(id) {
  await fetch("/api/criacao/referencia/aprovar", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ id, aprovada: true }) });
  toast("✅ referência no pool"); carregarRefs();
}
async function apagarRef(id) {
  if (!confirm("Apagar esta referência?")) return;
  await fetch("/api/criacao/referencia/apagar", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ id }) });
  carregarRefs();
}

/* ─────────── OPERAÇÃO ─────────── */
const CANAIS = [["email", "✉️", "e-mail enviado"], ["email_fila", "📥", "e-mail na fila"],
                ["whatsapp", "💬", "WhatsApp"], ["demo", "🖥️", "demo no ar"],
                ["handoff", "🙋", "handoff"], ["fechado", "💰", "fechado"]];
async function carregarOperacao() {
  let d; try { d = await (await fetch("/api/studio/operacao")).json(); }
  catch (e) { $("o-placar").innerHTML = `<div class="vazio">falhou: ${esc(e.message)}</div>`; return; }
  $("o-placar").innerHTML = `
    <div class="meta"><div class="t">CONVERSÃO REAL</div><div class="n">${d.conversao}%</div>
      <div class="d">${d.clientes_pagantes} pagante(s) de ${d.base_conversao} com lead</div></div>
    <div class="meta"><div class="t">LIGADOS A LEAD</div><div class="n">${d.com_lead}</div><div class="d">${d.sem_lead} sem dono</div></div>
    <div class="meta"><div class="t">CUSTO / VENDA</div><div class="n">${d.custo_por_venda === null ? "—" : "R$ " + d.custo_por_venda}</div>
      <div class="d">${d.nao_instrumentado.length ? d.nao_instrumentado.length + " insumo(s) sem preço" : "tudo medido"}</div></div>
    <div class="meta"><div class="t">FUNIL</div><div class="n">${Object.values(d.funil || {}).reduce((a, b) => a + b, 0)}</div>
      <div class="d">${Object.entries(d.funil || {}).map(([k, v]) => k + " " + v).join(" · ") || "—"}</div></div>`;
  $("o-tiers").innerHTML = Object.entries(d.por_tier).map(([t, v]) => `
    <div class="mod" style="cursor:default;padding:11px 13px">
      <div class="rot" style="padding:0">${t} — ${v.vendidos_mes}/${v.meta}</div>
      <div style="height:6px;background:rgba(6,95,70,.12);border-radius:4px;margin:7px 0 5px">
        <div style="height:100%;width:${Math.min(100, v.pct)}%;background:var(--esmeralda);border-radius:4px"></div></div>
      <div class="dsc" style="padding:0">${v.sites} site(s) nesse tier</div></div>`).join("");
  $("o-tab").innerHTML = `<tr><th>SITE</th><th>CLIENTE</th><th>TIER</th><th>FUNIL</th><th>CANAIS</th></tr>`
    + (d.lista || []).map(x => `<tr>
      <td><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.slug)}</a></td>
      <td>${esc(x.empresa)}${x.prospect_id ? "" : ' <span class="aviso">sem lead</span>'}</td>
      <td>${esc(x.tier || "—")}</td><td>${esc(x.coluna || "—")}</td>
      <td>${CANAIS.filter(([k]) => x.canais[k]).map(([, i, t]) => `<span title="${t}">${i}</span>`).join(" ") || "—"}</td></tr>`).join("");
  $("o-custos").innerHTML = d.custos.map(c => `<div class="falta">• <b>${esc(c.rotulo)}</b>: ${c.volume} un ·
    ${c.custo === null ? '<span class="aviso">não instrumentado</span>' : "R$ " + c.custo}
    <span class="hint">— ${esc(c.nota)}</span></div>`).join("");
}

carregarLeads();
carregarLeadDoCard();
verEscopo();
carregarSites();
