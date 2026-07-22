# Pendências de ativação (fora do código deste repo)

## 1. DNS — destrava video/imagem/sites.noemi.digital (ação JP, ~2 min)
Criar 3 registros **A → 2.24.120.204** no DNS de noemi.digital:
`video`, `imagem`, `sites`. Caddy já está configurado; os certs TLS emitem
sozinhos quando o DNS propagar. Até lá, o Motor B responde local na :8010.

## 2. ANTHROPIC_API_KEY — destrava o modo real do Motor B (ação JP)
Único item que falta pra `MOCK_MODE=false` (ver README, "Ponto de troca").
O OAuth Higgsfield já está concluído (2026-07-21, plano plus, 1010 créditos).

## 3. Modo real é prompt-only — image-to-video é a Fase 2 (build futuro)
`higgsfield_video.generate` já gera vídeo real por prompt, mas NÃO anexa a mídia
enviada pelo cliente (foto do imóvel). Fase 2 = subir o asset via
`media_upload`/`media_import_url` do MCP e passar o `media_id` no `generate_video`
(image-to-video). Até lá o pipeline completo upload→vídeo só é fiel em MOCK.

## 4. Card "Produtos" no painel de produção — ADIADO de propósito
O painel (:3000, `noemi-painel.service`, checkout `/root/sdr-motor/web`) está
numa branch em andamento (`feat/noemi-final-cleanup`, `sw.js` modificado sem
commit). Rebuild agora embarcaria a branch inteira no war-room — risco > ganho.

Quando a branch estabilizar, o card é pequeno (nav é config-driven pelo cartucho):
1. `web/components/AppShell.tsx`: adicionar ao CATALOGO
   `produtos: { key: "produtos", label: "Produtos", icon: Boxes, href: "/produtos" }`
2. Criar `web/app/produtos/page.tsx` com 3 cards estáticos:
   🎥 video.noemi.digital (em build) · 🌐 videoshiggs.noemi.digital (ativo) ·
   🖼️ imagem.noemi.digital (experimental)
3. Adicionar `"produtos"` ao bloco `nav` do cartucho do operador (DB)
4. `npm run build` + bump VERSION no sw.js + `systemctl restart noemi-painel`

## 5. Sem auth no Motor B (aceito na Fase 1, rever antes de beta multi-cliente)
Mitigado no código: sem listagem pública de jobs, ids uuid4 não-adivinháveis,
erro genérico, upload 25MB + cap 30MB no Caddy, duration clampada. Um token
simples por cliente entra quando houver 2º cliente de verdade.

## 6. Watermark de marca é TEXTO, não overlay do logo PNG (Onda 1 — follow-up)
`apps/motor-b-video/pos.py` desenha o NOME da marca via `drawtext` como watermark.
O `logo_url` do cartucho é uma URL e o pipeline não busca imagem externa. Quando
um cliente subir um ARQUIVO de logo de verdade, trocar por overlay de PNG
(`ffmpeg -i vídeo -i logo.png -filter_complex overlay=...`) — ~15 linhas, o
brand_kit já carrega o campo. Não é bug; é acabamento adiado por não haver logo
real ainda. Marcado com `ponytail:` no próprio pos.py.
