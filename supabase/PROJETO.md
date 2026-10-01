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
- [ ] Falta rodar `supabase/schema_etapa3.sql` no SQL Editor (mesmo processo do `schema_etapa2.sql`).
- [ ] Repositório `indicador-clientes` ainda não tem remoto no GitHub (público/privado a decidir).
