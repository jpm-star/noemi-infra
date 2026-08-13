<!-- modelo: qwen/qwen3.6-27b -->

<think>
Here's a thinking process:

1.  **Analyze User Input:**
    - **Context:** Brazilian website generator (JPOS) targeting local businesses in inland São Paulo.
    - **Tiers:** T1 (Landing, R$500, no monthly), T2 (Multi-page+SEO, R$1000 + R$397/mo), T3 (AI booking, R$1500 + R$697/mo), T4 (Ops dashboard, R$2500 + R$1297/mo).
    - **Clients:** Local businesses (clinics, gyms, law firms, salons, real estate, restaurants, small e-commerce).
    - **Tech:** Static HTML, no framework, section-by-section styling. T1/T2 sell on SPEED (Core Web Vitals), so lightweight.
    - **Current Vocabulary:** 127 niches, 92 section structures, 80 principles.
    - **Task:** Identify ANTI-PATTERNS and TRAPS that this vocabulary *misses* – things local business sites do that *destroy conversion*, which an automated generator would repeat blindly. For each, state what the generator should do instead. Avoid generic best practices. Focus on specific, conversion-destroying pitfalls relevant to this context.

2.  **Deconstruct the Problem:**
    - I need to find gaps in the current vocabulary (niches, sections, principles) that lead to bad conversion outcomes for local businesses.
    - The generator is automated, so it might default to trendy, complex, or generic patterns that backfire for local, conversion-focused sites.
    - I must avoid generic advice like "make it fast" or "use good colors" since those are already covered (Core Web Vitals, contrast, mobile-first, etc.).
    - I need to focus on *anti-patterns* (what not to do) and *traps* (intuitive but wrong choices) that the vocabulary doesn't explicitly prevent.
    - For each, provide a concrete alternative action for the generator.

3.  **Brainstorming Anti-Patterns & Traps (Local Business Context + Automation):**
    *Let's think about what local business sites typically get wrong, especially when auto-generated:*
    - **Overcomplicated Navigation/Menu:** Too many links, dropdowns, hiding the phone number. Generator might auto-generate a mega menu from CMS categories.
    - **Generic Hero Imagery:** Stock photos that don't match the local context/business. Generator might pick from a generic library.
    - **Multiple CTAs/Conflicting Goals:** "Call us", "WhatsApp", "Book now", "Get a quote", "Follow Instagram" all fighting for attention. Generator might stack them.
    - **Hidden/Inaccessible Contact Info:** Burying phone/WhatsApp in footer or behind a "Contact" page. Generator might follow standard template layouts.
    - **Over-engineered Interactions:** Carousels, sliders, parallax, heavy animations. Generator might default to trendy effects that hurt speed/conversion.
    - **Pricing Misalignment:** Showing prices that are outdated, missing local taxes, or using national averages. Generator might use placeholder numbers.
    - **SEO/Content Mismatch:** Writing generic content that doesn't match local search intent (e.g., "dentista em São Paulo" when client is in "Bauru"). Generator might ignore geo-specificity.
    - **Form Fatigue:** Long contact forms before establishing trust. Generator might auto-insert a 10-field form in the hero.
    - **Trust Gap:** Missing local proof (Google Maps embed that's slow, fake testimonials, unverified badges). Generator might use stock testimonials or heavy map embeds.
    - **Mobile UX Traps:** Covering content with sticky elements, non-tappable links, pop-ups that break flow. Generator might add aggressive lead magnets.
    - **Language/Tone Mismatch:** Corporate jargon instead of local, conversational tone. Generator might use formal AI text.
    - **Service Overload:** Listing 50 services when 3-5 drive 80% of revenue. Generator might dump all CRM categories into a grid.
    - **Legal/Compliance Blind Spots:** Missing LGPD consent for WhatsApp/forms, missing professional council numbers (OAB, CRM, etc.). Generator might ignore regional legal requirements.
    - **Speed vs. Feature Conflict:** Adding live chat, AI, or heavy galleries to T1/T2. Generator might not tier features properly.
    - **Conversion Leakage:** No click-to-call prefill, no WhatsApp message template, no clear next step after scroll. Generator might treat all CTAs equally.

4.  **Filter & Structure (Align with Prompt Requirements):**
    Need to pick the most critical, specific anti-patterns/traps that the *current vocabulary explicitly misses* and that an *automated generator would repeat*. For each:
    - Name the anti-pattern/trap
    - Explain why it destroys conversion for local businesses
    - What the generator *currently lacks* (gap in vocab)
    - What it *should do instead* (concrete, actionable fix)

    Let's refine 6-8 high-impact ones:

    **1. O "Menu-Rodapé" de Contato (Hidden Contact Friction)**
    - *Anti-pattern:* Burying phone/WhatsApp in footer or "Contato" page. Standard templates do this for "clean design".
    - *Why it destroys conversion:* Local buyers on mobile need one-tap contact. Every scroll/lick adds drop-off.
    - *Gap:* Vocab has "Header fixo", "Rodapé completo", but no rule forcing contact prominence above fold.
    - *Fix:* Generator must enforce "Contact-First Header" (tel: + WhatsApp floating) as non-negotiable for T1/T2. Hide decorative nav, prioritize utility.

    **2. A Ilusão do Carrossel Hero (Slideshow Cognitive Load)**
    - *Anti-pattern:* Auto-adding hero sliders/carousels. "Modern" but ignored by users, hurts LCP, dilutes message.
    - *Why it destroys conversion:* Users don't swipe. First slide gets 70% attention, rest is wasted. Breaks Core Web Vitals.
    - *Gap:* Vocab has carousel sections for testimonials, but no explicit ban on hero sliders.
    - *Fix:* Generator must disable hero carousels entirely. Force single static hero with one CTA. If multiple messages exist, use A/B or geo-variant static pages, not JS sliders.

    **3. O Efeito "Cardápio de Serviços" (Service Dump)**
    - *Anti-pattern:* Listing every possible service (10-20 items) in a grid. Generator scrapes CRM/category list.
    - *Why it destroys conversion:* Paradox of choice + cognitive overload. Local clients buy 1-3 core services. Grid looks like a catalog, not a conversion funnel.
    - *Gap:* Vocab has "Serviços em grid 2x2", "accordion", but no rule to filter/prioritize by conversion weight.
    - *Fix:* Generator must auto-collapse to top 3 services (based on niche template or client input). Others go to "Ver todos" (secondary CTA) or multi-page T2. Enforce "3 max above the fold".

    **4. O Mapa Lento do Google (Heavy Embed Penalty)**
    - *Anti-pattern:* Auto-embedding Google Maps in "Como chegar". Loads JS/API, kills performance, often shows wrong pin or stale info.
    - *Why it destroys conversion:* T1/T2 sell on speed. Map embeds add 2-5s load, block render, hurt LCP. Locals just need address + Waze link.
    - *Gap:* Vocab has "Abrir no Waze / Maps", "Mapa + horários", but no performance guardrail against heavy embeds.
    - *Fix:* Generator must replace live maps with static image + "Abrir no Waze/Google Maps" button + address text. Lazy-load only if T3/T4 explicitly requests it, with placeholder skeleton.

    **5. O Formulário de Confiança Zero (Premature Form Funnel)**
    - *Anti-pattern:* Auto-inserting 5+ field forms in hero or above fold before trust is established. "Pedir orçamento" with name, email, phone, service, message.
    - *Why it destroys conversion:* High friction, low trust, privacy concerns (LGPD). Local buyers prefer WhatsApp/call first.
    - *Gap:* Vocab has "Hero + formulário embutido", but no rule linking form fields to trust progression or niche behavior.
    - *Fix:* Generator must enforce "WhatsApp-first" for T1/T2. If forms exist, max 2 fields (nome + telefone) + explicit LGPD checkbox + trust microcopy ("Respondemos em 15min"). Push to mid-page after social proof.

    **6. A Prova Social Genérica (Stock Testimonial Trap)**
    - *Anti-pattern:* Auto-filling testimonials with generic names, stock photos, or fake 5-star quotes. Generator uses placeholder AI text.
    - *Why it destroys conversion:* Local clients verify via Google/WhatsApp. Fake/generic proof kills trust instantly. "Maria S." with no context = scam signal.
    - *Gap:* Vocab has "Avaliações do Google", "Print de elogio no WhatsApp", but no validation rule against AI/stock generation.
    - *Fix:* Generator must block AI-generated testimonials. Require client-uploaded WhatsApp screenshots or verified Google API pulls. If missing, replace with "Já atendemos +X clientes em [Cidade/Região]" + case metric, not fake quotes.

    **7. O CTA Concorrente (Multiple Call-to-Action War)**
    - *Anti-pattern:* "Ligar", "WhatsApp", "Agendar", "Baixar cardápio", "Seguir Instagram" all visible simultaneously. Generator stacks available CTA blocks.
    - *Why it destroys conversion:* Paradox of choice, dilutes primary goal. Local mobile users click randomly or bounce.
    - *Gap:* Vocab has "CTA único por tela", but no enforcement mechanism or fallback hierarchy.
    - *Fix:* Generator must enforce strict CTA hierarchy per tier/niche. Primary CTA = 1 per screen (WhatsApp/Call). Secondary = hidden behind scroll or secondary color. Auto-disable non-conversion CTAs (Instagram, newsletter) on T1/T2.

    **8. O Microcopy Corporativo em Lugar de Regional (Tone Mismatch)**
    - *Anti-pattern:* Formal, national-brand copy ("Soluções inovadoras para seu negócio", "Excelência em cada detalhe"). Generator uses default AI prompts.
    - *Why it destroys conversion:* Inland SP locals respond to direct, regional, practical language. Corporate tone feels distant/untrustworthy.
    - *Gap:* Vocab has "micro-copy regionalista", but no template constraints or regional lexicon enforcement.
    - *Fix:* Generator must inject geo-specific templates (e.g., "Atendemos Bauru e região", "Orçamento sem compromisso", "Atendimento rápido"). Block corporate buzzwords. Use conversational, action-oriented phrasing validated for interior SP.

5.  **Check Against Requirements:**
    - ✅ Points out anti-patterns & traps
    - ✅ Things local business sites do that destroy conversion
    - ✅ What an automated generator would repeat blindly
    - ✅ For each: what generator should do instead
    - ✅ Avoids generic best practices (focuses on specific, contextual, automation-prone failures)
    - ✅ Aligns with T1/T2 speed focus, local SP context, static HTML, current vocab gaps

    Let's refine the output to be precise, structured, and directly actionable for the generator's logic. I'll format it clearly, ensuring each point has: Nome, Por que destrói conversão, Falha no vocabulário atual, O que o gerador deve fazer (regra automática).

    I'll also add a meta-note about how these integrate into the generator's rule engine (since it's automated).

    Structure per item:
    **1. [Nome do Antipadrão/Armadilha]**
    - *O que acontece:* ...
    - *Por que destrói conversão:* ...
    - *Omissão no vocabulário:* ...
    - *Regra para o gerador:* ...

    I'll ensure tone is technical, conversion-focused, and specific to the Brazilian local business context + static HTML generator constraints.

    Self-Correction/Verification during thought:
    - Are these truly missing from the vocab? Yes. The vocab lists components/principles but lacks *enforcement rules*, *priority constraints*, and *anti-pattern guards*.
    - Are they specific to local business + automation? Yes. Each addresses a common auto-generator blind spot that directly hurts local conversion.
    - Do they avoid generic advice? Yes. No "use good UX" or "optimize images". All are structural/logic rules for the generator.
    - T1/T2 speed focus addressed? Yes (maps, carousels, forms, CTAs directly impact CWV and conversion).
    - Regional context? Yes (tone, service dump, proof sources).

    Ready. Output matches the refined structure.✅
</think>

Aqui estão 8 antipadrões e armadilhas que geradores automáticos repetem por inércia de template, e que o seu vocabulário atual **não bloqueia explicitamente**. Para cada um, há a regra concreta que o motor JPOS deve injetar na lógica de composição.

---

### 1. O Efeito “Cardápio de Serviços” (Service Dump)
- **O que acontece:** O gerador varre o CRM ou categoria do nicho e renderiza 10 a 20 serviços em grid ou accordion na home.
- **Por que destrói conversão:** Paradoxo da escolha + sobrecarga cognitiva. Negócio local converte por 1 a 3 serviços-chave. O grid vira catálogo de e-commerce, não funil de ação.
- **Omissão no vocabulário:** Você tem `Serviços em grid 2x2`, `accordion`, `mais pedidos`, mas não há regra de **filtragem por peso de conversão** ou limite estrutural.
- **Regra para o gerador:** Forçar `max 3 serviços acima da dobra`. Demais vão para `CTA secundário: Ver todos os serviços` (âncora ou página separada). Se o cliente não informar prioridade, o motor escolhe os 3 com maior margem/volume padrão do nicho.

### 2. O Mapa Lento do Google (Heavy Embed Penalty)
- **O que acontece:** Auto-injeção de `<iframe>` do Google Maps na seção “Como chegar”.
- **Por que destrói conversão:** Em T1/T2 (vendidos por velocidade), o embed bloqueia render, puxa JS externo, infla LCP e often mostra pin desatualizado ou bairro errado. O usuário local só precisa de endereço + link direto.
- **Omissão no vocabulário:** `Abrir no Waze / Maps` e `Mapa + horários` estão listados, mas sem **guardrail de performance**.
- **Regra para o gerador:** Substituir iframe por `imagem estática + texto do endereço + botão "Abrir no Waze/Google Maps"`. Renderizar iframe apenas se T3/T4 solicitar explicitamente + `loading="lazy"` + placeholder skeleton + `width/height` explícitos paraCLS.

### 3. O Carrossel Hero (Slideshow Cognitive Load)
- **O que acontece:** Gerador insere slider de 3-5 slides na hero por “padrão moderno”.
- **Por que destrói conversão:** Usuários não deslizam. O primeiro slide consome ~70% da atenção; o resto é custo de render + JS + CLS. Destrói Core Web Vitals e dispersa a mensagem principal.
- **Omissão no vocabulário:** Você tem carrosséis para depoimentos, mas **nenhuma proibição explícita para hero**.
- **Regra para o gerador:** Desabilitar hero sliders por padrão. Forçar `hero estático único + 1 CTA`. Se o cliente quiser múltiplas mensagens, gerar variações estáticas (A/B ou por segmento) ou usar `tab sem JS` com priorização clara. Zero animação de slide na dobra.

### 4. O Formulário de Confiança Zero (Premature Form Funnel)
- **O que acontece:** Gerador coloca formulário de 5+ campos (nome, email, telefone, serviço, mensagem) na hero ou acima da dobra.
- **Por que destrói conversão:** Fricção alta + desconfiança LGPD + preferência local por contato direto. Taxa de abandono >80% em mobile interiorano.
- **Omissão no vocabulário:** `Hero + formulário embutido` existe, mas sem **regra de progressão de confiança** ou limite de campos por tier.
- **Regra para o gerador:** Em T1/T2, bloquear formulário na hero. Se formulário existir: `max 2 campos (nome + telefone)` + checkbox LGPD explícito + microcopy de resposta (`“Respondemos em até 15 min”`). Posicionar abaixo da prova social. Priorizar `WhatsApp-first com mensagem pré-preenchida`.

### 5. O CTA Concorrente (Multiple Call-to-Action War)
- **O que acontece:** Gerador renderiza simultaneamente: “Ligar”, “WhatsApp”, “Agendar”, “Baixar cardápio”, “Seguir Instagram”, “Fale conosco”.
- **Por que destrói conversão:** Diluição de intenção. Mobile local clica por impulso ou desiste. O site vira placar de botões, não funil.
- **Omissão no vocabulário:** `CTA único por tela` está nos princípios, mas **sem Enforcement Engine** (o gerador não valida conflitos).
- **Regra para o gerador:** Implementar `CTA Hierarchy Lock`: 1 primário por viewport (cor forte, posição thumb-friendly, link `tel:` ou `wa.me`). Secundários: `opacity 0.7`, `border-only`, ou revelados no scroll. Auto-desabilitar CTAs não conversivos (Instagram, newsletter, blog) em T1/T2.

### 6. A Prova Social Genérica (Stock Testimonial Trap)
- **O que acontece:** Gerador preenche depoimentos com nomes fictícios, fotos de banco de imagem e textos AI genéricos (“Excelente atendimento!”).
- **Por que destrói conversão:** Público local valida por Google Meu Negócio e prints de WhatsApp. Prova falsa/gênica ativa detector de golpe imediato.
- **Omissão no vocabulário:** `Avaliações do Google` e `Print de elogio no WhatsApp` estão listados, mas **sem validação de origem ou bloqueio de geração sintética**.
- **Regra para o gerador:** Bloquear geração automática de depoimentos. Exibir apenas: (a) screenshots reais de WhatsApp fornecidas pelo cliente, ou (b) pull via Google Places API com link de verificação. Se ausente, substituir por `métrica local + cases` (`“+120 clientes em [Cidade] atendidos este ano”`) + selo de garantia, nunca frase genérica.

### 7. O Microcopy Corporativo em Lugar de Regional (Tone Mismatch)
- **O que acontece:** Gerador usa prompts padrão de IA: “Soluções inovadoras”, “Excelência em cada detalhe”, “Transforme seu negócio”.
- **Por que destrói conversão:** Interior SP responde a linguagem direta, prática e regional. Tom corporativo soa distante, cara e pouco confiável para negócio local.
- **Omissão no vocabulário:** `micro-copy regionalista` está nos princípios, mas **sem dicionário de restrição ou template geolocalizado**.
- **Regra para o gerador:** Injetar `geo-templates` por cidade/região. Bloquear buzzwords corporativos via regex no pré-processamento. Forçar padrão: `[Ação] + [Benefício concreto] + [Região/Tempo]`. Ex: `“Orçamento sem sair de casa. Atendemos Bauru e região em até 2h.”` Validação automática antes do render.

### 8. O Header Decorativo (Navigation Over Utility)
- **O que acontece:** Gerador prioriza menu hamburguer + logo grande + links institucionais (“Sobre”, “Blog”, “Política”) na hero, empurrando contato para fora da tela.
- **Por que destrói conversão:** Usuário local em mobile busca contato imediato. Navegação institucional é ruído. Cada pixel de scroll extra = drop-off.
- **Omissão no vocabulário:** `Header fixo`, `Menu hambúrguer` estão listados, mas **sem priorização de utilidade sobre decoração**.
- **Regra para o gerador:** Forçar `Contact-First Header`: `tel:` + `WhatsApp` visíveis sem scroll. Logo ≤ 60px. Menu reduzido a 2-3 links essenciais. Em T1, substituir navegação por `âncoras de ação` (Serviço, Prova, Contato). O header deve ser instrumental, não identitária.

---

### 🛠️ Como injetar isso no motor JPOS
1. **Regras de Bloqueio (Hard Guards):** Carrossel hero, formulários longos na dobra, iframes de mapa, depoimentos AI, CTAs múltiplos primários.
2. **Validação Pré-Render:** Regex para buzzwords, contador de CTAs por viewport, verificação de origem de prova social.
3. **Fallback Automatizado:** Se o cliente não fornecer X, o gerador substitui por padrão conversivo (ex: sem depoimento → métrica regional + garantia; sem mapa → endereço + Waze).
4. **Tier Lock:** T1/T2 ativam `Performance + Conversão Direta` (sem JS pesado, sem secundários). T3/T4 liberam recursos sob demanda com `lazy + skeleton`.

Essas regras transformam o gerador de “montador de blocos” em **filtro anti-distorção**, impedindo que padrões de agência/templates genéricos contaminem a conversão de negócio local.