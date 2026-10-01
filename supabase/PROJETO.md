# Projeto Supabase — indicador-clientes

- **Project URL**: `https://fydoatntynvcwudxkhqv.supabase.co`
- **Project ID**: `fydoatntynvcwudxkhqv`
- **Região**: sa-east-1 (São Paulo)
- **Publishable key** (segura pra usar no navegador/index.html): `sb_publishable_lXegUG6Ry1uZI3lqnbKyQg_lv-Ivzv6`
- **Organização**: "CAlculadora de Frete" no Supabase — mesma organização/conta do projeto Calculadora de Frete, mas é um **projeto separado** (banco de dados isolado), como combinado.

A **secret key** (`sb_secret_...`) fica só com o Mauro — nunca neste repositório nem em nenhum arquivo versionado. Vai ser necessária só na Etapa 3 (criação de login de cliente via admin), e nesse momento decidimos onde ela mora com segurança (ex.: variável de ambiente de uma Supabase Edge Function, nunca no código do site).

## Status

- [x] Etapa 2 concluída (01/10/2026): tabelas `clientes`/`profiles` criadas, RLS ativo, primeiro admin (mauro.cesar@portoex.com.br) cadastrado e confirmado.
- [x] Etapa 3 concluída (01/10/2026): `login.html`, `admin.html` (cadastro de cliente + vínculo de login) e `auth.js` (sessão/trava por painel) no `index.html`. Criação de login de cliente continua manual (Authentication → Users no painel do Supabase); `admin.html` só vincula um e-mail já criado a um cliente/papel, via a função `buscar_auth_user_id` (`schema_etapa3.sql`) — por isso a secret key nunca precisou entrar no código do site.
- [x] Repositório no GitHub: `https://github.com/maurocmarques-creator/indicador-clientes` (privado).
- [x] Etapa 4 concluída (01/10/2026): pipeline (`pipeline_atualizar.py`) agora busca os clientes ativos no Supabase (`nomes_portal` de cada um), extrai todos do portal Brudam (um nome de portal por vez, consolidando por cliente), e grava em duas tabelas novas (`schema_etapa4.sql`): `fretes` (uma linha por minuta, upsert por `cliente_id`+`minuta`) e `ocorrencias_historico` (só insere quando a descrição muda). Escrita usa a **service role key** (`SUPABASE_SERVICE_ROLE_KEY`, variável de ambiente só na máquina do pipeline — nunca no repo) via `supabase_db.py`, que fala direto com a API REST do Supabase.
  - Removidos da cópia (eram específicos da Ansell e não fazem mais sentido multi-cliente): `cliente_config.json`, `config.py`, e os `.json` soltos que alimentavam o Mural (`em_transito.json`, `nf_pendente.json`, `ocorrencias_historico.json`, `ocorrencias_problema.json`).
  - **Ainda NÃO migrado** (decisão consciente, pra não inflar a Etapa 4 — ver conversa de 01/10/2026): correções manuais de status/data, observações do Mural, motivo de ocorrência, ID de carregamento, Status NF (CT-e). Continuam só no projeto indicador-ansell por enquanto; entram numa etapa futura quando o Mural for generalizado pra multi-cliente.
  - Falta rodar `supabase/schema_etapa4.sql` no SQL Editor (mesmo processo das anteriores) antes do pipeline rodar de verdade.
