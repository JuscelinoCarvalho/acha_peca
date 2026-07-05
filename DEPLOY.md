# acha peça — rodar e publicar em parts.jussa.com.br

O projeto tem duas partes:

- **`motor/`** — coleta os dados dos catálogos Fraga para o SQLite `acha_peca.db`.
- **`app/`** — API FastAPI + front web (SPA/PWA) que serve o buscador de intercâmbio.

## Rodar localmente

```bash
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.server:app --host 127.0.0.1 --port 8077
# abre http://localhost:8077
```

## Atualizar os dados (opcional, quando quiser recoletar)

```bash
python -m motor sweep          # varre os catálogos abertos conhecidos (~45k peças)
python -m motor stats          # confere o banco
```

## Publicar em parts.jussa.com.br

1. **Servir a app** (na máquina/servidor do domínio), escutando local:

   ```bash
   uvicorn app.server:app --host 127.0.0.1 --port 8077 --workers 2
   ```

   Para manter no ar, use um serviço systemd (exemplo em `deploy/achapeca.service`).

2. **Proxy reverso com HTTPS** apontando o subdomínio para a porta 8077.
   A PWA **exige HTTPS** para instalar/rodar o service worker (localhost é exceção).

   **Caddy** (TLS automático — mais simples):
   ```
   parts.jussa.com.br {
       reverse_proxy 127.0.0.1:8077
   }
   ```

   **Nginx** (com certbot para o certificado):
   ```nginx
   server {
       server_name parts.jussa.com.br;
       location / { proxy_pass http://127.0.0.1:8077; proxy_set_header Host $host; }
   }
   ```

3. Pronto: `https://parts.jussa.com.br` abre o buscador; no celular, "Adicionar à tela inicial" instala como app.

## Observações

- O `acha_peca.db` (~310 MB) é o dado. Leva-o junto no deploy (ou recoleta com o `sweep`).
- A API abre o banco em modo **somente leitura**, então dá para recoletar em paralelo.
