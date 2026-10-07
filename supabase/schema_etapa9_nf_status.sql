-- Status Nota Fiscal (Confirmacao de Coleta + Posicao NF): uma linha por
-- nota fiscal/minuta, por cliente. Mesma regra de acesso de public.fretes:
-- admin ve/edita tudo, cliente ve so as proprias linhas.
--
-- Quem grava e o script sync_nf_status.py (service role, ignora RLS), que
-- copia as NFs do indicador-ansell. O navegador so le.
-- Rodar no SQL Editor do Supabase (projeto indicador-clientes).

create table public.nf_status (
  id bigint generated always as identity primary key,
  cliente_id uuid not null references public.clientes(id) on delete cascade,
  minuta text not null,
  nf text not null,
  cte text not null default '',
  status_cte text not null default '',
  nf_data date,
  data_recebimento date,
  cliente text not null default '',
  destino text not null default '',
  cidade_destino text not null default '',
  uf_destino text not null default '',
  local_entrega text not null default '',
  cidade_entrega text not null default '',
  uf_entrega text not null default '',
  coletada text not null default '',
  id_carregamento text not null default '',
  -- NF cancelada/pendente reemitida depois em outra minuta: lista das
  -- linhas anteriores (mesmos campos acima), mostrada ao clicar na linha
  historico jsonb,
  -- posicao da linha na lista de origem (a tela mostra nessa ordem)
  ordem integer not null default 0,
  atualizado_em timestamptz not null default now(),
  unique (cliente_id, minuta, nf)
);

comment on table public.nf_status is 'Notas fiscais por minuta (relatorio de NFs emitidas do portal), por cliente';

create index nf_status_cliente_id_idx on public.nf_status (cliente_id, ordem);

alter table public.nf_status enable row level security;

create policy "admin_tudo_nf_status" on public.nf_status
  for all
  using (exists (select 1 from public.meu_profile() p where p.role = 'admin'))
  with check (exists (select 1 from public.meu_profile() p where p.role = 'admin'));

create policy "cliente_le_proprio_nf_status" on public.nf_status
  for select
  using (cliente_id = (select cliente_id from public.meu_profile()));
