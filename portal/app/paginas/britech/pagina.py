#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rentabilidade e Cotas (Streamlit)

Duas abas sobre as mesmas carteiras:
  - Conferência de Rentabilidade: o PL final bate com a rentabilidade da cota? Quando não bate, de onde vem a
    diferença (aplicações e resgates de cotas). O passo a passo abre em um pop-up.
  - Monitor de Cotas: o retorno diário da cota está Acima, Abaixo ou Dentro do normal da carteira (banda de média
    ± desvios com peso exponencial, em 4 janelas)? Gráfico por carteira em pop-up e Excel com gráficos.

Como usar:
    streamlit run app.py
    Em "Buscar carteiras na API", escolha os IDs e o período e clique em "Buscar na API": o app baixa os dados
    (mesma busca do teste.py), incluindo o histórico de cotas do monitor (por padrão, 2 anos). Também dá para rodar
    `python teste.py` e só abrir o app.

A busca na API fica no teste.py, a conferência no converter.py, o monitor no monitor.py (a mesma lógica gera o Excel e
este app). O visual (cores, cartões, tabelas) fica no tema.py, no padrão da Mesa de Boletas.
"""

import io
from datetime import date, datetime, timedelta
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from app.ambiente.config_ambiente import obterDiretorioDados
from app.api import api_britech as tb  # busca na API Britech
from app.database.carteiras import listarIdsCarteiras
from app.database.historico_cotas import dataAtualizacaoHistorico, existeHistorico, lerHistorico, versaoHistorico
from app.paginas.britech import converter as cv
from app.paginas.britech import monitor as mon  # monitor de cotas: Acima/Abaixo/Dentro da banda
from app.utilitarias.componentes import seletorIds
from app.utilitarias.tema import topo  # cabeçalho padrão do portal
from app.paginas.britech.tema_britech import (COR, aplicarTema, avisoHtml, badge, esc, estilizarAltair, kpisHtml,
                                              passosHtml, tabelaHtml)

PASTA = obterDiretorioDados("britech")
ARQUIVO_PADRAO = PASTA / cv.ARQUIVO_PADRAO
CHAVE_ARQUIVO, CHAVE_EXTRATOS = "arquivo_api", "pasta_extratos"

# set_page_config fica no portal (home.py)
aplicarTema()

# Como cada status aparece: cor do KPI/aviso, cor do selo, ícone (o ícone garante que a cor não é a única pista) e
# o nome usado no CSS do cartão.
STATUS_UI = {
    cv.STATUS_OK: {"cls": "ok", "selo": "ok", "icone": "✓", "slug": "ok"},
    cv.STATUS_EXPLICADA: {"cls": "alerta", "selo": "warn", "icone": "⇄", "slug": "explicada"},
    cv.STATUS_DIVERGENTE: {"cls": "div", "selo": "div", "icone": "✕", "slug": "div"},
}
SEVERIDADE = {cv.STATUS_DIVERGENTE: 0, cv.STATUS_EXPLICADA: 1, cv.STATUS_OK: 2}


def selo(status):
    ui = STATUS_UI[status]
    return badge(ui["selo"], f"{ui['icone']} {status}")


# ----------------------------------------------------------------------------
# Dados
# ----------------------------------------------------------------------------
def versaoCodigo():
    """Data do converter.py: se a lógica mudar, o cache é refeito."""
    return Path(cv.__file__).stat().st_mtime


@st.cache_data(show_spinner="Analisando as carteiras…")
def carregar(caminho, mtime, extratos, codigo):
    """mtime e codigo entram na chave do cache: arquivo novo ou lógica nova recarregam os dados sozinhos."""
    return cv.analisarTodas(caminho, pasta_extratos=extratos)


@st.cache_data(show_spinner=False)
def excelBytes(caminho, mtime, extratos, codigo):
    analises, _ = carregar(caminho, mtime, extratos, codigo)
    mem_arquivo = io.BytesIO()
    cv.salvarExcelMulti(analises, mem_arquivo)
    return mem_arquivo.getvalue()


# ----------------------------------------------------------------------------
# Formatação
# ----------------------------------------------------------------------------
def fmtNum(numero, casas=2):
    if numero is None or pd.isna(numero):
        return "—"
    return f"{numero:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmtValor(valor, tipo):
    if valor is None:
        return "—"
    return {"brl": cv.fmtBrl, "pct": cv.fmtPct, "qtd": lambda numero: fmtNum(numero, 4),
            "cota": lambda numero: fmtNum(numero, 8), "txt": str}[tipo](valor)


def txtBrl(valor):
    return esc(cv.fmtBrl(valor))


def txtNum(casas=2):
    return lambda numero: esc(fmtNum(numero, casas))


DICAS_COMPARATIVA = {
    "Carteira": "ID da carteira no Britech.",
    "Nome": "Nome do cliente ou fundo, lido do cabeçalho do extrato de conta corrente.",
    "Status": (f"Sem divergência: a diferença é de até R$ {cv.TOLERANCIA_REAIS:.2f} (arredondamento). "
               f"Explicada por cotistas: há aplicação ou resgate de cotas e o resíduo é de até "
               f"{cv.TOLERANCIA_EXPLICADA_PCT * 100:.2f}% do PL inicial. Divergente: o resto, ou seja, sobra diferença sem explicação."),
    "PL inicial": "Valor da carteira no dia-base (soma do valor final dos ativos nesse dia).",
    "PL final real": "Valor da carteira no último dia do período (soma do valor final dos ativos nesse dia).",
    "Esperado pela cota": "PL inicial × (1 + rentabilidade da cota). É o PL que a carteira teria se só houvesse rentabilidade, "
                          "sem aplicação nem resgate de cotas.",
    "Diferença": "PL final real − Esperado pela cota. Negativo: saiu dinheiro da carteira por fora da rentabilidade. "
                 "Positivo: entrou dinheiro.",
    "Efeito dos cotistas": "Cotas aplicadas ou resgatadas no período × cota do último dia, em R$. Negativo: resgates. "
                           "Fica vazio se o histórico de cotas não foi baixado.",
    "Resíduo": "Diferença − Efeito dos cotistas: o que sobra sem explicação. Perto de zero: a diferença vem dos cotistas.",
}


def resumoCurto(analise):
    resumo, cot = analise["resumo"], analise["cot"]
    dif = resumo["dif_pl"]
    if analise["status"] == cv.STATUS_OK:
        return f"A cota explica o PL (diferença de {cv.fmtBrl(dif)})."
    verbo = "saíram" if dif < 0 else "entraram"
    if analise["status"] == cv.STATUS_EXPLICADA:
        return f"{cv.fmtBrl(abs(dif))} {verbo} por movimentação de cotas ({cot['n_operacoes']} operações)."
    return f"Diferença de {cv.fmtBrl(dif)} sem explicação nos dados disponíveis."


def html(texto):
    st.markdown(texto, unsafe_allow_html=True)


def graficoEvolucao(historico, coluna, titulo, datas_ops):
    """Linha diária com eixo ajustado (sem forçar zero) e marcas nos dias de aplicação/resgate."""
    dados = historico[["Data", coluna]].rename(columns={coluna: titulo})
    linha = alt.Chart(dados).mark_line(point=alt.OverlayMarkDef(filled=True, size=45, color=COR["vinho"]),
                                       color=COR["vinho"], strokeWidth=2.5).encode(
        x=alt.X("Data:T", title=None, axis=alt.Axis(format="%d/%m", labelAngle=0)),
        y=alt.Y(f"{titulo}:Q", title=None, scale=alt.Scale(zero=False), axis=alt.Axis(format=",.0f")),
        tooltip=[alt.Tooltip("Data:T", title="Data", format="%d/%m/%Y"), alt.Tooltip(f"{titulo}:Q", title=titulo, format=",.2f")])
    regras = alt.Chart(datas_ops).mark_rule(strokeDash=[4, 4], color=COR["dourado"], strokeWidth=2).encode(x="Data:T")
    return estilizarAltair((linha + regras).properties(height=210))


def rankingContribuicao(analise, quantos=5):
    """Maiores altas e baixas da carteira. Contribuição = rendimento do ativo ÷ PL inicial total (em p.p.)."""
    cdf = analise["contribuicoes"]
    html('<div class="rotulo">Quem mais contribuiu para a rentabilidade</div>')
    if cdf.empty:
        html(avisoHtml("alerta", "Nenhum ativo com rendimento no período."))
        return

    ordem = st.segmented_control("Ordenar por", ["Contribuição (bps)", "% do ativo"], default="Contribuição (bps)",
                                 key=f"ord_{analise['id']}", label_visibility="collapsed") or "Contribuição (bps)"
    col = "% Rent" if ordem == "% do ativo" else "Contribuição"
    maximo = float(cdf["Contribuição"].abs().max())
    pl_total = analise["resumo"]["pl_inicial"]

    # Deixa explícito o que cada opção significa
    if col == "Contribuição":
        html(avisoHtml("", "Ranking pelo quanto cada ativo puxou a rentabilidade da carteira: rendimento do ativo ÷ PL inicial "
                            "da carteira. Considera o tamanho da posição, e a soma de todos os ativos fecha com a rentabilidade "
                            "dos ativos.", "Ordenado por contribuição (bps):"))
    else:
        html(avisoHtml("alerta", "Ranking pela rentabilidade do próprio ativo: rendimento ÷ PL inicial do ativo. NÃO considera o "
                                  "tamanho da posição: um ativo pequeno pode aparecer no topo e ter pesado pouco na carteira "
                                  "(veja a coluna 'Peso na carteira'). Para o peso real no resultado, use a contribuição em bps.",
                        "Ordenado por % do ativo:"))

    def contrib(contribuicao):
        cls = "pos" if contribuicao > 0 else "neg"
        largura = min(100.0, abs(contribuicao) / maximo * 100) * 0.6 if maximo else 0
        return (f'<span class="{cls}">{esc(f"{contribuicao * 10000:+.2f}".replace(".", ","))} bps</span>'
                f'<span class="barra {cls}" style="width:{largura:.0f}px"></span>')

    def pctAtivo(rentabilidade):
        return f'<span class="{"pos" if rentabilidade > 0 else "neg"}">{esc(cv.fmtPct(rentabilidade, 2))}</span>'

    def tabela(df):
        vis = df[["Ativo", "Contribuição", "Rendimento", "% Rent"]].copy()
        vis["Peso na carteira"] = df["PL Inicial"] / pl_total if pl_total else 0.0
        vis = vis.rename(columns={"Contribuição": "Contribuição (bps)", "Rendimento": "Rendimento (R$)", "% Rent": "% do ativo"})
        vis = vis[["Ativo", "Peso na carteira", "% do ativo", "Contribuição (bps)", "Rendimento (R$)"]]
        fm = {"Ativo": lambda valor: f'<span class="trunc" title="{esc(valor)}">{esc(valor)}</span>',
              "Peso na carteira": lambda valor: esc(cv.fmtPct(valor, 2)), "% do ativo": pctAtivo,
              "Contribuição (bps)": contrib, "Rendimento (R$)": txtBrl}
        return tabelaHtml(vis, numericas={"Peso na carteira", "% do ativo", "Contribuição (bps)", "Rendimento (R$)"},
                           formatos=fm, altura=320)

    altas = cdf[cdf[col] > 0].sort_values(col, ascending=False).head(quantos)
    baixas = cdf[cdf[col] < 0].sort_values(col).head(quantos)
    # Uma tabela sobre a outra: lado a lado ficam apertadas dentro do pop-up
    html('<div class="rank-titulo pos">▲ Maiores altas</div>')
    html(tabela(altas) if len(altas) else '<div class="nota-tabela">Nenhum ativo com alta.</div>')
    html('<div class="rank-titulo neg">▼ Maiores baixas</div>')
    html(tabela(baixas) if len(baixas) else '<div class="nota-tabela">Nenhum ativo com baixa.</div>')
    soma_bps = f'{analise["resumo"]["simples"] * 10000:.2f}'.replace(".", ",")
    html(f'<div class="nota-tabela">Contribuição = rendimento do ativo ÷ PL inicial da carteira ({cv.fmtBrl(analise["resumo"]["pl_inicial"])}), '
         f'em bps (1 bps = 0,01%). A soma de todos os ativos é {soma_bps} bps ({esc(cv.fmtPct(analise["resumo"]["simples"]))}), '
         f'a rentabilidade dos ativos. Um ativo pequeno pode ter % alto e contribuir pouco.</div>')

    with st.expander("Da soma dos ativos até a cota: caixa, despesas e outros"):
        etapas = pd.DataFrame(cv.degrausContribuicao(analise), columns=["Etapa", "Tipo", "R$", "frac"])
        etapas["bps"] = etapas["frac"] * 10000
        etapas = etapas[["Etapa", "R$", "bps"]].rename(columns={"R$": "Valor (R$)", "bps": "Contribuição (bps)"})
        sinal = lambda valor: f'<span class="{"pos" if valor > 0 else "neg" if valor < 0 else ""}">{esc(f"{valor:+.2f}".replace(".", ","))}</span>'
        html(tabelaHtml(etapas, numericas={"Valor (R$)", "Contribuição (bps)"},
                         formatos={"Etapa": lambda valor: esc(valor), "Valor (R$)": txtBrl, "Contribuição (bps)": sinal}, altura=360))
        html('<div class="nota-tabela">A soma das contribuições é a rentabilidade simples dos ativos. A diferença de ponderação '
             'surge quando o PL varia no período (resgates/aplicações): o rendimento de cada dia pesa sobre o PL daquele dia, '
             'não sobre o PL inicial. O valor em R$ dessa linha é só bps × PL inicial, não um valor de caixa. Despesas, provisões e outros levam o resultado até a cota. '
             'Esta seção também sai na aba Contribuicoes do Excel.</div>')


# ----------------------------------------------------------------------------
# Pop-up com o passo a passo
# ----------------------------------------------------------------------------
@st.dialog("Passo a passo da conferência", width="large")
def detalhe(analise):
    resumo, cot, ui = analise["resumo"], analise["cot"], STATUS_UI[analise["status"]]
    ini, fim = analise["ativos"].attrs["inicio"], analise["ativos"].attrs["fim"]
    html(f'<div class="dlg-nome">{esc(analise["nome"])}</div>'
         f'<div class="dlg-meta">Carteira {esc(analise["id"])} · período {ini:%d/%m/%Y} a {fim:%d/%m/%Y}</div>'
         f'{selo(analise["status"])}<div style="height:.7rem"></div>')
    html(avisoHtml(ui["cls"], analise["mensagem"]))

    explicado = analise["status"] != cv.STATUS_DIVERGENTE
    html(kpisHtml([
        ("div" if abs(resumo["dif_pl"]) > cv.TOLERANCIA_REAIS else "ok", "Diferença (real − esperado)", cv.fmtBrl(resumo["dif_pl"]),
         "PL real menos PL esperado pela cota", True),
        ("alerta", "Explicada pelos cotistas", cv.fmtBrl(resumo["efeito_cotas"]) if resumo["efeito_cotas"] is not None else "—",
         "aplicações e resgates de cotas", True),
        ("ok" if explicado else "div", "Resíduo (sem explicação)",
         cv.fmtBrl(resumo["residuo_cotistas"]) if resumo["residuo_cotistas"] is not None else "—", "o que sobra depois dos cotistas", True),
    ]))

    t_passos, t_cotistas, t_evolucao, t_ponte, t_ativos = st.tabs(
        ["Passo a passo", "Movimentação de cotistas", "Evolução diária", "Conferência e ponte", "Ativos"])

    with t_passos:
        html('<div class="secao-sub">Pergunta: se a carteira só tivesse rentabilidade (sem aplicar nem resgatar cotas), '
             'o PL final seria igual ao PL final real?</div>')
        html(passosHtml(analise["passos"], fmtValor))

    with t_cotistas:
        if not cot["disponivel"]:
            html(avisoHtml("alerta", "Histórico de cotas não encontrado. Rode o teste.py novamente."))
        elif cot["n_operacoes"] == 0:
            html(avisoHtml("ok", f"Nenhuma aplicação nem resgate de cotas no período. A quantidade de cotas ficou em "
                                  f"{fmtNum(cot['qtd_fim'], 4)}."))
        else:
            html(kpisHtml([
                ("ok", "Aplicações", cv.fmtBrl(cot["aplicacoes"]), "valor bruto no período", True),
                ("div", "Resgates", cv.fmtBrl(cot["resgates"]), "valor bruto no período", True),
                ("total", "Cotas no início", fmtNum(cot["qtd_ini"], 2), "dia-base", True),
                ("total", "Cotas no fim", fmtNum(cot["qtd_fim"], 2), f"variação de {fmtNum(cot['qtd_fim'] - cot['qtd_ini'], 2)}", True),
            ]))
            if cot["qtd_confere"] is False:
                html(avisoHtml("alerta", "A variação da quantidade de cotas não bate com a soma das operações."))
            ops = cot["operacoes"].copy()
            ops["Efeito"] = ops["Sinal"].map({1: "Entra", -1: "Sai", 0: "Não classificado"})
            html(tabelaHtml(
                ops.drop(columns=["Sinal"]), numericas={"Quantidade", "Valor bruto", "Valor líquido", "IR"}, altura=360,
                formatos={"Data": lambda valor: esc(f"{valor:%d/%m/%Y}"), "Quantidade": txtNum(4), "Valor bruto": txtNum(2),
                          "Valor líquido": txtNum(2), "IR": txtNum(2),
                          "Efeito": lambda valor: badge({"Entra": "ok-suave", "Sai": "div-suave"}.get(valor, "neutro"), valor)}))
            html('<div class="nota-tabela">Fonte: API Fundo/OperacaoCotistaAnalitico_PorCarteiraPeriodo.</div>')

    with t_evolucao:
        historico = cot["historico"]
        if historico is None or historico.empty:
            html(avisoHtml("alerta", "Sem histórico diário de cotas."))
        else:
            datas_ops = pd.DataFrame({"Data": pd.to_datetime(cot["operacoes"]["Data"]).drop_duplicates()})
            html('<div class="rotulo">PL de fechamento (R$)</div>')
            st.altair_chart(graficoEvolucao(historico, "PLFechamento", "PL (R$)", datas_ops), theme=None, use_container_width=True)
            html('<div class="rotulo">Quantidade de cotas</div>')
            st.altair_chart(graficoEvolucao(historico, "QuantidadeFechamento", "Cotas", datas_ops), theme=None, use_container_width=True)
            html('<div class="nota-tabela">Linhas douradas tracejadas: dias com aplicação ou resgate de cotas. Uma queda na '
                 'quantidade de cotas indica resgate. Fonte: API Fundo/BuscaHistoricoCotaDia.</div>')

    with t_ponte:
        html('<div class="rotulo">Cota × ativos</div>')
        html(kpisHtml([
            ("total", "Rentabilidade dos ativos", cv.fmtPct(resumo["simples"]), "rendimento ÷ PL inicial"),
            ("total", "Rentabilidade da cota", cv.fmtPct(resumo["carteira"]), "RentabilidadeCotaBruta"),
            ("alerta", "Diferença em R$", cv.fmtBrl(resumo["diferenca_reais"]), "(cota − ativos) × PL inicial", True),
        ]))
        if analise["ponte_cotistas"]:
            ponte = analise["ponte_cotistas"]
            html('<div class="rotulo">Ponte do PL (com movimentação de cotistas)</div>')
            linhas = [("PL inicial", ponte["pl_inicial"]), ("(+) Rendimento dos ativos", ponte["rendimento"]),
                      ("(+/−) Movimentação de cotistas", ponte["fluxo_valor"]),
                      ("(+/−) Outros efeitos (tributos, taxas, provisões, datas)", ponte["outros"]), ("= PL final", ponte["pl_final"])]
            html(tabelaHtml(pd.DataFrame(linhas, columns=["Item", "R$"]), numericas={"R$"}, altura=300,
                             formatos={"R$": txtBrl},
                             destaque=lambda lin: "linha-geral" if lin["Item"].startswith("=") else ""))
        elif analise["ponte"]:
            ponte = analise["ponte"]
            html('<div class="rotulo">De onde vem a diferença (extrato de conta corrente e provisões)</div>')
            linhas = [("Despesas e taxas do extrato", sum(lancamento["valor"] for lancamento in ponte["externos"])),
                      ("Variação das provisões", sum(provisao["delta"] for provisao in ponte["provisoes"])),
                      ("Rendas da planilha − cupom recebido em caixa", -(ponte["rendas"] - ponte["cupom_caixa"])),
                      ("Total explicado", ponte["explicado"]), ("Resíduo (deve ser ~0)", ponte["residuo"])]
            html(tabelaHtml(pd.DataFrame(linhas, columns=["Item", "R$"]), numericas={"R$"}, altura=300,
                             formatos={"R$": txtBrl},
                             destaque=lambda lin: "linha-total" if lin["Item"].startswith(("Total", "Resíduo")) else ""))
            with st.expander("Ver lançamentos do extrato"):
                extensao = pd.DataFrame([{"Data": lancamento["data"], "Descrição": lancamento["descricao"], "Valor (R$)": lancamento["valor"]} for lancamento in ponte["externos"]])
                html(tabelaHtml(extensao, numericas={"Valor (R$)"}, altura=300,
                                 formatos={"Data": lambda valor: esc(f"{valor:%d/%m/%Y}"), "Valor (R$)": txtBrl}))
        else:
            html(avisoHtml("alerta", "Ponte não gerada para esta carteira."))

    with t_ativos:
        rankingContribuicao(analise)
        html('<div class="rotulo">Todos os ativos</div>')
        lay = analise["layout"]
        formatos = {coluna: txtNum(2) for coluna in cv.VALORES}
        formatos["% Rent"] = lambda valor: esc(cv.fmtPct(valor, 2))

        def realce(lin):
            if lin["Nível"] == "Total Geral":
                return "linha-geral"
            return "linha-total" if lin["Nível"] != "Ativo" else ""

        html(tabelaHtml(lay, numericas=set(cv.VALORES) | {"% Rent"}, formatos=formatos, destaque=realce, altura=460,
                         ocultar={"Nível"}))

    if analise["avisos"]:
        with st.expander(f"Avisos ({len(analise['avisos'])})"):
            html("".join(avisoHtml("alerta", texto_aviso) for texto_aviso in analise["avisos"]))


# ----------------------------------------------------------------------------
# Fonte dos dados (fica no fim da página; o valor digitado é lido pelo session_state)
# ----------------------------------------------------------------------------
def fonteDados():
    with st.expander("Fonte dos dados", icon=":material/folder_open:"):
        c1, c2 = st.columns(2)
        c1.text_input("Arquivo da API", value=str(ARQUIVO_PADRAO), key=CHAVE_ARQUIVO, help="Gerado pela busca na API")
        c2.text_input("Pasta dos extratos", value=str(cv.EXTRATOS_PADRAO), key=CHAVE_EXTRATOS)
        st.caption("O histórico de cotas do Monitor de cotas fica no banco de dados (atualizado pela busca na API).")


# ----------------------------------------------------------------------------
# Busca na API: o usuário escolhe os IDs e o período (o mesmo que o teste.py faz)
# ----------------------------------------------------------------------------
def usarIdsCadastrados():
    st.session_state["ids_busca"] = listarIdsCarteiras()


def limparIds():
    st.session_state["ids_busca"] = []


def resumoBusca(resultado_calculo):
    """Mostra o resultado da última busca (depois que a página recarregou com os dados novos)."""
    html(avisoHtml("ok", f"{len(resultado_calculo['clientes'])} carteira(s) buscada(s) na API e os dados foram atualizados.", "Busca concluída:"))
    historico = resultado_calculo.get("historico")
    if historico and "erro" in historico:
        html(avisoHtml("alerta", f"o histórico para o Monitor de cotas não foi gravado ({historico['erro']}). A conferência foi atualizada "
                                  "normalmente.", "Atenção:"))
    elif historico and historico["sem_dados"]:
        html(avisoHtml("alerta", f"a API não devolveu histórico de cotas para: {', '.join(historico['sem_dados'])}.", "Atenção:"))
    sem = {aba: ids for aba, ids in resultado_calculo["sem_dados"].items() if ids and aba != "OpCotista"}
    for aba, ids in sem.items():
        html(avisoHtml("alerta", f"a API não devolveu '{aba}' para: {', '.join(ids)}.", "Atenção:"))
    if resultado_calculo["extratos_falhos"]:
        html(avisoHtml("alerta", f"não consegui baixar o extrato de conta corrente de: {', '.join(resultado_calculo['extratos_falhos'])}.",
                        "Atenção:"))


def secaoBusca(analises, caminho, pasta_extratos, tem_dados):
    ids_planilha = listarIdsCarteiras()
    na_tela = list(analises)
    if analises:
        atributos = next(iter(analises.values()))["ativos"].attrs
        ini_padrao, fim_padrao = atributos["inicio"].date(), atributos["fim"].date()
    else:
        ini_padrao, fim_padrao = date.fromisoformat(tb.DATA_INICIO_PADRAO), date.fromisoformat(tb.DATA_FIM_PADRAO)

    st.session_state.setdefault("ids_busca", na_tela or ids_planilha)
    opcoes = list(dict.fromkeys(ids_planilha + na_tela + list(st.session_state["ids_busca"])))

    with st.expander("Buscar carteiras na API", expanded=not tem_dados, icon=":material/cloud_download:"):
        html('<div class="secao-sub">Escolha as carteiras e o período. A busca <b>substitui</b> os dados atuais pelas carteiras '
             'escolhidas (as que não estiverem na lista saem da análise).</div>')
        c_ids, c_per = st.columns([3, 1.6])
        with c_ids:
            seletorIds("IDs das carteiras", opcoes, "ids_busca",
                       "Os IDs das carteiras cadastradas aparecem na lista. Também dá para digitar um ID novo.")
        periodo = c_per.date_input("Período (dia-base e último dia)", value=(ini_padrao, fim_padrao), format="DD/MM/YYYY",
                                   key="periodo_busca")
        com_historico = False  # o histórico do Monitor de cotas é buscado só na aba do monitor

        b1, b2, b3, _ = st.columns([1.5, 1.8, 1, 2.2])
        buscar = b1.button("Buscar na API", icon=":material/search:", key="btn_buscar", use_container_width=True,
                           disabled=not st.session_state.get("ids_busca"))
        b2.button("Usar IDs cadastrados", icon=":material/table_view:", key="btn_planilha", use_container_width=True,
                  on_click=usarIdsCadastrados, disabled=not ids_planilha,
                  help=f"Carrega os {len(ids_planilha)} ID(s) das carteiras cadastradas")
        b3.button("Limpar", icon=":material/close:", key="btn_limpar", use_container_width=True, on_click=limparIds)

        if not buscar:
            return
        ids = [str(ordem_item).strip() for ordem_item in st.session_state["ids_busca"] if str(ordem_item).strip()]
        invalidos = [ordem_item for ordem_item in ids if not ordem_item.isdigit()]
        if invalidos:
            html(avisoHtml("div", f"IDs inválidos (use só números): {', '.join(invalidos)}."))
            return
        if not (isinstance(periodo, (tuple, list)) and len(periodo) == 2):
            html(avisoHtml("div", "Escolha as duas datas do período (dia-base e último dia)."))
            return

        resultado, erro = None, None
        with st.status(f"Buscando {len(ids)} carteira(s) na API Britech…", expanded=True) as status:
            barra, andamento = st.progress(0.0), st.empty()

            def mostrar(fracao, texto):
                barra.progress(fracao)
                andamento.write(texto)

            try:
                resultado = tb.buscarDados(ids, periodo[0].isoformat(), periodo[1].isoformat(), arquivo_saida=caminho,
                                            pasta_extratos=pasta_extratos, progresso=mostrar,
                                            historico_inicio=None)
            except (ValueError, RuntimeError, PermissionError) as excecao:
                erro = str(excecao)
            except Exception as excecao:  # rede, credencial etc.: mostra em vez de quebrar a página
                erro = f"Erro inesperado na busca: {excecao}"
            status.update(label="Busca concluída" if erro is None else "A busca falhou",
                          state="complete" if erro is None else "error")
        if erro:
            html(avisoHtml("div", erro, "Não foi possível buscar:"))
        else:
            st.session_state["resultado_busca"] = resultado
            st.cache_data.clear()
            st.rerun()


# ----------------------------------------------------------------------------
# Aba: Conferência de Rentabilidade
# ----------------------------------------------------------------------------
def abaConferencia(analises, erros, caminho, pasta_extratos, erro_leitura):
    if not caminho.exists():
        html(avisoHtml("alerta", f"Ainda não há dados ({caminho.name}). Escolha as carteiras acima e clique em 'Buscar na API'.",
                        "Primeira vez:"))
        return
    if erro_leitura:
        html(avisoHtml("div", erro_leitura, "Não foi possível ler os dados."))
        return
    if not analises:
        html(avisoHtml("alerta", "Nenhuma carteira pôde ser analisada.") + "".join(
            avisoHtml("alerta", f"Carteira {ordem_item}: {texto_mensagem}") for ordem_item, texto_mensagem in erros.items()))
        return

    # Barra de ações
    a1, a2, a3, a4 = st.columns([3.2, 1.4, 1.6, 1.1], vertical_alignment="center")
    a1.markdown(f'<div class="fonte-dados">Dados de {datetime.fromtimestamp(caminho.stat().st_mtime):%d/%m/%Y %H:%M} · '
                f'{esc(caminho.name)}</div>', unsafe_allow_html=True)
    if a2.button("Recarregar dados", icon=":material/refresh:", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    a3.download_button("Baixar Excel", data=excelBytes(str(caminho), caminho.stat().st_mtime, pasta_extratos, versaoCodigo()),
                       file_name="Rentabilidade_Tratada.xlsx", icon=":material/download:", use_container_width=True,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with a4.popover("Como ler", icon=":material/help:", use_container_width=True):
        st.markdown(
            "<b>PL esperado pela cota</b> = PL inicial × (1 + cota). É o PL se a carteira só tivesse rentabilidade.<br><br>"
            f"{selo(cv.STATUS_OK)} o PL real fechou com o esperado.<br><br>"
            f"{selo(cv.STATUS_EXPLICADA)} o PL real difere, mas a diferença é igual ao efeito de aplicações e resgates de cotas.<br><br>"
            f"{selo(cv.STATUS_DIVERGENTE)} sobra diferença sem explicação nos dados disponíveis.<br><br>"
            "Clique em <b>Ver passo a passo</b> em qualquer carteira para abrir a conta completa.", unsafe_allow_html=True)

    # Indicadores
    total = len(analises)
    contagem = {status: sum(1 for analise in analises.values() if analise["status"] == status) for status in SEVERIDADE}

    def pct(quantidade):
        return f"{quantidade / total * 100:.0f}%" if total else "0%"

    html(kpisHtml([
        ("total", "Carteiras analisadas", total, "na planilha"),
        ("ok", "Sem divergência", contagem[cv.STATUS_OK], pct(contagem[cv.STATUS_OK])),
        ("alerta", "Explicadas por cotistas", contagem[cv.STATUS_EXPLICADA], pct(contagem[cv.STATUS_EXPLICADA])),
        ("div", "Divergentes", contagem[cv.STATUS_DIVERGENTE], pct(contagem[cv.STATUS_DIVERGENTE])),
    ]))

    if contagem[cv.STATUS_DIVERGENTE]:
        html(avisoHtml("div", f"{contagem[cv.STATUS_DIVERGENTE]} carteira(s) com divergência sem explicação. Elas aparecem primeiro.",
                        "Atenção:"))
    elif contagem[cv.STATUS_EXPLICADA]:
        html(avisoHtml("alerta", "Nenhuma divergência sem explicação. As diferenças encontradas vêm de movimentação de cotas.",
                        "Tudo explicado:"))
    else:
        html(avisoHtml("ok", "Todas as carteiras fecharam com a rentabilidade da cota.", "Tudo certo:"))
    for ordem_item, texto_mensagem in erros.items():
        html(avisoHtml("alerta", f"Carteira {ordem_item} não foi analisada: {texto_mensagem}"))

    # Filtros
    f1, f2 = st.columns([3, 2], vertical_alignment="center")
    with f1:
        filtro_status = st.pills("Mostrar", options=list(SEVERIDADE), selection_mode="multi", default=list(SEVERIDADE),
                                 label_visibility="collapsed", key="conf_pills")
    with f2:
        busca = st.text_input("Buscar", placeholder="Buscar por nome ou ID da carteira", label_visibility="collapsed",
                              key="conf_busca")

    itens = [analise for analise in analises.values()
             if analise["status"] in (filtro_status or [])
             and (not busca or busca.lower() in analise["nome"].lower() or busca in analise["id"])]
    itens.sort(key=lambda analise: (SEVERIDADE[analise["status"]], -abs(analise["resumo"]["dif_pl"])))

    if not itens:
        html(avisoHtml("alerta", "Nenhuma carteira com esses filtros."))

    # Cartões
    por_linha = 3
    limite = st.session_state.setdefault("limite_cards", 12)
    for ini in range(0, min(len(itens), limite), por_linha):
        cols = st.columns(por_linha)
        for col, analise in zip(cols, itens[ini:ini + por_linha]):
            resumo = analise["resumo"]
            neg = " neg" if abs(resumo["dif_pl"]) > cv.TOLERANCIA_REAIS and resumo["dif_pl"] < 0 else ""
            with col, st.container(key=f"cartCard_{STATUS_UI[analise['status']]['slug']}_{analise['id']}"):
                html(f'<div class="card-topo">{selo(analise["status"])}<span class="card-id">#{esc(analise["id"])}</span></div>'
                     f'<div class="card-nome">{esc(analise["nome"])}</div>'
                     f'<div class="kv"><span>PL final real</span><b>{esc(cv.fmtBrl(resumo["pl_final"]))}</b></div>'
                     f'<div class="kv"><span>Esperado pela cota</span><b>{esc(cv.fmtBrl(resumo["pl_final_cota"]))}</b></div>'
                     f'<div class="kv"><span>Diferença</span><b class="{neg.strip()}">{esc(cv.fmtBrl(resumo["dif_pl"]))}</b></div>'
                     f'<div class="resumo">{esc(resumoCurto(analise))}</div>')
                if st.button("Ver passo a passo", key=f"ver_{analise['id']}", icon=":material/list_alt:", use_container_width=True):
                    detalhe(analise)

    if len(itens) > limite:
        if st.button(f"Mostrar mais ({len(itens) - limite} restantes)", icon=":material/expand_more:", key="conf_mais"):
            st.session_state["limite_cards"] = limite + 12
            st.rerun()

    # Tabela comparativa
    st.write("")
    with st.expander("Ver tabela comparativa", icon=":material/table:"):
        if itens:
            tabela = pd.DataFrame([{
                "Carteira": analise["id"], "Nome": analise["nome"], "Status": analise["status"],
                "PL inicial": analise["resumo"]["pl_inicial"], "PL final real": analise["resumo"]["pl_final"],
                "Esperado pela cota": analise["resumo"]["pl_final_cota"], "Diferença": analise["resumo"]["dif_pl"],
                "Efeito dos cotistas": analise["resumo"]["efeito_cotas"], "Resíduo": analise["resumo"]["residuo_cotistas"],
            } for analise in itens])
            colunas_brl = ["PL inicial", "PL final real", "Esperado pela cota", "Diferença", "Efeito dos cotistas", "Resíduo"]
            html(tabelaHtml(tabela, numericas=set(colunas_brl), altura=420, dicas=DICAS_COMPARATIVA,
                             formatos={**{coluna: txtBrl for coluna in colunas_brl}, "Status": selo}))

        # Legenda: o que cada coluna significa
        html('<div class="rotulo">O que é cada coluna</div>')
        legenda = pd.DataFrame({"Coluna": list(DICAS_COMPARATIVA), "O que é": list(DICAS_COMPARATIVA.values())})
        html(tabelaHtml(legenda, altura=520, quebrar=True, formatos={"Coluna": lambda valor: f"<b>{esc(valor)}</b>"}))


# ----------------------------------------------------------------------------
# Aba: Monitor de cotas
# ----------------------------------------------------------------------------
# Acima/Abaixo: o retorno do dia saiu da banda de normalidade (para cima ou para baixo).
STATUS_MON = {
    mon.ACIMA: {"cls": "ok", "selo": "ok", "icone": "▲", "slug": "acima"},
    mon.ABAIXO: {"cls": "div", "selo": "div", "icone": "▼", "slug": "abaixo"},
    mon.DENTRO: {"cls": "total", "selo": "neutro", "icone": "●", "slug": "dentro"},
    mon.SEM_STATUS: {"cls": "alerta", "selo": "warn", "icone": "—", "slug": "sem"},
}
ORDEM_MON = {mon.ABAIXO: 0, mon.ACIMA: 1, mon.SEM_STATUS: 2, mon.DENTRO: 3}
NIVEL_ALERTA = {"erro": "div", "alerta": "alerta", "info": ""}
DICAS_MONITOR = {
    "Carteira": "ID da carteira no Britech.",
    "Nome": "Nome do cliente ou fundo (do extrato de conta corrente ou da conferência).",
    "Última cota": "Data da cota mais recente da carteira.",
    "Retorno": "Cota bruta de hoje ÷ cota bruta de ontem − 1, no último dia.",
    "252d": "Status do último dia com a janela de 252 dias (meia-vida de 60 dias).",
    "126d": "Status do último dia com a janela de 126 dias (meia-vida de 30 dias).",
    "63d": "Status do último dia com a janela de 63 dias (meia-vida de 15 dias).",
    "21d": "Status do último dia com a janela de 21 dias (meia-vida de 5 dias).",
    "Alertas": "Avisos sobre os dados da carteira: cota menor ou igual a zero, saltos acima de 50%, histórico curto, "
               "intervalos sem cota e cota desatualizada.",
}


def seloMon(status):
    ui = STATUS_MON[status]
    return badge(ui["selo"], f"{ui['icone']} {status}")


def pct3(valor):
    return "—" if valor is None or pd.isna(valor) else cv.fmtPct(valor, 3)


def bpsTxt(valor):
    return "—" if valor is None or pd.isna(valor) else f"{fmtNum(valor * 10000, 1)} bps"


def nomeCarteira(id_, analises, pasta_extratos):
    if id_ in analises:
        return analises[id_]["nome"]
    arquivo = Path(pasta_extratos) / f"ReportExtratoContaCorrente_{id_}.xlsx"
    return (cv.lerNomeExtrato(arquivo) if arquivo.exists() else None) or f"Carteira {id_}"


def versaoMonitor():
    """Data do monitor.py: se a lógica mudar, o cache é refeito."""
    return Path(mon.__file__).stat().st_mtime


@st.cache_data(show_spinner="Calculando o monitor…")
def carregarMonitor(versao_historico, n_desvios, piso_bps, codigo):
    """versao_historico entra na chave do cache: busca nova na API recarrega o histórico do banco."""
    base = lerHistorico()
    return mon.analisarMonitor(base, {"n_desvios": n_desvios, "piso_bps": piso_bps})


def textoMonitor(linha_resumo, info):
    if not linha_resumo["Atual"]:
        return f"Cota desatualizada: a última é de {info['ultima_data']:%d/%m/%Y}."
    if linha_resumo["Status"] == mon.ACIMA:
        return f"O retorno ficou {bpsTxt(linha_resumo['Retorno'] - linha_resumo['Lim_Sup_Hoje'])} acima do limite superior da banda."
    if linha_resumo["Status"] == mon.ABAIXO:
        return f"O retorno ficou {bpsTxt(linha_resumo['Lim_Inf_Hoje'] - linha_resumo['Retorno'])} abaixo do limite inferior da banda."
    if linha_resumo["Status"] == mon.DENTRO:
        return "Retorno dentro da banda de normalidade."
    return "Sem status nesta janela: histórico curto."


def graficoMonitor(serie, janela, meses):
    """Retornos diários (pontos), banda de normalidade e limites. Zoom e arraste com o mouse."""
    col_s, col_i, col_m = f"Status_{janela}d", f"Lim_Inf_{janela}d_Ant", f"Lim_Sup_{janela}d_Ant"
    dados = serie[["Data", "Retorno", col_s, col_i, col_m]].rename(columns={col_s: "Status", col_i: "Inferior", col_m: "Superior"})
    dados = dados.dropna(subset=["Inferior", "Superior"])
    if dados.empty:
        return None
    if meses:
        dados = dados[dados["Data"] >= dados["Data"].max() - pd.DateOffset(months=meses)]
    dados = dados.assign(Fora=dados["Status"].isin([mon.ACIMA, mon.ABAIXO]), Status=dados["Status"].fillna("Sem status"))
    eixo_x = alt.X("Data:T", title=None, axis=alt.Axis(format="%d/%m/%y", labelAngle=0))
    y_eixo = alt.Axis(format=".2%")
    banda = alt.Chart(dados).mark_area(opacity=0.14, color=COR["dourado"]).encode(
        x=eixo_x, y=alt.Y("Inferior:Q", title=None, axis=y_eixo, scale=alt.Scale(zero=False)), y2="Superior:Q")
    superior = alt.Chart(dados).mark_line(color=COR["ok"], strokeDash=[4, 3], strokeWidth=1.5).encode(x=eixo_x, y="Superior:Q")
    inferior = alt.Chart(dados).mark_line(color=COR["div"], strokeDash=[4, 3], strokeWidth=1.5).encode(x=eixo_x, y="Inferior:Q")
    pontos = alt.Chart(dados).mark_circle(opacity=0.9).encode(
        x=eixo_x, y="Retorno:Q",
        color=alt.Color("Status:N", legend=alt.Legend(orient="bottom", title=None),
                        scale=alt.Scale(domain=[mon.DENTRO, mon.ACIMA, mon.ABAIXO],
                                        range=[COR["vinho"], COR["ok"], COR["div"]])),
        size=alt.condition("datum.Fora", alt.value(80), alt.value(24)),
        tooltip=[alt.Tooltip("Data:T", title="Data", format="%d/%m/%Y"), alt.Tooltip("Retorno:Q", format=".3%"),
                 alt.Tooltip("Status:N"), alt.Tooltip("Inferior:Q", title="Limite inferior", format=".3%"),
                 alt.Tooltip("Superior:Q", title="Limite superior", format=".3%")])
    return estilizarAltair((banda + superior + inferior + pontos).properties(height=330).interactive())


@st.dialog("Monitor de cotas", width="large")
def detalheMonitor(id_, resultado_calculo, janela_inicial, nome, status_conferencia):
    serie, info = resultado_calculo["series"][id_], resultado_calculo["carteiras"][id_]
    ini, fim = info["primeira_data"], info["ultima_data"]
    html(f'<div class="dlg-nome">{esc(nome)}</div>'
         f'<div class="dlg-meta">Carteira {esc(id_)} · cotas de {ini:%d/%m/%Y} a {fim:%d/%m/%Y} ({info["n_linhas"]} dias)</div>')
    if status_conferencia:
        html(f'<div class="dlg-meta">Conferência do PL: {selo(status_conferencia)}</div>')

    janela = st.segmented_control("Janela", mon.JANELAS, default=janela_inicial, format_func=lambda ordem_aux: f"{ordem_aux} dias",
                                  key=f"mon_dlg_j_{id_}", label_visibility="collapsed") or janela_inicial
    linha_resumo = resultado_calculo["resumo"][(resultado_calculo["resumo"]["Id"] == id_) & (resultado_calculo["resumo"]["Janela"] == janela)].iloc[0]
    ui = STATUS_MON[linha_resumo["Status"]]
    html(f'{seloMon(linha_resumo["Status"])}<div style="height:.6rem"></div>')
    html(avisoHtml(ui["cls"] if ui["cls"] != "total" else "", textoMonitor(linha_resumo, info)))
    html(kpisHtml([
        ("total", "Retorno do último dia", pct3(linha_resumo["Retorno"]), f"em {fim:%d/%m/%Y}", True),
        ("div", "Limite inferior (hoje)", pct3(linha_resumo["Lim_Inf_Hoje"]), "média − banda", True),
        ("ok", "Limite superior (hoje)", pct3(linha_resumo["Lim_Sup_Hoje"]), "média + banda", True),
    ]))

    t_graf, t_dias, t_janelas, t_qual = st.tabs(["Gráfico", "Últimos dias", "Todas as janelas", "Qualidade dos dados"])

    with t_graf:
        meses = st.segmented_control("Período do gráfico", [3, 6, 12, 0], default=12, key=f"mon_dlg_m_{id_}",
                                     format_func=lambda qt_meses: "Tudo" if qt_meses == 0 else f"{qt_meses} meses",
                                     label_visibility="collapsed")
        grafico = graficoMonitor(serie, janela, 12 if meses is None else meses)
        if grafico is None:
            html(avisoHtml("alerta", "Sem banda calculada nesta janela: o histórico é curto demais."))
        else:
            st.altair_chart(grafico, theme=None, use_container_width=True)
            html('<div class="nota-tabela">Pontos: retorno diário (verde = acima, vermelho = abaixo). Faixa dourada: banda de '
                 'normalidade (média ± desvios) calculada no dia anterior. Dá para dar zoom e arrastar com o mouse.</div>')

    with t_dias:
        cols = ["Data", "Cota", "Retorno", f"Status_{janela}d", f"Lim_Inf_{janela}d_Ant", f"Lim_Sup_{janela}d_Ant"]
        stt = serie[f"Status_{janela}d"]
        n_ac, n_ab, n_de = int(stt.eq("Acima").sum()), int(stt.eq("Abaixo").sum()), int(stt.eq("Dentro").sum())
        html(f'<div class="nota-tabela">No histórico carregado ({serie["Data"].min():%d/%m/%Y} a {serie["Data"].max():%d/%m/%Y}), '
             f'janela de {janela} dias: <b>{n_ac}</b> dias Acima, <b>{n_ab}</b> Abaixo e <b>{n_de}</b> Dentro.</div>')
        filtro = st.segmented_control("Mostrar", ["Últimos 15 dias", "Acima", "Abaixo", "Dentro"], default="Últimos 15 dias",
                                      key=f"mon_dlg_f_{id_}", label_visibility="collapsed") or "Últimos 15 dias"
        base = serie[cols] if filtro == "Últimos 15 dias" else serie.loc[stt.eq(filtro), cols]
        if filtro == "Últimos 15 dias":
            base = base.tail(15)
        ult = base.iloc[::-1].rename(columns={
            f"Status_{janela}d": "Status", f"Lim_Inf_{janela}d_Ant": "Limite inferior", f"Lim_Sup_{janela}d_Ant": "Limite superior"})
        ult["Status"] = ult["Status"].fillna(mon.SEM_STATUS)
        if ult.empty:
            html(f'<div class="nota-tabela">Nenhum dia {esc(filtro.lower())} na janela de {janela} dias.</div>')
        else:
          html(tabelaHtml(ult,numericas={"Cota", "Retorno", "Limite inferior", "Limite superior"}, altura=460,
                         formatos={"Data": lambda valor: esc(f"{valor:%d/%m/%Y}"), "Cota": txtNum(6), "Retorno": lambda valor: esc(pct3(valor)),
                                   "Limite inferior": lambda valor: esc(pct3(valor)), "Limite superior": lambda valor: esc(pct3(valor)),
                                   "Status": lambda valor: seloMon(valor)}))
        html('<div class="nota-tabela">Os limites de cada linha são os calculados no dia anterior.</div>')

    with t_janelas:
        proximo = fim + pd.offsets.BDay(1)
        linhas = []
        for ordem_aux in mon.JANELAS:
            linha_janela = resultado_calculo["resumo"][(resultado_calculo["resumo"]["Id"] == id_) & (resultado_calculo["resumo"]["Janela"] == ordem_aux)].iloc[0]
            fora = linha_janela[mon.ACIMA] + linha_janela[mon.ABAIXO]
            linhas.append({"Janela": f"{ordem_aux} dias", "Status": linha_janela["Status"], "Retorno": linha_janela["Retorno"],
                           "Limite inferior": linha_janela["Lim_Inf_Hoje"], "Limite superior": linha_janela["Lim_Sup_Hoje"],
                           "Dias abaixo": linha_janela[mon.ABAIXO], "Dias dentro": linha_janela[mon.DENTRO], "Dias acima": linha_janela[mon.ACIMA],
                           "% fora": fora / linha_janela["Dias_Com_Status"] if linha_janela["Dias_Com_Status"] else None,
                           "Inferior p/ o próximo dia": linha_janela["Lim_Inf_Proximo"], "Superior p/ o próximo dia": linha_janela["Lim_Sup_Proximo"]})
        aba_atual = pd.DataFrame(linhas)
        fm_pct = lambda valor: esc(pct3(valor))
        html(tabelaHtml(aba_atual, numericas={coluna for coluna in aba_atual.columns if coluna not in ("Janela", "Status")}, altura=300,
                         formatos={"Status": seloMon, "Retorno": fm_pct, "Limite inferior": fm_pct, "Limite superior": fm_pct,
                                   "% fora": lambda valor: esc(cv.fmtPct(valor, 1)), "Inferior p/ o próximo dia": fm_pct,
                                   "Superior p/ o próximo dia": fm_pct}))
        html(f'<div class="nota-tabela">As colunas "p/ o próximo dia" são a banda que vale para o retorno de {proximo:%d/%m/%Y} '
             '(próximo dia útil, sem considerar feriados).</div>')

    with t_qual:
        if not info["qualidade"]:
            html(avisoHtml("ok", "Nenhum problema encontrado nos dados desta carteira."))
        for nivel, texto in info["qualidade"]:
            html(avisoHtml(NIVEL_ALERTA[nivel], texto))


def buscaMonitor(analises):
    """Busca do histórico de cotas: só roda quando o usuário clica (não acompanha a busca da conferência)."""
    ids_padrao = list(analises) or listarIdsCarteiras()
    if analises:
        fim_padrao = next(iter(analises.values()))["ativos"].attrs["fim"].date()
    else:
        fim_padrao = date.fromisoformat(tb.DATA_FIM_PADRAO)
    with st.expander("Buscar histórico de cotas na API", expanded=not existeHistorico(), icon=":material/cloud_download:"):
        html('<div class="secao-sub">O monitor precisa de muito mais histórico que a conferência. Escolha as carteiras e '
             'clique em <b>Buscar cotas</b>. Leva cerca de 1 segundo por carteira.</div>')
        st.session_state.setdefault("ids_monitor", ids_padrao)
        opcoes = list(dict.fromkeys(ids_padrao + list(st.session_state["ids_monitor"])))
        c1, c2, c3 = st.columns([3, 1.3, 1.3], vertical_alignment="bottom")
        with c1:
            seletorIds("IDs das carteiras", opcoes, "ids_monitor")
        desde = c2.date_input("Histórico desde", value=fim_padrao - timedelta(days=tb.HISTORICO_DIAS_PADRAO),
                              format="DD/MM/YYYY", key="mon_desde")
        ate = c3.date_input("Até", value=fim_padrao, format="DD/MM/YYYY", key="mon_ate")
        if not st.button("Buscar cotas", icon=":material/search:", key="btn_buscar_cotas",
                         disabled=not st.session_state.get("ids_monitor")):
            return
        ids = [str(ordem_item).strip() for ordem_item in st.session_state["ids_monitor"] if str(ordem_item).strip()]
        invalidos = [ordem_item for ordem_item in ids if not ordem_item.isdigit()]
        if invalidos:
            html(avisoHtml("div", f"IDs inválidos (use só números): {', '.join(invalidos)}."))
            return
        if desde >= ate:
            html(avisoHtml("div", "A data inicial precisa ser anterior à data final."))
            return
        erro, resultado_calculo = None, None
        with st.status(f"Buscando cotas de {len(ids)} carteira(s)…", expanded=True) as status:
            barra, andamento = st.progress(0.0), st.empty()

            def mostrar(fracao, texto):
                barra.progress(fracao)
                andamento.write(texto)

            try:
                resultado_calculo = tb.buscarHistoricoCotas(ids, desde.isoformat(), ate.isoformat(), progresso=mostrar)
            except (ValueError, RuntimeError, PermissionError) as excecao:
                erro = str(excecao)
            except Exception as excecao:
                erro = f"Erro inesperado na busca: {excecao}"
            status.update(label="Busca concluída" if erro is None else "A busca falhou",
                          state="complete" if erro is None else "error")
        if erro:
            html(avisoHtml("div", erro, "Não foi possível buscar:"))
        else:
            st.cache_data.clear()
            st.rerun()


def abaMonitor(analises, pasta_extratos):
    buscaMonitor(analises)
    versao_historico = versaoHistorico()
    if versao_historico is None:
        html(avisoHtml("alerta", "Ainda não há histórico de cotas. Clique em 'Buscar cotas' acima.", "Monitor sem dados:"))
        return

    c1, c2, c3 = st.columns([2.4, 1.6, 1.1], vertical_alignment="center")
    janela = c1.segmented_control("Janela", mon.JANELAS, default=63, format_func=lambda ordem_aux: f"{ordem_aux} dias", key="mon_janela",
                                  label_visibility="collapsed") or 63
    with c2.popover("Parâmetros", icon=":material/tune:", use_container_width=True):
        n_desvios = st.number_input("Largura da banda (desvios-padrão)", min_value=0.5, max_value=4.0, value=1.5, step=0.1,
                                    key="mon_desvios", help="Quanto maior, menos dias saem da banda.")
        piso_bps = st.number_input("Piso do desvio (bps por dia)", min_value=0.0, max_value=10.0, value=0.5, step=0.1,
                                   key="mon_piso", help="Evita banda de largura zero em carteiras de retorno quase constante. "
                                                        "Use 0 para o cálculo sem piso.")
    with c3.popover("Como ler", icon=":material/help:", use_container_width=True):
        st.markdown(
            "O retorno de <b>hoje</b> é comparado com a banda calculada <b>ontem</b>: média ± desvios dos retornos dos dias "
            "anteriores, com mais peso para os dias recentes (EWMA).<br><br>"
            f"{seloMon(mon.ACIMA)} retorno acima do limite superior.<br><br>"
            f"{seloMon(mon.ABAIXO)} retorno abaixo do limite inferior.<br><br>"
            f"{seloMon(mon.DENTRO)} dentro da banda.<br><br>"
            f"{seloMon(mon.SEM_STATUS)} histórico curto demais para a janela, ou cota desatualizada.<br><br>"
            "As janelas (252, 126, 63 e 21 dias) mudam o quanto o passado recente pesa. "
            "Fora da banda não é erro: é um dia incomum para aquela carteira.", unsafe_allow_html=True)

    try:
        resultado_calculo = carregarMonitor(versao_historico, float(n_desvios), float(piso_bps),
                               versaoMonitor())
    except ValueError as excecao:
        html(avisoHtml("div", str(excecao), "Não foi possível ler o histórico de cotas."))
        return

    resumo = mon.resumoDaJanela(resultado_calculo, janela)
    ids = list(resumo.index)
    atual = resumo["Atual"]
    contagem = {status_banda: int(((resumo["Status"] == status_banda) & atual).sum()) for status_banda in (mon.DENTRO, mon.ACIMA, mon.ABAIXO)}
    sem_status = len(ids) - sum(contagem.values())

    html(kpisHtml([
        ("total", "Carteiras monitoradas", len(ids), f"cotas até {resultado_calculo['data_ref']:%d/%m/%Y}"),
        ("total", "Dentro da banda", contagem[mon.DENTRO], f"janela de {janela} dias"),
        ("ok", "Acima da banda", contagem[mon.ACIMA], "no último dia"),
        ("div", "Abaixo da banda", contagem[mon.ABAIXO], "no último dia"),
        ("alerta", "Sem status", sem_status, "histórico curto ou cota desatualizada"),
    ]))
    fora = contagem[mon.ACIMA] + contagem[mon.ABAIXO]
    if fora:
        html(avisoHtml("alerta", f"{fora} carteira(s) fora da banda no último dia, na janela de {janela} dias. Elas aparecem primeiro.",
                        "Atenção:"))
    elif contagem[mon.DENTRO]:
        html(avisoHtml("ok", f"Todas as carteiras com status estão dentro da banda na janela de {janela} dias.", "Tudo dentro do normal:"))
    desatualizadas = [ordem_item for ordem_item in ids if not atual[ordem_item]]
    if desatualizadas:
        html(avisoHtml("alerta", f"cota mais antiga que a data de referência ({resultado_calculo['data_ref']:%d/%m/%Y}) em: "
                                  f"{', '.join(desatualizadas)}.", "Cota desatualizada:"))
    html(f'<div class="fonte-dados">Histórico de {dataAtualizacaoHistorico():%d/%m/%Y %H:%M} · '
         f'banco de dados · banda de {resultado_calculo["params"]["n_desvios"]:g} desvio(s) · piso de {resultado_calculo["params"]["piso_bps"]:g} bps</div>')

    # Filtros
    f1, f2 = st.columns([3, 2], vertical_alignment="center")
    with f1:
        filtro = st.pills("Mostrar", options=list(ORDEM_MON), selection_mode="multi", default=list(ORDEM_MON),
                          label_visibility="collapsed", key="mon_pills")
    with f2:
        busca = st.text_input("Buscar", placeholder="Buscar por nome ou ID da carteira", label_visibility="collapsed",
                              key="mon_busca")
    nomes = {ordem_item: nomeCarteira(ordem_item, analises, pasta_extratos) for ordem_item in ids}
    itens = [ordem_item for ordem_item in ids if resumo.loc[ordem_item, "Status"] in (filtro or []) and (not busca or busca.lower() in nomes[ordem_item].lower() or busca in ordem_item)]
    itens.sort(key=lambda ordem_item: (ORDEM_MON[resumo.loc[ordem_item, "Status"]], -abs(resumo.loc[ordem_item, "Retorno"] if pd.notna(resumo.loc[ordem_item, "Retorno"]) else 0)))
    if not itens:
        html(avisoHtml("alerta", "Nenhuma carteira com esses filtros."))

    # Cartões
    por_linha = 3
    limite = st.session_state.setdefault("limite_mon", 12)
    for ini in range(0, min(len(itens), limite), por_linha):
        cols = st.columns(por_linha)
        for col, ordem_item in zip(cols, itens[ini:ini + por_linha]):
            linha_resumo, info = resumo.loc[ordem_item], resultado_calculo["carteiras"][ordem_item]
            status = linha_resumo["Status"]
            fora_n = int(linha_resumo[mon.ACIMA] + linha_resumo[mon.ABAIXO])
            fora_pct = f"{fora_n / linha_resumo['Dias_Com_Status'] * 100:.1f}%".replace(".", ",") if linha_resumo["Dias_Com_Status"] else "—"
            alertas = len(info["qualidade"])
            with col, st.container(key=f"monCard_{STATUS_MON[status]['slug']}_{ordem_item}"):
                html(f'<div class="card-topo">{seloMon(status)}<span class="card-id">#{esc(ordem_item)}</span></div>'
                     f'<div class="card-nome">{esc(nomes[ordem_item])}</div>'
                     f'<div class="kv"><span>Retorno do último dia</span><b>{esc(pct3(linha_resumo["Retorno"]))}</b></div>'
                     f'<div class="kv"><span>Banda de hoje</span><b>{esc(pct3(linha_resumo["Lim_Inf_Hoje"]))} a {esc(pct3(linha_resumo["Lim_Sup_Hoje"]))}</b></div>'
                     f'<div class="kv"><span>Dias fora da banda</span><b>{fora_pct} ({fora_n})</b></div>'
                     f'<div class="kv"><span>Última cota</span><b>{info["ultima_data"]:%d/%m/%Y}</b></div>'
                     f'<div class="resumo">{esc(textoMonitor(linha_resumo, info))}'
                     f'{f" · {alertas} alerta(s) de dados" if alertas else ""}</div>')
                if st.button("Ver gráfico", key=f"mver_{ordem_item}", icon=":material/show_chart:", use_container_width=True):
                    detalheMonitor(ordem_item, resultado_calculo, janela, nomes[ordem_item], analises[ordem_item]["status"] if ordem_item in analises else None)

    if len(itens) > limite:
        if st.button(f"Mostrar mais ({len(itens) - limite} restantes)", icon=":material/expand_more:", key="mon_mais"):
            st.session_state["limite_mon"] = limite + 12
            st.rerun()

    # Tabela com todas as janelas
    st.write("")
    with st.expander("Ver tabela com todas as janelas", icon=":material/table:"):
        linhas = []
        for ordem_item in itens:
            info = resultado_calculo["carteiras"][ordem_item]
            por_janela = {ordem_aux: resultado_calculo["resumo"][(resultado_calculo["resumo"]["Id"] == ordem_item) & (resultado_calculo["resumo"]["Janela"] == ordem_aux)].iloc[0] for ordem_aux in mon.JANELAS}
            linhas.append({"Carteira": ordem_item, "Nome": nomes[ordem_item], "Última cota": info["ultima_data"], "Retorno": por_janela[janela]["Retorno"],
                           **{f"{ordem_aux}d": por_janela[ordem_aux]["Status"] for ordem_aux in mon.JANELAS}, "Alertas": len(info["qualidade"])})
        if linhas:
            aba_atual = pd.DataFrame(linhas)
            fm = {"Última cota": lambda valor: esc(f"{valor:%d/%m/%Y}"), "Retorno": lambda valor: esc(pct3(valor))}
            fm.update({f"{ordem_aux}d": seloMon for ordem_aux in mon.JANELAS})
            html(tabelaHtml(aba_atual, numericas={"Retorno", "Alertas"}, formatos=fm, altura=420, dicas=DICAS_MONITOR))
        html('<div class="rotulo">O que é cada coluna</div>')
        legenda = pd.DataFrame({"Coluna": list(DICAS_MONITOR), "O que é": list(DICAS_MONITOR.values())})
        html(tabelaHtml(legenda, altura=520, quebrar=True, formatos={"Coluna": lambda valor: f"<b>{esc(valor)}</b>"}))

    # Excel do monitor (gerado sob demanda: os gráficos levam alguns segundos)
    st.write("")
    x1, x2, x3 = st.columns([1.6, 1.6, 3], vertical_alignment="center")
    com_graficos = x3.checkbox("Incluir gráficos no Excel", value=len(ids) <= 40, key="mon_xl_graficos",help="Um gráfico por carteira e janela (até 160 no total).")
    assinatura = (str(versao_historico), float(n_desvios), float(piso_bps), com_graficos)
    if x1.button("Gerar Excel do monitor", icon=":material/table_chart:", use_container_width=True, key="mon_xl_gerar"):
        with st.spinner("Gerando o Excel…"):
            dados, info_xl = mon.excelMonitorBytes(resultado_calculo, nomes, com_graficos)
        st.session_state["mon_xl"] = {"assinatura": assinatura, "dados": dados, "info": info_xl,"nome": f"Monitor_Cotas_{datetime.now():%d%m%Y_%H%M%S}.xlsx"}
    guardado = st.session_state.get("mon_xl")
    if guardado and guardado["assinatura"] == assinatura:
        x2.download_button("Baixar Excel do monitor", data=guardado["dados"], file_name=guardado["nome"], use_container_width=True,
icon=":material/download:", key="mon_xl_baixar",mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if guardado["info"]["omitidos"]:
            html(avisoHtml("alerta", "Muitas carteiras: os gráficos foram omitidos do Excel (o limite é de 160 gráficos)."))
    elif guardado:
        html('<div class="nota-tabela">Os dados ou parâmetros mudaram desde o último Excel: gere de novo.</div>')


# ----------------------------------------------------------------------------
# Página
# ----------------------------------------------------------------------------
arquivo = st.session_state.get(CHAVE_ARQUIVO, str(ARQUIVO_PADRAO))
pasta_extratos = st.session_state.get(CHAVE_EXTRATOS, str(cv.EXTRATOS_PADRAO))
caminho = Path(arquivo)

ANALISES, ERROS, erro_leitura = {}, {}, None
if caminho.exists():
    try:
        ANALISES, ERROS = carregar(str(caminho), caminho.stat().st_mtime, pasta_extratos, versaoCodigo())
    except ValueError as excecao:
        erro_leitura = str(excecao)

if ANALISES:
    primeiro = next(iter(ANALISES.values()))["ativos"]
    topo("Rentabilidade e Cotas",
         f"Conferência do PL com a cota ({primeiro.attrs['inicio']:%d/%m/%Y} a {primeiro.attrs['fim']:%d/%m/%Y}) "
         "e monitor da rentabilidade diária", app="rentabilidade")
else:
    topo("Rentabilidade e Cotas", "Conferência do PL com a cota e monitor da rentabilidade diária", app="rentabilidade")

ultima_busca = st.session_state.pop("resultado_busca", None)
if ultima_busca:
    resumoBusca(ultima_busca)
secaoBusca(ANALISES, caminho, pasta_extratos, tem_dados=bool(ANALISES) or existeHistorico())

tab_conferencia, tab_monitor = st.tabs(["Conferência de Rentabilidade", "Monitor de Cotas"])
with tab_conferencia:
    abaConferencia(ANALISES, ERROS, caminho, pasta_extratos, erro_leitura)
with tab_monitor:
    abaMonitor(ANALISES, pasta_extratos)

fonteDados()

