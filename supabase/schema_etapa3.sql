-- Indicador Clientes -- Etapa 3: funcao auxiliar usada pela tela
-- admin.html (Cadastro de Cliente) pra vincular um login ja criado no
-- Supabase Auth (email + senha, criado manualmente em
-- Authentication > Users) a um cliente/papel em public.profiles.
--
-- auth.users nao e exposta por RLS ao client, entao a tela nao
-- consegue descobrir o id (uuid) de um login so pelo email. Esta
-- funcao resolve isso: roda com security definer (le auth.users), mas
-- so devolve algo se quem chamou for admin (via meu_profile()).
--
-- Rodar no SQL Editor do Supabase, depois do schema_etapa2.sql.

create or replace function public.buscar_auth_user_id(p_email text)
returns uuid
language sql
security definer
stable
as $$
  select case
    when (select role from public.meu_profile()) = 'admin'
      then (select id from auth.users where email = p_email limit 1)
    else null
  end;
$$;

revoke all on function public.buscar_auth_user_id(text) from public;
grant execute on function public.buscar_auth_user_id(text) to authenticated;
