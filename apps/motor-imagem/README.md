# Motor Imagem (stub)

Uso ainda indefinido — JP vai testar com Pé Di antes de qualquer lógica.

- Porta **8011** reservada; `imagem.noemi.digital` hoje é placeholder direto no Caddy.
- Quando ativar: copiar a forma do `motor-b-video` (upload → fila → status) e expor
  `image.generate(asset, config)` em `packages/shared-core/ai/` (mesmo padrão do vídeo,
  provider por trás: Higgsfield `generate_image` / `outpaint_image` / `remove_background`).
- Pra subir: trocar o bloco `respond` do Caddy por `reverse_proxy localhost:8011`.
