// auth.js -- Indicador Clientes: sessao, login/logout, perfil (admin ou
// cliente) e visibilidade de paineis por cliente.
//
// Carregado ANTES do script principal de cada pagina (index.html,
// admin.html). O script principal deve comecar com
// "await window.authPronto" pra so seguir depois que a sessao e o
// perfil estiverem resolvidos (ou o usuario ja ter sido redirecionado
// pro login).

const SUPABASE_URL = 'https://fydoatntynvcwudxkhqv.supabase.co';
const SUPABASE_ANON_KEY = 'sb_publishable_lXegUG6Ry1uZI3lqnbKyQg_lv-Ivzv6';

const supabaseClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

// Depois que authPronto resolver, fica disponivel como:
// {id, nome, role, cliente_id, clientes: {nome, nomes_portal, paineis_permitidos, ativo} | null}
window.PERFIL_ATUAL = null;

// Paginas que nao exigem login (a propria tela de login).
const PAGINAS_PUBLICAS = ['login.html'];

function paginaAtual() {
  return location.pathname.split('/').pop() || 'index.html';
}

window.authPronto = (async function iniciarAuth() {
  if (PAGINAS_PUBLICAS.includes(paginaAtual())) return null;

  const { data: { session } } = await supabaseClient.auth.getSession();
  if (!session) {
    location.href = 'login.html';
    return null;
  }

  const { data: profile, error } = await supabaseClient
    .from('profiles')
    .select('*, clientes(*)')
    .eq('id', session.user.id)
    .maybeSingle();

  if (error || !profile) {
    // Login existe no Supabase Auth mas nao tem profile vinculado
    // (cadastro incompleto) -- desloga em vez de deixar numa tela
    // quebrada sem saber quem e.
    await supabaseClient.auth.signOut();
    location.href = 'login.html?erro=sem_perfil';
    return null;
  }

  if (profile.role !== 'admin' && profile.role !== 'cliente') {
    // Outros papeis (ex.: comercial_leitura, usado so na pagina Comercial do
    // indicador-ansell) nao tem acesso a este sistema.
    await supabaseClient.auth.signOut();
    location.href = 'login.html?erro=sem_acesso';
    return null;
  }

  if (profile.role === 'cliente' && (!profile.clientes || !profile.clientes.ativo)) {
    // Cliente desativado (ou sem vinculo) -- barra o acesso mesmo com
    // login valido.
    await supabaseClient.auth.signOut();
    location.href = 'login.html?erro=inativo';
    return null;
  }

  window.PERFIL_ATUAL = profile;
  return profile;
})();

async function logout() {
  await supabaseClient.auth.signOut();
  location.href = 'login.html';
}

// Esconde da barra de abas qualquer .tab[data-tab] que nao esteja na
// lista de paineis liberados do cliente. Admin sempre ve tudo (nao
// filtra nada). Chamar depois que window.authPronto resolver.
function aplicarPermissoesPaineis(perfil) {
  if (!perfil || perfil.role === 'admin') return;
  const permitidos = new Set((perfil.clientes && perfil.clientes.paineis_permitidos) || []);
  document.querySelectorAll('.tab[data-tab]').forEach(btn => {
    if (!permitidos.has(btn.dataset.tab)) btn.style.display = 'none';
  });
}
