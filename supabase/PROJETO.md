# Projeto Supabase — indicador-clientes

- **Project URL**: `https://fydoatntynvcwudxkhqv.supabase.co`
- **Project ID**: `fydoatntynvcwudxkhqv`
- **Região**: sa-east-1 (São Paulo)
- **Publishable key** (segura pra usar no navegador/index.html): `sb_publishable_lXegUG6Ry1uZI3lqnbKyQg_lv-Ivzv6`
- **Organização**: "CAlculadora de Frete" no Supabase — mesma organização/conta do projeto Calculadora de Frete, mas é um **projeto separado** (banco de dados isolado), como combinado.

A **secret key** (`sb_secret_...`) fica só com o Mauro — nunca neste repositório nem em nenhum arquivo versionado. Vai ser necessária só na Etapa 3 (criação de login de cliente via admin), e nesse momento decidimos onde ela mora com segurança (ex.: variável de ambiente de uma Supabase Edge Function, nunca no código do site).

## Status

- [x] Etapa 2 concluída (01/10/2026): tabelas `clientes`/`profiles` criadas, RLS ativo, primeiro admin (mauro.cesar@portoex.com.br) cadastrado e confirmado.
