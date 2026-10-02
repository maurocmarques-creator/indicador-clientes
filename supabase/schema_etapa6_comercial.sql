-- Comercial (usado pela aba Comercial do indicador-ansell): tabelas de
-- tarifa comerciais com historico tipo chat, e regras de ICMS.
--
-- Acesso: so usuarios com profiles.role = 'admin' (time PortoEx).
-- Registros nunca sao editados: cada tabela/regra nova e um registro novo.
-- Unica mudanca permitida e marcar qual e a vigente, via as funcoes
-- comercial_marcar_*_vigente (security definer) -- nao ha policy de
-- update/delete, entao o cliente (browser) nao consegue alterar nem apagar.
-- Rodar no SQL Editor do Supabase (projeto indicador-clientes), depois do
-- schema_etapa2.sql (usa public.profiles e public.meu_profile()).

-- ============================================================
-- Tabelas comerciais (tarifa por cidade + faixas), uma por upload
-- ============================================================
create table public.comercial_tabelas (
  id uuid primary key default gen_random_uuid(),
  nome text not null,
  arquivo_origem text,
  criada_em timestamptz not null default now(),
  criada_por uuid,
  criada_por_nome text,
  vigente boolean not null default false,
  -- {faixas: {cabecalhos, linhas}, cidades: [...]} -- ver comercial.js
  dados jsonb not null
);

-- no maximo uma tabela vigente por vez
create unique index comercial_tabelas_uma_vigente
  on public.comercial_tabelas (vigente) where vigente;

-- ============================================================
-- Historico (chat) de cada tabela: status e/ou comentario, com autor
-- ============================================================
create table public.comercial_historico (
  id bigint generated always as identity primary key,
  tabela_id uuid not null references public.comercial_tabelas(id) on delete cascade,
  status text check (status in (
    'Enviada - aguardando aprovação', 'Em negociação', 'Aprovada', 'Reprovada', 'Vigente'
  )),
  comentario text,
  autor_id uuid,
  autor_nome text,
  autor_email text,
  criado_em timestamptz not null default now(),
  constraint comercial_historico_status_ou_comentario
    check (status is not null or coalesce(btrim(comentario), '') <> '')
);

create index comercial_historico_tabela_idx
  on public.comercial_historico (tabela_id, criado_em);

-- ============================================================
-- Regras de ICMS (matriz UF origem x UF destino), uma por upload
-- ============================================================
create table public.comercial_regras_icms (
  id uuid primary key default gen_random_uuid(),
  nome text not null,
  arquivo_origem text,
  criada_em timestamptz not null default now(),
  criada_por uuid,
  criada_por_nome text,
  vigente boolean not null default false,
  -- {ufs: [...], matriz: {"SP": {"AC": 7, ...}, ...}} -- aliquota em %
  dados jsonb not null
);

create unique index comercial_regras_icms_uma_vigente
  on public.comercial_regras_icms (vigente) where vigente;

-- ============================================================
-- Autor preenchido no servidor (o browser nao consegue falsificar)
-- ============================================================
create or replace function public.comercial_preenche_autor()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_nome text;
  v_email text;
begin
  select nome into v_nome from public.profiles where id = auth.uid();
  select email into v_email from auth.users where id = auth.uid();
  if tg_table_name = 'comercial_historico' then
    new.autor_id := auth.uid();
    new.autor_nome := v_nome;
    new.autor_email := v_email;
  else
    new.criada_por := auth.uid();
    new.criada_por_nome := v_nome;
  end if;
  return new;
end;
$$;

create trigger comercial_tabelas_autor before insert on public.comercial_tabelas
  for each row execute function public.comercial_preenche_autor();
create trigger comercial_historico_autor before insert on public.comercial_historico
  for each row execute function public.comercial_preenche_autor();
create trigger comercial_regras_icms_autor before insert on public.comercial_regras_icms
  for each row execute function public.comercial_preenche_autor();

-- ============================================================
-- RLS: so admin le e insere. Sem policy de update/delete.
-- ============================================================
alter table public.comercial_tabelas enable row level security;
alter table public.comercial_historico enable row level security;
alter table public.comercial_regras_icms enable row level security;

create policy "admin_le_comercial_tabelas" on public.comercial_tabelas
  for select using (exists (select 1 from public.meu_profile() p where p.role = 'admin'));
create policy "admin_insere_comercial_tabelas" on public.comercial_tabelas
  for insert with check (exists (select 1 from public.meu_profile() p where p.role = 'admin'));

create policy "admin_le_comercial_historico" on public.comercial_historico
  for select using (exists (select 1 from public.meu_profile() p where p.role = 'admin'));
create policy "admin_insere_comercial_historico" on public.comercial_historico
  for insert with check (exists (select 1 from public.meu_profile() p where p.role = 'admin'));

create policy "admin_le_comercial_regras_icms" on public.comercial_regras_icms
  for select using (exists (select 1 from public.meu_profile() p where p.role = 'admin'));
create policy "admin_insere_comercial_regras_icms" on public.comercial_regras_icms
  for insert with check (exists (select 1 from public.meu_profile() p where p.role = 'admin'));

-- ============================================================
-- Marcar vigente (unica "edicao" permitida)
-- ============================================================
create or replace function public.comercial_marcar_tabela_vigente(p_id uuid)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if not exists (select 1 from public.profiles where id = auth.uid() and role = 'admin') then
    raise exception 'sem permissao';
  end if;
  update public.comercial_tabelas set vigente = false where vigente;
  update public.comercial_tabelas set vigente = true where id = p_id;
  -- se p_id nao existir, esta insercao falha na FK e desfaz tudo
  insert into public.comercial_historico (tabela_id, status, comentario)
    values (p_id, 'Vigente', 'Marcada como vigente');
end;
$$;

create or replace function public.comercial_marcar_regra_icms_vigente(p_id uuid)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if not exists (select 1 from public.profiles where id = auth.uid() and role = 'admin') then
    raise exception 'sem permissao';
  end if;
  update public.comercial_regras_icms set vigente = false where vigente;
  update public.comercial_regras_icms set vigente = true where id = p_id;
  if not exists (select 1 from public.comercial_regras_icms where id = p_id and vigente) then
    raise exception 'regra nao encontrada';
  end if;
end;
$$;

revoke all on function public.comercial_marcar_tabela_vigente(uuid) from public;
revoke all on function public.comercial_marcar_regra_icms_vigente(uuid) from public;
grant execute on function public.comercial_marcar_tabela_vigente(uuid) to authenticated;
grant execute on function public.comercial_marcar_regra_icms_vigente(uuid) to authenticated;
