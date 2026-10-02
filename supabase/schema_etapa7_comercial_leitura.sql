-- Papel "comercial_leitura": convidado (ex.: cliente) que so VE a tabela
-- comercial VIGENTE e a regra de ICMS VIGENTE e usa o simulador, na pagina
-- comercial.html do indicador-ansell.
--
-- Ele NAO le: outras versoes de tabela, historico/chat de negociacao,
-- dados dos clientes do indicador-clientes. NAO insere nem altera nada
-- (as policies de insert continuam so de admin; nao ha update/delete).
-- Rodar no SQL Editor do Supabase (projeto indicador-clientes), depois do
-- schema_etapa6_comercial.sql.

-- 1) novo papel aceito em profiles (sem cliente_id obrigatorio)
alter table public.profiles drop constraint if exists profiles_role_check;
alter table public.profiles add constraint profiles_role_check
  check (role in ('admin', 'cliente', 'comercial_leitura'));

alter table public.profiles drop constraint if exists cliente_id_obrigatorio_se_nao_admin;
alter table public.profiles add constraint cliente_id_obrigatorio_se_nao_admin
  check (role in ('admin', 'comercial_leitura') or cliente_id is not null);

-- 2) leitura SOMENTE do que esta vigente
create policy "leitura_le_tabela_vigente" on public.comercial_tabelas
  for select
  using (vigente and exists (select 1 from public.meu_profile() p where p.role = 'comercial_leitura'));

create policy "leitura_le_regra_icms_vigente" on public.comercial_regras_icms
  for select
  using (vigente and exists (select 1 from public.meu_profile() p where p.role = 'comercial_leitura'));

-- comercial_historico: sem policy pra comercial_leitura = negado (de proposito).

-- 3) Como dar acesso a um convidado:
--    a) Authentication > Users > Add user (e-mail + senha, Auto Confirm User);
--    b) rodar (trocando e-mail e nome):
--       insert into public.profiles (id, nome, role, cliente_id)
--       select id, 'Nome do convidado', 'comercial_leitura', null
--       from auth.users where email = 'email@do.convidado';
