-- Indicador Clientes -- Etapa 4: dados operacionais (frete) por cliente.
--
-- Substitui o antigo padrao de um index.html por cliente com os dados
-- embutidos num blob JSON (RAW) -- agora toda extracao do Brudam, pra
-- todos os clientes ativos, grava direto aqui, uma linha por minuta,
-- marcada com cliente_id. O pipeline (pipeline_atualizar.py) escreve
-- usando a service role key (nunca o publishable key, que so le,
-- filtrado por RLS, o que o cliente logado tem permissao de ver).
--
-- Ainda NAO inclui: correcoes manuais de status/data, observacoes do
-- Mural, motivo de ocorrencia, ID de carregamento -- essas funcionalidades
-- continuam especificas do projeto indicador-ansell por enquanto (ver
-- PROJETO.md), migradas pra ca numa etapa futura.

create table public.fretes (
  id bigint generated always as identity primary key,
  cliente_id uuid not null references public.clientes(id) on delete cascade,
  minuta text not null,
  nf_doc text not null default '',
  mes text not null,
  mes_nome text not null,
  mes_prev text not null,
  mes_prev_nome text not null,
  status text not null,
  cliente_portal text not null default '',
  volumes integer not null default 0,
  frete_total numeric not null default 0,
  nf_valor numeric not null default 0,
  peso numeric not null default 0,
  tx_pedagio numeric not null default 0,
  valor_icms numeric not null default 0,
  tx_gris numeric not null default 0,
  tx_frete_peso numeric not null default 0,
  tx_outros numeric not null default 0,
  tx_nota numeric not null default 0,
  tipo_emissao text not null default '',
  cotacao text not null default 'N',
  data_emissao date,
  data_entrega date,
  prev_entrega date,
  data_agendamento date,
  eff_local text not null default '',
  redespacho text not null default '',
  eff_cidade text not null default '',
  eff_uf text not null default '',
  regiao text not null default '',
  lat double precision,
  lng double precision,
  descricao_ultimo text not null default '',
  atualizado_em timestamptz not null default now(),
  unique (cliente_id, minuta)
);

comment on table public.fretes is 'Uma linha por minuta (dados do relatorio 106 do Brudam), por cliente';

create index fretes_cliente_id_idx on public.fretes (cliente_id);

alter table public.fretes enable row level security;

create policy "admin_tudo_fretes" on public.fretes
  for all
  using (exists (select 1 from public.meu_profile() p where p.role = 'admin'))
  with check (exists (select 1 from public.meu_profile() p where p.role = 'admin'));

create policy "cliente_le_proprio_fretes" on public.fretes
  for select
  using (cliente_id = (select cliente_id from public.meu_profile()));

-- ============================================================
-- Historico de ocorrencias: o Brudam so entrega a ultima ocorrencia de
-- cada minuta (sobrescrita a cada extracao) -- o pipeline compara com
-- o ultimo registro conhecido aqui e so insere um novo quando a
-- descricao mudou, construindo o historico do lado da PortoEx.
-- ============================================================
create table public.ocorrencias_historico (
  id bigint generated always as identity primary key,
  cliente_id uuid not null references public.clientes(id) on delete cascade,
  minuta text not null,
  descricao text not null,
  detectado_em timestamptz not null default now()
);

create index ocorrencias_historico_cliente_minuta_idx on public.ocorrencias_historico (cliente_id, minuta);

alter table public.ocorrencias_historico enable row level security;

create policy "admin_tudo_ocorrencias_historico" on public.ocorrencias_historico
  for all
  using (exists (select 1 from public.meu_profile() p where p.role = 'admin'))
  with check (exists (select 1 from public.meu_profile() p where p.role = 'admin'));

create policy "cliente_le_proprio_ocorrencias_historico" on public.ocorrencias_historico
  for select
  using (cliente_id = (select cliente_id from public.meu_profile()));
