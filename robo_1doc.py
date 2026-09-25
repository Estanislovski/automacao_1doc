# -*- coding: utf-8 -*-
"""
Robo de encaminhamento de comprovantes no 1Doc

O que ele faz:
  1. Descobre a data de referencia (ontem; na segunda-feira, a sexta anterior).
  2. Encontra a pasta PASTA_BASE\\ANO\\MES\\"DD de mes" (aceita variacoes de maiusculas,
     acentos, zero a esquerda e espacos).
  3. Para cada PDF da pasta (ex.: "Memorando 20.185-26.pdf"):
       - pesquisa numero/ano no 1Doc e abre o resultado do tipo certo;
       - se estiver arquivado, clica em Reabrir e confirma;
       - encaminha para a unidade configurada, com o texto padrao,
         marca "Arquivar" e "Arquivar + Parar de acompanhar", anexa o PDF e confirma.
  4. Gera um relatorio (CSV) com o que foi feito e o que ficou pendente.

Uso:
  python robo_1doc.py              -> usa a data de referencia automatica
  python robo_1doc.py 24/09/2026   -> processa a pasta de uma data especifica
"""

import csv
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

# CONFIGURACOES

# Endereco do 1Doc 
URL_1DOC = "https://cidade.1doc.com.br/"

# Pasta base onde ficam as pastas de ano 
PASTA_BASE = r"Z:\secretaria"

# Unidade de destino: o que digitar na busca e o texto exato da opcao
BUSCA_UNIDADE = "nome de busca"
OPCAO_UNIDADE = "nome a ser selecionado"

# Texto padrao
TEXTO_MENSAGEM = "Prezados, {saudacao}!\nSegue comprovante de pagamento."

# Modo conferencia: o robo preenche tudo e PERGUNTA antes de confirmar cada
# encaminhamento.
MODO_CONFERENCIA = True

# Tipos de arquivo e como eles aparecem no 1Doc (na lista de resultados e no
# titulo da janela "Confirma?"). Ajuste se algum nome for diferente.
TIPOS = {
    "despesa extra": ["Despesa Extra"],
    "memorando": ["Memorando"],
    "proc adm": ["Processo Administrativo", "Proc. Adm", "Proc ADM"],
    "protocolo": ["Protocolo"],
}

# Tempo maximo (segundos) esperando o upload do anexo terminar
ESPERA_UPLOAD_SEG = 60

# =====================================================================

PASTA_ROBO = Path(__file__).resolve().parent
PERFIL_NAVEGADOR = PASTA_ROBO / "perfil_navegador"
PASTA_RELATORIOS = PASTA_ROBO / "relatorios"
PASTA_ERROS = PASTA_RELATORIOS / "prints_erros"
ARQ_PROCESSADOS = PASTA_ROBO / "processados.csv"

MESES = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]

RE_ARQUIVO = re.compile(
    r"^(despesa extra|memorando|proc\.? ?adm\.?|protocolo) ?n?[o.]? ?([\d.]+) ?[-/] ?(\d{4}|\d{2})$"
)
RE_PASTA_DIA = re.compile(r"^0*(\d{1,2}) ?(?:de)? ?([a-z]+)$")


class Pendencia(Exception):
    """Situacao em que o robo prefere nao mexer e deixa para conferencia manual."""


# Utilitarios de texto, data e pastas

def normalizar(texto):
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip().lower()


def so_letras_numeros(texto):
    return re.sub(r"[^a-z0-9]", "", normalizar(texto))


def saudacao():
    return "bom dia" if datetime.now().hour < 12 else "boa tarde"


def data_referencia(hoje=None):
    """Dia util anterior: ontem, pulando sabado e domingo."""
    d = (hoje or date.today()) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def achar_unica(pai, teste, descricao):
    if not pai.is_dir():
        raise FileNotFoundError(f"Pasta nao encontrada: {pai}")
    achadas = [p for p in pai.iterdir() if p.is_dir() and teste(normalizar(p.name))]
    if not achadas:
        return None
    if len(achadas) > 1:
        nomes = ", ".join(p.name for p in achadas)
        raise RuntimeError(f"Mais de uma pasta de {descricao} em {pai}: {nomes}")
    return achadas[0]


def achar_pasta_do_dia(d):
    base = Path(PASTA_BASE)
    mes_nome = MESES[d.month - 1]

    pasta_ano = achar_unica(base, lambda n: n == str(d.year), "ano")
    if not pasta_ano:
        return None
    pasta_mes = achar_unica(pasta_ano, lambda n: n == mes_nome, "mes")
    if not pasta_mes:
        return None

    def eh_o_dia(n):
        m = RE_PASTA_DIA.match(n)
        return bool(m) and int(m.group(1)) == d.day and m.group(2) == mes_nome

    return achar_unica(pasta_mes, eh_o_dia, "dia")


def interpretar_nome(arquivo):
    """'Memorando 20.185-26.pdf' -> ('memorando', 20185, 2026). None se fora do padrao."""
    m = RE_ARQUIVO.match(normalizar(arquivo.stem))
    if not m:
        return None
    tipo = re.sub(r"\s+", " ", m.group(1).replace(".", " ")).strip()
    numero = int(m.group(2).replace(".", ""))
    ano = int(m.group(3))
    if ano < 100:
        ano += 2000
    return tipo, numero, ano


def carregar_processados():
    if not ARQ_PROCESSADOS.exists():
        return set()
    with open(ARQ_PROCESSADOS, encoding="utf-8-sig", newline="") as f:
        return {linha[0] for linha in csv.reader(f, delimiter=";") if linha}


def registrar_processado(arquivo):
    novo = not ARQ_PROCESSADOS.exists()
    with open(ARQ_PROCESSADOS, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        if novo:
            w.writerow(["arquivo", "data_hora"])
        w.writerow([str(arquivo).lower(), datetime.now().strftime("%d/%m/%Y %H:%M:%S")])


# Utilitarios de tela

def primeiro_visivel(loc, timeout=10):
    fim = time.time() + timeout
    while True:
        try:
            for i in range(loc.count()):
                el = loc.nth(i)
                if el.is_visible():
                    return el
        except Exception:
            pass
        if time.time() >= fim:
            return None
        time.sleep(0.3)


def ultimo_visivel(loc, timeout=10):
    fim = time.time() + timeout
    while True:
        try:
            visiveis = [loc.nth(i) for i in range(loc.count()) if loc.nth(i).is_visible()]
            if visiveis:
                return visiveis[-1]
        except Exception:
            pass
        if time.time() >= fim:
            return None
        time.sleep(0.3)


def botoes(escopo, texto):
    return escopo.get_by_role("button", name=texto, exact=True).or_(
        escopo.get_by_role("link", name=texto, exact=True))


def aguardar(page, segundos=1.0):
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    time.sleep(segundos)


def esperar_modal(page, timeout=8):
    return primeiro_visivel(page.locator(".modal-dialog, [role=dialog]"), timeout)


def esperar_modal_sumir(page, timeout=30):
    fim = time.time() + timeout
    while time.time() < fim:
        if primeiro_visivel(page.locator(".modal-dialog, [role=dialog]"), 0) is None:
            return
        time.sleep(0.5)


def perguntar(msg):
    return input(msg).strip().lower()


# Passos no 1Doc

def garantir_login(page):
    page.goto(URL_1DOC)
    aguardar(page)
    if primeiro_visivel(page.locator("input[type=password]"), 3):
        print("\n>>> Faca login no 1Doc na janela do navegador que abriu.")
        input(">>> Depois de entrar, volte aqui e aperte Enter... ")
        aguardar(page)


def pesquisar(page, numero, ano):
    page.goto(URL_1DOC)
    aguardar(page)
    termo = f"{numero}/{ano}"

    lupa = primeiro_visivel(page.locator(
        "a:has(.fa-search), button:has(.fa-search), "
        "a:has(.glyphicon-search), button:has(.glyphicon-search)"), 5)
    if lupa:
        lupa.click()
        time.sleep(0.8)

    campo = primeiro_visivel(page.locator(
        "input[type=search], input[placeholder*='usca' i], input[placeholder*='esquis' i], "
        "input[name*='busca' i], input[name*='search' i], input[name*='q' i]"), 5)

    if campo:
        campo.fill(termo)
        campo.press("Enter")
    else:
        print(f"\n>>> Nao achei o campo de pesquisa. Pesquise {termo} manualmente no navegador.")
        input(">>> Quando a lista de resultados aparecer, aperte Enter aqui... ")
    aguardar(page, 1.5)


def ja_esta_no_documento(page):
    return (primeiro_visivel(botoes(page, "Reabrir"), 0) is not None or
            primeiro_visivel(botoes(page, "Encaminhar"), 0) is not None)


def abrir_resultado(page, nomes_tipo, numero, ano):
    num_ponto = f"{numero:,}".replace(",", ".")
    padrao = re.compile(rf"(?<![\d.])(?:{re.escape(num_ponto)}|{numero})\s*/\s*{ano}\b")
    tipos_norm = [normalizar(n) for n in nomes_tipo]

    candidatos = {}
    links = page.locator("a")
    for i in range(links.count()):
        a = links.nth(i)
        try:
            if not a.is_visible():
                continue
            txt = a.inner_text()
            if not padrao.search(txt):
                continue
            linha = a.locator("xpath=ancestor::tr[1]")
            contexto = linha.inner_text() if linha.count() else txt
            if any(t in normalizar(contexto) for t in tipos_norm):
                href = a.get_attribute("href") or f"link{i}"
                candidatos.setdefault(href, a)
        except Exception:
            continue

    if len(candidatos) == 1:
        list(candidatos.values())[0].click()
        aguardar(page, 1.5)
        return
    if len(candidatos) > 1:
        raise Pendencia(f"Mais de um resultado do tipo certo para {numero}/{ano}")
    if ja_esta_no_documento(page):
        return
    raise Pendencia(f"Processo {numero}/{ano} do tipo certo nao encontrado na busca")


def reabrir_se_arquivado(page):
    botao = primeiro_visivel(botoes(page, "Reabrir"), 3)
    if not botao:
        return False
    botao.scroll_into_view_if_needed()
    botao.click()

    modal = esperar_modal(page, 5)
    if modal is None:
        enviar = ultimo_visivel(botoes(page, "Reabrir"), 5)
        if enviar:
            enviar.click()
        modal = esperar_modal(page, 8)
    if modal is None:
        raise Pendencia("Janela de confirmacao do Reabrir nao apareceu")

    confirmar = primeiro_visivel(botoes(modal, "Reabrir"), 5)
    if not confirmar:
        raise Pendencia("Botao de confirmar Reabrir nao encontrado")
    confirmar.click()
    esperar_modal_sumir(page)
    aguardar(page, 2)
    return True


def select_de_acao(page):
    selects = page.locator("select")
    for i in range(selects.count()):
        s = selects.nth(i)
        try:
            if not s.is_visible():
                continue
            for op in s.locator("option").all():
                if normalizar(op.inner_text()) == "encaminhar":
                    return s, op.get_attribute("value")
        except Exception:
            continue
    return None, None


def abrir_formulario_encaminhar(page):
    sel, valor = select_de_acao(page)
    if sel is None:
        b = primeiro_visivel(botoes(page, "Encaminhar"), 10)
        if not b:
            raise Pendencia("Botao Encaminhar nao encontrado")
        b.scroll_into_view_if_needed()
        b.click()
        aguardar(page, 1.5)
        sel, valor = select_de_acao(page)
    if sel is not None:
        sel.select_option(value=valor)
        time.sleep(1)


def escolher_unidade(page):
    rotulo = primeiro_visivel(page.get_by_text(re.compile(r"^\s*Para:\s*$")), 10)
    if not rotulo:
        raise Pendencia("Campo 'Para:' nao encontrado")

    caixa = primeiro_visivel(rotulo.locator(
        "xpath=following::*[contains(@class,'select2-selection') or contains(@class,'select2-choice') "
        "or contains(@class,'chosen-single') or contains(@class,'selectize-input')][1]"), 2)
    if caixa:
        caixa.click()
    else:
        box = rotulo.bounding_box()
        page.mouse.click(box["x"] + 60, box["y"] + box["height"] + 18)
    time.sleep(0.8)

    page.keyboard.type(BUSCA_UNIDADE, delay=60)
    opcao = primeiro_visivel(page.locator(
        ".select2-results li, .chosen-results li, [role=option], .selectize-dropdown .option"
    ).filter(has_text=OPCAO_UNIDADE), 10)
    if not opcao:
        raise Pendencia(f"Unidade '{OPCAO_UNIDADE}' nao apareceu na lista")
    opcao.click()
    time.sleep(0.8)


def escrever_mensagem(page, texto):
    editor = primeiro_visivel(page.locator("[contenteditable=true]"), 5)
    if editor is None:
        iframe = primeiro_visivel(page.locator("iframe"), 5)
        if iframe is None:
            raise Pendencia("Editor de mensagem nao encontrado")
        editor = iframe.content_frame().locator("body")

    if "segue comprovante de pagamento" in normalizar(editor.inner_text()):
        return  # texto ja existe (rascunho salvo)

    editor.click()
    page.keyboard.press("Control+Home")
    for i, linha in enumerate(texto.split("\n")):
        if i:
            page.keyboard.press("Enter")
        page.keyboard.type(linha, delay=15)
    page.keyboard.press("Enter")


def marcar_opcao(page, texto):
    padrao = re.compile(rf"^\s*{re.escape(texto)}\s*$")
    for _ in range(20):
        cb = page.get_by_label(padrao)
        try:
            if cb.count():
                alvo = cb.first
                if not alvo.is_checked():
                    alvo.check(force=True)
                if alvo.is_checked():
                    return
        except Exception:
            pass
        rotulo = primeiro_visivel(page.locator("label").filter(has_text=padrao), 0)
        if rotulo:
            caixa = rotulo.locator("input[type=checkbox]")
            if caixa.count() and caixa.first.is_checked():
                return
            rotulo.click()
            time.sleep(0.5)
            if caixa.count() and caixa.first.is_checked():
                return
        time.sleep(0.5)
    raise Pendencia(f"Nao consegui marcar a opcao '{texto}'")


def anexar(page, arquivo):
    botao = primeiro_visivel(botoes(page, "Anexar"), 10)
    if not botao:
        raise Pendencia("Botao Anexar nao encontrado")

    chave = so_letras_numeros(arquivo.stem)
    antes = so_letras_numeros(page.inner_text("body")).count(chave)

    with page.expect_file_chooser(timeout=15000) as escolha:
        botao.click()
    escolha.value.set_files(str(arquivo))

    fim = time.time() + ESPERA_UPLOAD_SEG
    while time.time() < fim:
        if so_letras_numeros(page.inner_text("body")).count(chave) > antes:
            aguardar(page, 2)
            return
        time.sleep(1)
    raise Pendencia("O anexo nao apareceu no formulario dentro do tempo limite")


def enviar_e_confirmar(page, nomes_tipo, descricao):
    enviar = ultimo_visivel(botoes(page, "Encaminhar"), 10)
    if not enviar:
        raise Pendencia("Botao final Encaminhar nao encontrado")
    enviar.scroll_into_view_if_needed()
    enviar.click()

    modal = esperar_modal(page, 10)
    if modal is None:
        raise Pendencia("Janela 'Confirma?' do encaminhamento nao apareceu")

    titulo = normalizar(modal.inner_text())
    if not any(normalizar(n) in titulo for n in nomes_tipo):
        cancelar = primeiro_visivel(botoes(modal, "Cancelar"), 3)
        if cancelar:
            cancelar.click()
        raise Pendencia("O tipo na janela de confirmacao nao bate com o nome do arquivo")

    if MODO_CONFERENCIA:
        print(f"\n>>> Tudo preenchido para: {descricao}")
        print(">>> Confira no navegador (unidade, texto, opcoes marcadas e anexo).")
        resp = perguntar(">>> Confirmar o encaminhamento? [s = sim / n = nao]: ")
        if resp != "s":
            cancelar = primeiro_visivel(botoes(modal, "Cancelar"), 3)
            if cancelar:
                cancelar.click()
            raise Pendencia("Encaminhamento cancelado na conferencia")

    confirmar = primeiro_visivel(botoes(modal, "Encaminhar"), 5)
    if not confirmar:
        raise Pendencia("Botao de confirmar Encaminhar nao encontrado")
    confirmar.click()
    esperar_modal_sumir(page)
    aguardar(page, 2)


def processar_arquivo(page, arquivo, tipo, numero, ano):
    nomes_tipo = TIPOS[tipo]
    pesquisar(page, numero, ano)
    abrir_resultado(page, nomes_tipo, numero, ano)
    reaberto = reabrir_se_arquivado(page)
    abrir_formulario_encaminhar(page)
    escolher_unidade(page)
    escrever_mensagem(page, TEXTO_MENSAGEM.format(saudacao=saudacao()))
    marcar_opcao(page, "Arquivar")
    marcar_opcao(page, "Arquivar + Parar de acompanhar")
    anexar(page, arquivo)
    enviar_e_confirmar(page, nomes_tipo, arquivo.name)
    return reaberto


# Programa principal

def main():
    if len(sys.argv) > 1:
        ref = datetime.strptime(sys.argv[1], "%d/%m/%Y").date()
    else:
        ref = data_referencia()

    print(f"Data de referencia: {ref.strftime('%d/%m/%Y')}")
    pasta = achar_pasta_do_dia(ref)
    if not pasta:
        print("Nenhuma pasta encontrada para essa data. Nada a processar.")
        return
    print(f"Pasta: {pasta}")

    arquivos = sorted(p for p in pasta.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
    if not arquivos:
        print("A pasta nao tem PDFs. Nada a processar.")
        return

    PASTA_ERROS.mkdir(parents=True, exist_ok=True)
    processados = carregar_processados()
    resultados = []

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(PERFIL_NAVEGADOR), channel="msedge", headless=False, no_viewport=True,
            args=["--start-maximized"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        garantir_login(page)

        for n, arq in enumerate(arquivos, 1):
            print(f"\n[{n}/{len(arquivos)}] {arq.name}")
            info = interpretar_nome(arq)
            linha = {"arquivo": arq.name, "tipo": "", "numero": "", "ano": "",
                     "reaberto": "", "situacao": "", "detalhe": ""}

            if str(arq).lower() in processados:
                linha.update(situacao="JA PROCESSADO", detalhe="Encaminhado em execucao anterior")
                print("  ja processado antes, pulando")
                resultados.append(linha)
                continue
            if not info:
                linha.update(situacao="PENDENTE", detalhe="Nome fora do padrao")
                print("  nome fora do padrao")
                resultados.append(linha)
                continue

            tipo, numero, ano = info
            linha.update(tipo=TIPOS[tipo][0], numero=numero, ano=ano)
            try:
                reaberto = processar_arquivo(page, arq, tipo, numero, ano)
                registrar_processado(arq)
                linha.update(situacao="ENCAMINHADO", reaberto="sim" if reaberto else "nao")
                print("  encaminhado" + (" (foi reaberto antes)" if reaberto else ""))
            except Exception as e:
                situacao = "PENDENTE" if isinstance(e, Pendencia) else "ERRO"
                linha.update(situacao=situacao, detalhe=str(e).splitlines()[0][:300])
                print(f"  {situacao}: {linha['detalhe']}")
                try:
                    page.screenshot(path=str(PASTA_ERROS / f"{arq.stem}.png"), full_page=True)
                except Exception:
                    pass
            resultados.append(linha)

        ctx.close()

    carimbo = datetime.now().strftime("%Y-%m-%d_%H%M")
    rel = PASTA_RELATORIOS / f"relatorio_{ref.strftime('%Y-%m-%d')}_exec_{carimbo}.csv"
    with open(rel, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(resultados[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(resultados)

    total = {}
    for r in resultados:
        total[r["situacao"]] = total.get(r["situacao"], 0) + 1
    print("\n================ RESUMO ================")
    for k, v in sorted(total.items()):
        print(f"{k}: {v}")
    pend = [r for r in resultados if r["situacao"] in ("PENDENTE", "ERRO")]
    if pend:
        print("\nPara conferir manualmente:")
        for r in pend:
            print(f"  {r['arquivo']}: {r['detalhe']}")
    print(f"\nRelatorio salvo em: {rel}")


if __name__ == "__main__":
    main()
