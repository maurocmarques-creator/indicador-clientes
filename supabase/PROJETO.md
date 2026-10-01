# Projeto Supabase — indicador-clientes

- **Project URL**: `https://fydoatntynvcwudxkhqv.supabase.co`
- **Project ID**: `fydoatntynvcwudxkhqv`
- **Região**: sa-east-1 (São Paulo)
- **Publishable key** (segura pra usar no navegador/index.html): `sb_publishable_lXegUG6Ry1uZI3lqnbKyQg_lv-Ivzv6`
- **Organização**: "CAlculadora de Frete" no Supabase — mesma organização/conta do projeto Calculadora de Frete, mas é um **projeto separado** (banco de dados isolado), como combinado.

A **secret key** (`sb_secret_...`) fica só com o Mauro — nunca neste repositório nem em nenhum arquivo versionado. Usada só como variável de ambiente `SUPABASE_SERVICE_ROLE_KEY` na máquina que roda `pipeline_atualizar.py` (ver Etapa 4) — nunca no código do site.

## Como criar o login de um cliente novo (passo a passo)

A criação do login (e-mail + senha) é sempre manual, direto no painel do Supabase — o site nunca tem a secret key, então `admin.html` não consegue criar login sozinho, só vincular um e-mail já existente a um cliente.

1. **Criar o login no Supabase**: abra `https://supabase.com/dashboard/project/fydoatntynvcwudxkhqv/auth/users` → botão **"Add user"** → **"Create new user"** → preencha e-mail e senha → marque **"Auto Confirm User"** (senão o login fica pendente de confirmação por e-mail, que não está configurado) → **"Create user"**.
2. **Vincular esse login a um cliente**: abra `admin.html` (local ou publicado), logado como admin → card **"Vincular login a um cliente"** → preencha o mesmo e-mail, o nome da pessoa, papel **"Cliente"** e selecione o cliente → **"Vincular login"**.
3. Pronto — a pessoa já pode entrar em `login.html` com esse e-mail/senha e só vê os painéis liberados pro cliente dela.

Pra cadastrar um **admin** (acesso total, time PortoEx), mesmo passo 1, mas no passo 2 escolha papel **"Admin"** (não precisa selecionar cliente).

## Status

- [x] Etapa 2 concluída (01/10/2026): tabelas `clientes`/`profiles` criadas, RLS ativo, primeiro admin (mauro.cesar@portoex.com.br) cadastrado e confirmado.
- [x] Etapa 3 concluída (01/10/2026): `login.html`, `admin.html` (cadastro de cliente + vínculo de login) e `auth.js` (sessão/trava por painel) no `index.html`. Criação de login de cliente continua manual (Authentication → Users no painel do Supabase); `admin.html` só vincula um e-mail já criado a um cliente/papel, via a função `buscar_auth_user_id` (`schema_etapa3.sql`) — por isso a secret key nunca precisou entrar no código do site.
- [x] Repositório no GitHub: `https://github.com/maurocmarques-creator/indicador-clientes` (privado).
- [x] Etapa 4 concluída (01/10/2026): pipeline (`pipeline_atualizar.py`) agora busca os clientes ativos no Supabase (`nomes_portal` de cada um), extrai todos do portal Brudam (um nome de portal por vez, consolidando por cliente), e grava em duas tabelas novas (`schema_etapa4.sql`): `fretes` (uma linha por minuta, upsert por `cliente_id`+`minuta`) e `ocorrencias_historico` (só insere quando a descrição muda). Escrita usa a **service role key** (`SUPABASE_SERVICE_ROLE_KEY`, variável de ambiente só na máquina do pipeline — nunca no repo) via `supabase_db.py`, que fala direto com a API REST do Supabase.
  - Removidos da cópia (eram específicos da Ansell e não fazem mais sentido multi-cliente): `cliente_config.json`, `config.py`, e os `.json` soltos que alimentavam o Mural (`em_transito.json`, `nf_pendente.json`, `ocorrencias_historico.json`, `ocorrencias_problema.json`).
  - **Ainda NÃO migrado** (decisão consciente, pra não inflar a Etapa 4 — ver conversa de 01/10/2026): correções manuais de status/data, observações do Mural, motivo de ocorrência, ID de carregamento, Status NF (CT-e). Continuam só no projeto indicador-ansell por enquanto; entram numa etapa futura quando o Mural for generalizado pra multi-cliente.
  - [x] `supabase/schema_etapa4.sql` rodado no SQL Editor (01/10/2026).
