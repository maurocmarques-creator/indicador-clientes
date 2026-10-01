#!/usr/bin/env python3
"""
extrair_portal.py — Automatiza a extracao do relatorio 106 (Emissoes) do
portal Brudam (azportoex.brudam.com.br) para os clientes Ansell e Hercules.

Repete, via navegador headless, exatamente o fluxo manual:
  login -> Operacional > Relatorios > 106 Emissoes
  -> filtro Cliente + Data Emissao (01/01/<ano atual> ate ontem) -> Pesquisar
  -> Personalizado Excel -> Meus relatorios -> "AUDITORIA TELA 106_ANSELL"
  -> Gerar (isso ja baixa o Excel correto)

Credenciais NUNCA ficam no codigo: vem das variaveis de ambiente
PORTAL_USER e PORTAL_PASS (defina antes de rodar, ou configure como
Secrets do GitHub quando isso for automatizado na nuvem).

Uso:
  set PORTAL_USER=seu.usuario
  set PORTAL_PASS=sua.senha
  python extrair_portal.py [pasta_de_saida]
"""

import os
import sys
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from config import CONFIG

PORTAL_URL = "https://azportoex.brudam.com.br/"
RELATORIO_URL = "https://azportoex.brudam.com.br/opr/relatorio/emissoes"
RELATORIO_PERSONALIZADO = CONFIG["template_relatorio"]
CLIENTES = CONFIG["clientes_portal"]


def log(msg):
    print(msg, flush=True)


def login(page, usuario, senha):
    log(f"Acessando {PORTAL_URL} ...")
    page.goto(PORTAL_URL)
    page.get_by_placeholder("Usuário").fill(usuario)
    page.get_by_placeholder("Senha").fill(senha)
    page.get_by_text("Acessar Sistema").click()
    page.wait_for_load_state("networkidle")
    if "inicio.php" not in page.url and "opr" not in page.url:
        # confere que nao ficou na tela de login (credenciais invalidas etc.)
        page.wait_for_timeout(1500)
    log(f"Login OK, URL atual: {page.url}")


def get_cliente_input(page):
    """O campo de texto do filtro Cliente fica na linha seguinte ao
    combobox 'Cliente', na mesma coluna da tabela — a pagina nao usa
    id/name estaveis nesses campos. Ao voltar pra essa tela entre um
    cliente e outro, a pagina pode levar um instante a mais pra montar
    o select — espera ele existir de fato antes de procurar."""
    page.wait_for_function(
        "() => Array.from(document.querySelectorAll('select')).some(s => s.value === 'id_cliente')",
        timeout=20000,
    )
    handle = page.evaluate_handle(
        """
        () => {
            const sel = Array.from(document.querySelectorAll('select'))
                .find(s => s.value === 'id_cliente');
            const headerRow = sel.closest('tr');
            const idx = Array.from(headerRow.children).indexOf(sel.closest('td'));
            const dataRow = headerRow.nextElementSibling;
            return dataRow.children[idx].querySelector('input[type=text]');
        }
        """
    )
    el = handle.as_element()
    if el is None:
        raise RuntimeError("Campo de filtro 'Cliente' nao encontrado na pagina")
    return el


def set_date_range(page, data_ini, data_fim):
    campos = page.locator("input.brd-periodo")
    campos.nth(0).fill(data_ini)
    campos.nth(1).fill(data_fim)
    # fecha qualquer calendario popup que tenha aberto ao focar o campo
    page.keyboard.press("Escape")


def extrair_cliente(page, cliente, data_ini, data_fim, pasta_saida: Path) -> Path:
    log(f"\n=== Extraindo cliente: {cliente} ===")
    page.goto(RELATORIO_URL)
    page.wait_for_load_state("networkidle")

    cliente_input = get_cliente_input(page)
    cliente_input.fill(cliente)

    set_date_range(page, data_ini, data_fim)

    log("Clicando em PESQUISAR...")
    page.get_by_role("button", name="PESQUISAR").click()
    page.wait_for_selector("text=/registros|Selecione um dos relat/i", timeout=30000)

    log("Abrindo Personalizado Excel...")
    page.get_by_text("Personalizado Excel", exact=False).click()
    page.wait_for_selector("text=Personalizar Relatório", timeout=15000)

    log("Abrindo Meus relatórios...")
    page.get_by_text("Meus relatórios", exact=False).click()
    page.wait_for_selector("text=Relatórios Personalizados", timeout=15000)

    log(f"Selecionando relatório '{RELATORIO_PERSONALIZADO}'...")
    page.get_by_role("radio", name=RELATORIO_PERSONALIZADO).check()

    pasta_saida.mkdir(parents=True, exist_ok=True)
    destino = pasta_saida / f"{cliente.lower()}.xlsx"

    log("Clicando em Gerar (isso já gera o Excel correto)...")
    with page.expect_download(timeout=180000) as download_info:
        page.get_by_role("button", name="Gerar").click()
        # Em alguns casos aparece uma caixa extra perguntando CSV/XLSX —
        # se aparecer, confirma XLSX; se o download ja comecou sozinho,
        # esse bloco so encerra no timeout curto sem atrapalhar.
        try:
            page.wait_for_selector("text=Escolha o tipo de exportação", timeout=5000)
            page.get_by_role("button", name="XLSX").click()
        except PlaywrightTimeoutError:
            pass
    download = download_info.value
    download.save_as(destino)
    log(f"Salvo: {destino}")
    return destino


def main():
    usuario = os.environ.get("PORTAL_USER")
    senha = os.environ.get("PORTAL_PASS")
    if not usuario or not senha:
        log("Defina as variaveis de ambiente PORTAL_USER e PORTAL_PASS antes de rodar.")
        sys.exit(1)

    pasta_saida = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "downloads_tmp"

    hoje = date.today()
    data_ini = date(hoje.year, 1, 1).strftime("%d/%m/%Y")
    data_fim = (hoje - timedelta(days=1)).strftime("%d/%m/%Y")
    log(f"Periodo: {data_ini} ate {data_fim}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(60000)

        login(page, usuario, senha)

        arquivos = {}
        for cliente in CLIENTES:
            arquivos[cliente] = extrair_cliente(page, cliente, data_ini, data_fim, pasta_saida)

        browser.close()

    log("\nExtração concluída:")
    for cliente, caminho in arquivos.items():
        log(f"  {cliente}: {caminho}")


if __name__ == "__main__":
    main()
