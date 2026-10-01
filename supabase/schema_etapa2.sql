-- Indicador Clientes -- Etapa 2: clientes, perfis (login) e permissao de
-- paineis por cliente. Rodar no SQL Editor do Supabase (projeto novo,
-- separado do projeto da Calculadora de Frete).
--
-- Nao inclui ainda as tabelas de dados operacionais (minutas, NFs,
-- ocorrencias) -- essas vem na Etapa 4, quando o pipeline for adaptado
-- pra gravar no Supabase em vez de no index.html.

-- ============================================================
-- Tabela: clientes
-- Um registro por cliente da PortoEx (ex.: Ansell, outro cliente X).
-- ============================================================
create table public.clientes (
  id uuid primary key default gen_random_uuid(),
  nome text not null,
  -- Nome(s) do cliente exatamente como aparecem no portal Brudam (pode
  -- ser mais de um, ex.: Ansell + Hercules sao extraidos juntos hoje).
  -- Usado pelo pipeline pra saber quais linhas do Brudam pertencem a
  -- este cliente.
  nomes_portal text[] not null default '{}',
  -- Quais abas/paineis do dashboard este cliente pode ver. Os valores
  -- usam o mesmo id das abas do index.html (data-tab): 'totais',
  -- 'totais-cx', 'performance', 'perf-dest', 'resumo-dest',
  -- 'barra-perf', 'transito', 'ocorrencias', 'antecipadas', 'statusnf',
  -- 'expectativa', 'mapa'.
  paineis_permitidos text[] not null default '{}',
  ativo boolean not null default true,
  created_at timestamptz not null default now()
);

comment on table public.clientes is 'Clientes da PortoEx com acesso ao Indicador (multi-tenant)';

-- ============================================================
-- Tabela: profiles
-- Liga um usuario autenticado (auth.users, email/senha do Supabase
-- Auth) a um cliente e a um papel (admin ve tudo, cliente ve so o seu).
-- ============================================================
create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  nome text not null,
  role text not null check (role in ('admin', 'cliente')),
  -- NULL quando role='admin' (admin nao pertence a um cliente especifico).
  cliente_id uuid references public.clientes(id) on delete cascade,
  created_at timestamptz not null default now(),
  constraint cliente_id_obrigatorio_se_nao_admin
    check (role = 'admin' or cliente_id is not null)
);

comment on table public.profiles is 'Papel e vinculo de cada login (Supabase Auth) com um cliente';

-- ============================================================
-- Funcao auxiliar: le o profile do usuario autenticado na sessao atual
-- (evita repetir a subquery em cada politica de RLS abaixo).
-- ============================================================
create or replace function public.meu_profile()
returns public.profiles
language sql security definer stable
as $$
  select * from public.profiles where id = auth.uid();
$$;

-- ============================================================
-- RLS: clientes
-- ============================================================
alter table public.clientes enable row level security;

-- Admin ve/edita todos os clientes.
create policy "admin_tudo_clientes" on public.clientes
  for all
  using (exists (select 1 from public.meu_profile() p where p.role = 'admin'))
  with check (exists (select 1 from public.meu_profile() p where p.role = 'admin'));

-- Cliente ve so o proprio registro (pra saber nome/paineis liberados).
create policy "cliente_le_proprio" on public.clientes
  for select
  using (id = (select cliente_id from public.meu_profile()));

-- ============================================================
-- RLS: profiles
-- ============================================================
alter table public.profiles enable row level security;

-- Admin ve/edita todos os perfis (pra gerenciar logins de cliente).
create policy "admin_tudo_profiles" on public.profiles
  for all
  using (exists (select 1 from public.meu_profile() p where p.role = 'admin'))
  with check (exists (select 1 from public.meu_profile() p where p.role = 'admin'));

-- Qualquer usuario logado ve o proprio perfil.
create policy "usuario_le_proprio_profile" on public.profiles
  for select
  using (id = auth.uid());

-- ============================================================
-- Primeiro admin (voce, Mauro) -- rode isto DEPOIS de criar seu login
-- manualmente em Authentication > Users no painel do Supabase (email +
-- senha). Troque o e-mail abaixo pelo que voce usou lá.
-- ============================================================
-- insert into public.profiles (id, nome, role, cliente_id)
-- select id, 'Mauro Cesar', 'admin', null
-- from auth.users where email = 'SEU_EMAIL_AQUI';
