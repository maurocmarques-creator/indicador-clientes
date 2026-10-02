-- Convidado (comercial_leitura) passa a VER todas as tabelas comerciais e o
-- historico/chat de cada uma, e a REGISTRAR status e observacoes.
--
-- Pode lancar so: 'Em negociação', 'Aprovada', 'Reprovada' ou apenas um
-- comentario. NAO pode lancar 'Vigente' nem 'Enviada - aguardando aprovação',
-- nao cria tabela, nao marca vigente e nao altera tarifas (sem policy de
-- update/delete). O autor e preenchido no servidor (trigger).
-- Rodar no SQL Editor do Supabase, depois do schema_etapa7_comercial_leitura.sql.

-- 1) leitura de TODAS as tabelas (antes era so a vigente)
drop policy if exists "leitura_le_tabela_vigente" on public.comercial_tabelas;
create policy "leitura_le_tabelas" on public.comercial_tabelas
  for select
  using (exists (select 1 from public.meu_profile() p where p.role = 'comercial_leitura'));

-- 2) leitura do historico/chat
create policy "leitura_le_historico" on public.comercial_historico
  for select
  using (exists (select 1 from public.meu_profile() p where p.role = 'comercial_leitura'));

-- 3) registrar status/observacao (somente os status permitidos ao convidado)
create policy "leitura_insere_historico" on public.comercial_historico
  for insert
  with check (
    exists (select 1 from public.meu_profile() p where p.role = 'comercial_leitura')
    and (status is null or status in ('Em negociação', 'Aprovada', 'Reprovada'))
  );

-- regra de ICMS: continua so a vigente (policy da etapa 7).
