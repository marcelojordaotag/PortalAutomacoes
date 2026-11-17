import html
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from app.utilitarias import email_gmail
from app.utilitarias.tema import COR, aplicarTema, topo

from app.paginas.solicitacoes.graficos import grafico

from app.paginas.solicitacoes.comum import (
    CLASSE_STATUS, EMAIL_CC, EMAIL_PARA, PRIORIDADES, SLA_DIAS, SLA_URGENTE_DIAS, STATUS, TIPOS, URGENTE_BADGE,
    abrirEmail, canonSolicitante, carregar, carregarClientes, criarRascunhoGmail, diasEntre, evento, nomeCurto, paraDf,
    neutralizarFormulas, previsaoConclusao, salvarSolicitacao, salvarSolicitacoes, textoPrevisao,
)

aplicarTema()
topo("Registro de Solicitações", "Abertura, acompanhamento, histórico e análise das demandas ao processamento",
     app="solicitacoes")

st.markdown(
    f"""<style>
.hist-item {{ border-left: 3px solid {COR['vinho']}; padding: .15rem 0 .15rem .8rem; margin: 0 0 .55rem 0; }}
.hist-quando {{ color: {COR['texto_suave']}; font-size: .74rem; }}
.hist-evento {{ font-weight: 600; font-size: .9rem; }}
.hist-detalhe {{ color: {COR['texto_suave']}; font-size: .82rem; }}
.detalhe-box {{ background: #fff; border: 1px solid {COR['borda']}; border-radius: 12px; padding: .9rem 1.1rem; margin-bottom: .8rem; }}
.detalhe-box p {{ margin: .15rem 0; }}
.faixa-titulo {{ color: {COR['texto_suave']}; font-size: .72rem; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; margin: .4rem 0 .35rem 0; }}
</style>""",
    unsafe_allow_html=True,
)


def abrirEmailConclusao(reg, para, cc):
    """Cria no Gmail o rascunho avisando que a solicitação foi concluída (não envia)."""
    ds_texto = (
        "Olá,\n\nSua solicitação foi concluída:\n\n"
        f"CLIENTE: {reg['cliente']}\nTIPO: {reg.get('tipo', '')}\nDESCRIÇÃO: {reg.get('descricao', '')}\n"
        f"CONCLUÍDA EM: {date.fromisoformat(reg['data_conclusao']).strftime('%d/%m/%Y')}\n\n"
        f"COMO FOI RESOLVIDA:\n{reg.get('resolucao', '')}\n\nAtenciosamente,"
    )
    return criarRascunhoGmail(email_gmail.montarMimeTexto(para, f"SOLICITAÇÃO CONCLUÍDA : {nomeCurto(reg['cliente'])}", ds_texto, cc or ""))


# ---------------------------------------------------------------- estado
# Sempre do banco: pessoas de outras áreas registram solicitações em Registro Solicitações de Fechamento enquanto esta tela está aberta.
regs = carregar()
st.session_state.regs = regs
df = paraDf(regs)

aba_concluir, aba_painel, aba_lista = st.tabs(["Concluir solicitação", "Painel", "Solicitações e histórico"])

# ---------------------------------------------------------------- PAINEL
def kpi(nm_rotulo, valor, sub="", classe="", fonte=""):
    estilo = f' style="font-size:{fonte};line-height:1.4"' if fonte else ""
    return (f'<div class="kpi {classe}"><div class="kpi-label">{nm_rotulo}</div>'
            f'<div class="kpi-valor"{estilo}>{valor}</div><div class="kpi-sub">{sub}</div></div>')


def faixaKpis(titulo, itens):
    st.markdown(f'<p class="faixa-titulo">{titulo}</p><div class="kpis">{"".join(itens)}</div>', unsafe_allow_html=True)


def pct(parte, total):
    return f"{parte / total * 100:.0f}%" if total else "–"


COR_STATUS = {"Em aberto": COR["div"], "Em Processamento": COR["alerta"], "Concluído": COR["ok"]}
ORDEM_FAIXAS_DIAS = ["Mesmo dia", "1 dia", "2 a 3 dias", "4 a 7 dias", "8 a 15 dias", "16 dias ou mais"]
ORDEM_IDADE = ["0 a 2 dias", "3 a 5 dias", "6 a 10 dias", "11 a 20 dias", "Mais de 20 dias"]
DIAS_SEMANA = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

with aba_painel:
    if df.empty:
        st.info("Ainda não há solicitações. As novas são abertas em **Registro Solicitações de Fechamento**; para importar a planilha antiga, "
                "rode na pasta do portal `python -m app.paginas.solicitacoes.importar_planilha <arquivo.xlsm>`.")
    else:
        meses = sorted(df["Mês"].unique())
        p1, p2, p3 = st.columns([1, 1, 2])
        escolha = p1.selectbox("Período", ["Todos"] + meses[::-1])
        base = df if escolha == "Todos" else df[df["Mês"] == escolha]
        tipos_sel = p2.multiselect("Tipo", TIPOS, placeholder="Todos os tipos")
        if tipos_sel:
            base = base[base["Tipo"].isin(tipos_sel)]

        if base.empty:
            st.info("Nenhuma solicitação com esse filtro.")
        else:
            abertas = base[base["Status"] != "Concluído"]
            concl = base[base["Status"] == "Concluído"]
            tempo = concl["Dias p/ concluir"].dropna()
            atrasadas = int(base["Atrasada"].sum())
            urgentes = int(((base["Prioridade"] == "Urgente") & (base["Status"] != "Concluído")).sum())

            # ---- indicadores
            no_prazo = concl["No prazo"].dropna().astype(bool)
            mes_atual = date.today().strftime("%Y-%m")
            mes_ant = (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
            do_mes = int((df["Mês"] == mes_atual).sum())
            do_mes_ant = int((df["Mês"] == mes_ant).sum())
            variacao = (f"{(do_mes - do_mes_ant):+d} vs {mes_ant[5:]}/{mes_ant[:4]}" if do_mes_ant or do_mes else "")
            top_cli = base["Cliente"].value_counts()
            top_tipo = base["Tipo"].value_counts()
            por_cliente = base.groupby("Cliente").size()
            reinc = por_cliente[por_cliente >= 2]
            abertas_7 = int((base["Data_dt"] >= pd.Timestamp(date.today() - timedelta(days=7))).sum())
            sla_pct = f"{no_prazo.mean() * 100:.0f}%" if len(no_prazo) else "–"
            sla_cls = "" if not len(no_prazo) else ("ok" if no_prazo.mean() >= .8 else "div")

            faixaKpis("Situação agora", [
                kpi("Solicitações", len(base), f"{abertas_7} nos últimos 7 dias"),
                kpi("Não concluídas", len(abertas), "em aberto + em processamento", "vazio"),
                kpi("Atrasadas", atrasadas, "fora do prazo (SLA)", "div" if atrasadas else "ok"),
                kpi("Urgentes em aberto", urgentes,
                    f"prazo de {SLA_URGENTE_DIAS} dia · {pct(int((base['Prioridade'] == 'Urgente').sum()), len(base))} do total são urgentes",
                    "div" if urgentes else "ok"),
            ])
            faixaKpis("Desempenho", [
                kpi("Tempo médio", f"{tempo.mean():.1f}" if len(tempo) else "–",
                    f"dias · mediana {tempo.median():.0f} · máx {tempo.max():.0f}" if len(tempo) else "dias até concluir"),
                kpi("Cumprimento do SLA", sla_pct, f"{int(no_prazo.sum())} de {len(no_prazo)} concluídas no prazo", sla_cls),
                kpi("Concluídas", len(concl), f"{pct(len(concl), len(base))} do total", "ok"),
            ])
            faixaKpis("Perfil das demandas", [
                kpi("Cliente com mais solicitações", nomeCurto(top_cli.index[0]), f"{int(top_cli.iloc[0])} no período", fonte="1.05rem"),
                kpi("Tipo mais comum", top_tipo.index[0], f"{int(top_tipo.iloc[0])} de {len(base)}", fonte="1.25rem"),
                kpi("Clientes reincidentes", len(reinc), f"{pct(len(reinc), len(por_cliente))} dos clientes com 2+ solicitações"),
                kpi("Solicitações no mês", do_mes, f"{mes_atual[5:]}/{mes_atual[:4]} · {variacao}"),
            ])

            sub_geral, sub_prazos, sub_tempo, sub_pessoas = st.tabs(
                ["Visão geral", "Prazos e backlog", "Tempo de conclusão", "Solicitantes e c,"
                ";çpp´~lientes"])

            # ---------------- Visão geral
            with sub_geral:
                g1, g2 = st.columns([3, 2])
                with g1:
                    por_mes = base.groupby(["Mês", "Status"]).size().reset_index(name="Qtd")
                    grafico("bar", por_mes, "Solicitações por mês e status", x="Mês", y="Qtd", color="Status", barmode="stack",
                            color_discrete_map=COR_STATUS, category_orders={"Status": STATUS})
                with g2:
                    por_tipo = base.groupby("Tipo").size().reset_index(name="Qtd")
                    grafico("pie", por_tipo, "Por tipo de demanda", names="Tipo", values="Qtd", hole=.55,
                            color_discrete_sequence=[COR["vinho"], COR["dourado"], COR["vinho_medio"]])

                if True:
                    ab_sem = base.set_index("Data_dt").resample("W-MON", label="left", closed="left").size().rename("Abertas")
                    co = concl.dropna(subset=["Conclusão"]).copy()
                    co["Conclusão_dt"] = pd.to_datetime(co["Conclusão"])
                    if co.empty:
                        co_sem = pd.Series(dtype=int, name="Concluídas")
                    else:
                        co_sem = co.set_index("Conclusão_dt").resample("W-MON", label="left", closed="left").size().rename("Concluídas")
                    sem = pd.concat([ab_sem, co_sem], axis=1).fillna(0).astype(int).reset_index(names="Semana")
                    sem_l = sem.melt("Semana", var_name="Série", value_name="Qtd")
                    grafico("line", sem_l, "Aberturas × conclusões por semana", x="Semana", y="Qtd", color="Série", markers=True,
                            color_discrete_map={"Abertas": COR["vinho"], "Concluídas": COR["ok"]})

            # ---------------- Prazos e backlog
            with sub_prazos:
                b1, b2 = st.columns(2)
                with b1:
                    if len(abertas):
                        idade = pd.cut(abertas["Aberta há (dias)"].astype(float), bins=[-1, 2, 5, 10, 20, float("inf")],
                                       labels=ORDEM_IDADE).astype(str).value_counts().reindex(ORDEM_IDADE, fill_value=0)
                        idade_df = pd.DataFrame({"Idade": ORDEM_IDADE, "Qtd": idade.values})
                        grafico("bar", idade_df, "Backlog por idade (não concluídas)",
                                ajustes=[("update_traces", (), {"textposition": "outside"}), ("update_layout", (), {"showlegend": False})],
                                x="Idade", y="Qtd", text="Qtd", color="Idade",
                                color_discrete_sequence=[COR["ok"], "#8DB255", COR["alerta"], "#D2691E", COR["div"]])
                    else:
                        st.success("Nenhuma solicitação pendente.")
                with b2:
                    if len(no_prazo):
                        sla_tipo = (concl.dropna(subset=["No prazo"]).assign(ok=lambda tb_concluidas: tb_concluidas["No prazo"].astype(bool))
                                    .groupby("Tipo")["ok"].agg(["mean", "count"]).reset_index())
                        sla_tipo["Cumprimento (%)"] = (sla_tipo["mean"] * 100).round(0)
                        sla_tipo["Rótulo"] = sla_tipo.apply(lambda linha_sla: f"{linha_sla['Cumprimento (%)']:.0f}% ({int(linha_sla['count'])})", axis=1)
                        grafico("bar", sla_tipo, "Cumprimento do SLA por tipo (% · concluídas)",
                                ajustes=[("update_traces", (), {"textposition": "outside"}), ("update_yaxes", (), {"range": [0, 115]})],
                                x="Tipo", y="Cumprimento (%)", text="Rótulo", color_discrete_sequence=[COR["vinho"]])
                    else:
                        st.info("Sem concluídas para medir o cumprimento do SLA.")

                st.markdown('<p class="secao">Pendências mais antigas</p>'
                            f'<p class="secao-sub">Prazo: {", ".join(f"{chave_item} {qt_dias} d" for chave_item, qt_dias in SLA_DIAS.items())} · urgente {SLA_URGENTE_DIAS} d</p>',
                            unsafe_allow_html=True)
                antigas = abertas.assign(**{"Atraso (dias)": (abertas["Aberta há (dias)"] - abertas["Prazo (dias)"]).clip(lower=0)}) \
                    .sort_values("Aberta há (dias)", ascending=False).head(12)[
                    ["ID", "Cliente", "Solicitante", "Tipo", "Prioridade", "Status", "Aberta há (dias)", "Prazo (dias)", "Atraso (dias)"]]
                st.dataframe(antigas, hide_index=True, use_container_width=True)

            # ---------------- Tempo de conclusão
            with sub_tempo:
                if not len(tempo):
                    st.info("Ainda não há solicitações concluídas com data para calcular o tempo de conclusão.")
                else:
                    t1, t2 = st.columns(2)
                    with t1:
                        tm_mes = concl.groupby("Mês")["Dias p/ concluir"].agg(["mean", "median"]).round(1).reset_index()
                        tm_l = tm_mes.melt("Mês", var_name="Medida", value_name="Dias").replace({"mean": "Média", "median": "Mediana"})
                        grafico("bar", tm_l, "Dias para concluir por mês de abertura", ajustes=[("update_traces", (), {"textposition": "outside"})],
                                x="Mês", y="Dias", color="Medida", barmode="group", text="Dias",
                                color_discrete_map={"Média": COR["vinho"], "Mediana": COR["dourado"]})
                    with t2:
                        cc_f = concl.dropna(subset=["Dias p/ concluir"]).copy()
                        cc_f["Faixa"] = pd.cut(cc_f["Dias p/ concluir"], bins=[-1, 0, 1, 3, 7, 15, float("inf")],
                                               labels=ORDEM_FAIXAS_DIAS).astype(str)
                        dist = cc_f["Faixa"].value_counts().reindex(ORDEM_FAIXAS_DIAS, fill_value=0)
                        dist_df = pd.DataFrame({"Faixa": ORDEM_FAIXAS_DIAS, "Qtd": dist.values})
                        grafico("bar", dist_df, "Distribuição: quantas concluíram em cada faixa", ajustes=[("update_traces", (), {"textposition": "outside"})],
                                x="Faixa", y="Qtd", text="Qtd", color_discrete_sequence=[COR["vinho"]])

            # ---------------- Solicitantes e clientes
            with sub_pessoas:
                if True:
                    por_cli = base.groupby("Cliente").size().reset_index(name="Qtd").sort_values("Qtd").tail(10)
                    por_cli["Cliente"] = por_cli["Cliente"].map(nomeCurto)
                    grafico("bar", por_cli, "Clientes com mais solicitações (top 10)", ajustes=[("update_traces", (), {"textposition": "outside"})],
                            x="Qtd", y="Cliente", orientation="h", text="Qtd", color_discrete_sequence=[COR["dourado"]])

                st.markdown('<p class="secao">Clientes reincidentes</p>'
                            '<p class="secao-sub">Clientes com 2 ou mais solicitações no período: bom ponto de partida para achar a causa raiz</p>',
                            unsafe_allow_html=True)
                if len(reinc):
                    aba_atual = (base[base["Cliente"].isin(reinc.index)].groupby("Cliente")
                           .agg(Solicitações=("ID", "count"), Pendentes=("Status", lambda serie_status: int((serie_status != "Concluído").sum())),
                                Última=("Data", "max"), Tipos=("Tipo", lambda serie_tipo: ", ".join(sorted(set(serie_tipo)))))
                           .reset_index().sort_values(["Solicitações", "Pendentes"], ascending=False))
                    st.dataframe(aba_atual, hide_index=True, use_container_width=True)
                else:
                    st.info("Nenhum cliente com mais de uma solicitação no período.")

# ---------------------------------------------------------------- CONCLUIR SOLICITAÇÃO
with aba_concluir:
    cv = st.session_state.get("concluir_v", 0)
    pendentes = sorted((solicitacao for solicitacao in regs if solicitacao.get("status") != "Concluído"), key=lambda solicitacao: solicitacao["id"], reverse=True)
    if "aviso_concluir" in st.session_state:
        st.success(st.session_state.pop("aviso_concluir"))
    if not pendentes:
        st.info("Nenhuma solicitação pendente.")
    else:
        rotulo_sol = lambda solicitacao: f"#{solicitacao['id']} · {solicitacao.get('data') or '–'} · {solicitacao['cliente']} · {solicitacao.get('tipo', '')} · {solicitacao.get('solicitante', '')}"
        escolhida = st.selectbox("Solicitação", pendentes, format_func=rotulo_sol, index=None,
                                 placeholder="Selecione a solicitação", key=f"conc_sel_{cv}")
        if escolhida:
            st.markdown(
                f'<div class="detalhe-box"><p><b>{html.escape(escolhida["cliente"])}</b></p>'
                f'<p>Solicitante: {html.escape(escolhida.get("solicitante", ""))} · Data: {html.escape(str(escolhida.get("data") or "–"))} · Tipo: {html.escape(escolhida.get("tipo", ""))}</p>'
                f'<p style="margin-top:.6rem">{html.escape(escolhida.get("descricao", ""))}</p></div>',
                unsafe_allow_html=True)
        resolucao = st.text_area("Como foi resolvida", height=130, key=f"conc_res_{cv}")
        data_fim = st.date_input("Data de conclusão", value=date.today(), format="DD/MM/YYYY", key=f"conc_data_{cv}")
        enviar = st.checkbox("Criar rascunho do e-mail de conclusão no Gmail", value=True, key=f"conc_mail_{cv}")
        email_para = st.text_input("E-mail para (destinatário)", value=EMAIL_PARA or "",
                                    placeholder="nome@taginvest.com.br", disabled=not enviar,
                                    key=f"conc_para_{cv}_{(escolhida or {}).get('id', 0)}")
        if enviar and escolhida:
            st.caption(f"Assunto: SOLICITAÇÃO CONCLUÍDA : {nomeCurto(escolhida['cliente'])}")
        if st.button("Marcar como concluída", type="primary", key=f"conc_btn_{cv}"):
            if not escolhida:
                st.error("Selecione a solicitação.")
            elif not resolucao.strip():
                st.error("Descreva como a solicitação foi resolvida.")
            elif enviar and not email_para.strip():
                st.error("Informe o e-mail do destinatário ou desmarque o envio.")
            else:
                reg_c = next(solicitacao for solicitacao in regs if solicitacao["id"] == escolhida["id"])
                evento(reg_c, f"Status: {reg_c['status']} → Concluído", resolucao.strip())
                reg_c["status"] = "Concluído"
                reg_c["data_conclusao"] = data_fim.isoformat()
                reg_c["resolucao"] = resolucao.strip()
                texto_mensagem = f"Solicitação #{reg_c['id']} concluída."
                if enviar:
                    reg_c["email_solicitante"] = email_para.strip()
                    ok, texto = abrirEmailConclusao(reg_c, email_para.strip(), EMAIL_CC)
                    evento(reg_c, "Rascunho de e-mail de conclusão criado" if ok else "Falha ao criar e-mail de conclusão",
                           f"Para: {email_para.strip()}" if ok else texto)
                    texto_mensagem += " " + texto
                salvarSolicitacao(reg_c)
                st.session_state.concluir_v = cv + 1
                st.session_state.aviso_concluir = texto_mensagem
                st.rerun()

# ---------------------------------------------------------------- LISTA E HISTÓRICO
with aba_lista:
    if df.empty:
        st.info("Nenhuma solicitação registrada.")
    else:
        f1, f2, f3, f4, f5 = st.columns(5)
        fs = f1.multiselect("Status", STATUS)
        ft = f2.multiselect("Tipo", TIPOS)
        fsol = f3.multiselect("Solicitante", sorted(df["Solicitante"].unique()))
        fprio = f5.multiselect("Prioridade", PRIORIDADES)
        busca = f4.text_input("Buscar (cliente ou descrição)")

        vis = df
        if fs:
            vis = vis[vis["Status"].isin(fs)]
        if ft:
            vis = vis[vis["Tipo"].isin(ft)]
        if fprio:
            vis = vis[vis["Prioridade"].isin(fprio)]
        if fsol:
            vis = vis[vis["Solicitante"].isin(fsol)]
        if busca:
            alvo = vis["Cliente"].str.cat(vis["Descrição"], sep=" ").str.lower()
            vis = vis[alvo.str.contains(busca.lower(), regex=False)]
        vis = vis.sort_values("ID", ascending=False)

        st.caption(f"{len(vis)} de {len(df)} solicitações · clique em uma linha para ver o detalhe e o histórico")
        tabela = vis[["ID", "Data", "Cliente", "Solicitante", "Tipo", "Prioridade", "Status", "Conclusão", "Dias p/ concluir", "Aberta há (dias)", "Atrasada", "Descrição"]]
        def _corLinha(linha):
            if linha["Status"] == "Concluído":
                cor = "#EAF6EE"
            elif linha["Atrasada"]:
                cor = "#FBE7E4"
            else:
                cor = ""
            return [f"background-color: {cor}" if cor else ""] * len(linha)

        selecao = st.dataframe(
            tabela.style.apply(_corLinha, axis=1), hide_index=True, use_container_width=True, height=360,
            on_select="rerun", selection_mode="single-row", key="tab_sol",
            column_config={"Atrasada": st.column_config.CheckboxColumn("Atrasada"),
                           "Descrição": st.column_config.TextColumn(width="large")},
        )
        with st.expander("Revisão em lote: dar baixa em várias de uma vez"):
            pend = df[df["Status"] != "Concluído"].sort_values("Data")[["ID", "Data", "Cliente", "Solicitante", "Tipo", "Aberta há (dias)", "Descrição"]].copy()
            if pend.empty:
                st.info("Nenhuma solicitação pendente.")
            else:
                st.caption("Marque as que já foram resolvidas, defina a data de conclusão e aplique. Cada baixa entra no histórico.")
                pend.insert(0, "Concluir", False)
                lv = st.session_state.get("lote_v", 0)
                editado = st.data_editor(
                    pend, hide_index=True, use_container_width=True, height=300, key=f"lote_{lv}",
                    disabled=[coluna_tabela for coluna_tabela in pend.columns if coluna_tabela != "Concluir"],
                    column_config={"Concluir": st.column_config.CheckboxColumn("Concluir"),
                                   "Descrição": st.column_config.TextColumn(width="large")},
                )
                marcadas = editado[editado["Concluir"]]["ID"].tolist()
                l1, l2 = st.columns([1, 2])
                data_lote = l1.date_input("Data de conclusão", value=date.today(), format="DD/MM/YYYY", key=f"dlote_{lv}")
                l2.write("")
                if l2.button(f"Concluir {len(marcadas)} selecionada(s)", disabled=not marcadas, key=f"blote_{lv}"):
                    lote_baixa = [solicitacao_lote for solicitacao_lote in regs if solicitacao_lote["id"] in marcadas]
                    for solicitacao_lote in lote_baixa:
                        evento(solicitacao_lote, f"Status: {solicitacao_lote['status']} → Concluído", "Baixa em lote")
                        solicitacao_lote["status"] = "Concluído"
                        solicitacao_lote["data_conclusao"] = data_lote.isoformat()
                    salvarSolicitacoes(lote_baixa)
                    st.session_state.lote_v = lv + 1
                    st.session_state.aviso_lista = f"{len(marcadas)} solicitação(ões) concluída(s)."
                    st.rerun()
        if "aviso_lista" in st.session_state:
            st.success(st.session_state.pop("aviso_lista"))

        st.download_button("Exportar visão filtrada (CSV)", neutralizarFormulas(vis.drop(columns=["Data_dt"])).to_csv(index=False, sep=";").encode("utf-8-sig"),
                           "solicitacoes.csv", "text/csv")

        linhas = selecao.selection.rows if selecao and selecao.selection else []
        if linhas:
            rid = int(tabela.iloc[linhas[0]]["ID"])
            reg = next(solicitacao for solicitacao in regs if solicitacao["id"] == rid)
            st.markdown("---")
            st.markdown(f'<p class="secao">Solicitação #{rid}</p>', unsafe_allow_html=True)

            esq, dir_ = st.columns([3, 2])
            with esq:
                st.markdown(
                    f'<div class="detalhe-box"><p><b>{html.escape(reg["cliente"])}</b></p>'
                    f'<p>Solicitante: {html.escape(reg.get("solicitante", ""))} · Data: {html.escape(str(reg.get("data") or "–"))} · Tipo: {html.escape(reg.get("tipo", ""))}</p>'
                    f'<p><span class="badge {CLASSE_STATUS.get(reg["status"], "neutro")}">{reg["status"].upper()}</span> '
                    f'{URGENTE_BADGE if reg.get("prioridade") == "Urgente" else ""}'
                    f'{(" · concluída em " + reg["data_conclusao"] + " (" + str(diasEntre(reg.get("data"), reg["data_conclusao"])) + " dia(s) após a abertura)") if reg.get("data_conclusao") else (" · aberta há " + str(diasEntre(reg.get("data"))) + " dia(s)" if reg.get("data") else "")}</p>'
                    f'<p style="margin-top:.6rem">{html.escape(reg.get("descricao", ""))}</p>'
                    f'{("<p style=\"margin-top:.6rem\"><b>Resolução:</b> " + html.escape(reg["resolucao"]) + "</p>") if reg.get("resolucao") else ""}</div>',
                    unsafe_allow_html=True,
                )
                if reg["status"] != "Concluído" and reg.get("data"):
                    st.info(textoPrevisao(previsaoConclusao(regs, reg.get("tipo", ""), reg.get("prioridade", "Normal")),
                                           reg.get("tipo", ""), reg.get("prioridade", "Normal"), date.fromisoformat(reg["data"])))
                n1, n2 = st.columns(2)
                novo_status = n1.selectbox("Status", STATUS, index=STATUS.index(reg["status"]) if reg["status"] in STATUS else 0, key=f"st_{rid}")
                data_conc = n2.date_input("Data de conclusão", value=date.fromisoformat(reg["data_conclusao"]) if reg.get("data_conclusao") else date.today(),
                                          format="DD/MM/YYYY", key=f"dc_{rid}", disabled=novo_status != "Concluído")
                comentario = st.text_input("Comentário (entra no histórico)", key=f"com_{rid}")
                b1, b2 = st.columns(2)
                if b1.button("Salvar alterações", type="primary", key=f"salvar_{rid}"):
                    mudou = False
                    if novo_status != reg["status"]:
                        evento(reg, f"Status: {reg['status']} → {novo_status}")
                        reg["status"] = novo_status
                        reg["data_conclusao"] = data_conc.isoformat() if novo_status == "Concluído" else None
                        mudou = True
                    elif novo_status == "Concluído" and data_conc.isoformat() != reg.get("data_conclusao"):
                        reg["data_conclusao"] = data_conc.isoformat()
                        evento(reg, "Data de conclusão ajustada", data_conc.strftime("%d/%m/%Y"))
                        mudou = True
                    if comentario.strip():
                        evento(reg, "Comentário", comentario.strip())
                        mudou = True
                    if mudou:
                        salvarSolicitacao(reg)
                        st.session_state.aviso_lista = f"Solicitação #{rid} atualizada."
                        st.rerun()
                    else:
                        st.info("Nada para salvar.")
                with st.expander("Editar dados da solicitação"):
                    e1, e2 = st.columns(2)
                    lista_cli = carregarClientes()
                    opc_cli = lista_cli if reg["cliente"] in lista_cli else [reg["cliente"]] + lista_cli
                    ed_cli = e1.selectbox("Cliente", opc_cli, index=opc_cli.index(reg["cliente"]), key=f"edcli_{rid}")
                    ed_sol = e2.text_input("Solicitante", value=reg.get("solicitante", ""), key=f"edsol_{rid}")
                    ed_tipo = e1.selectbox("Tipo", TIPOS, index=TIPOS.index(reg["tipo"]) if reg.get("tipo") in TIPOS else 0, key=f"edtipo_{rid}")
                    ed_data = e2.date_input("Data da solicitação", value=date.fromisoformat(reg["data"]) if reg.get("data") else date.today(),
                                            format="DD/MM/YYYY", key=f"eddata_{rid}")
                    ed_prio = e1.radio("Prioridade", PRIORIDADES, index=PRIORIDADES.index(reg.get("prioridade", "Normal")), horizontal=True, key=f"edprio_{rid}")
                    ed_desc = st.text_area("Descrição", value=reg.get("descricao", ""), key=f"eddesc_{rid}")
                    if st.button("Salvar edição", key=f"edsalvar_{rid}"):
                        novos = {"cliente": ed_cli, "solicitante": canonSolicitante(ed_sol), "tipo": ed_tipo, "prioridade": ed_prio,
                                 "data": ed_data.isoformat(), "descricao": ed_desc.strip()}
                        rotulos = {"cliente": "Cliente", "solicitante": "Solicitante", "tipo": "Tipo", "prioridade": "Prioridade", "data": "Data", "descricao": "Descrição"}
                        alterados = [f"{rotulos[chave_item]}: «{reg.get(chave_item) or ('Normal' if chave_item == 'prioridade' else '')}» → «{valor_novo}»"
                                     for chave_item, valor_novo in novos.items() if (reg.get(chave_item) or ("Normal" if chave_item == "prioridade" else "")) != valor_novo]
                        if not novos["cliente"] or not novos["solicitante"] or not novos["descricao"]:
                            st.error("Cliente, solicitante e descrição não podem ficar vazios.")
                        elif alterados:
                            reg.update(novos)
                            evento(reg, "Dados editados", " | ".join(alterados))
                            salvarSolicitacao(reg)
                            st.session_state.aviso_lista = f"Solicitação #{rid} editada."
                            st.rerun()
                        else:
                            st.info("Nenhuma alteração.")
                if b2.button("Reabrir rascunho do e-mail", key=f"reemail_{rid}"):
                    ok, texto = abrirEmail(reg)
                    evento(reg, "Rascunho de e-mail criado" if ok else "Falha ao criar e-mail", "" if ok else texto)
                    salvarSolicitacao(reg)
                    (st.success if ok else st.error)(texto)
            with dir_:
                st.markdown("**Histórico**")
                for evento_historico in reversed(reg.get("historico", [])):
                    det = f'<div class="hist-detalhe">{html.escape(str(evento_historico["detalhe"]))}</div>' if evento_historico.get("detalhe") else ""
                    st.markdown(
                        f'<div class="hist-item"><div class="hist-quando">{html.escape(str(evento_historico["quando"]))}{" · " + html.escape(evento_historico["usuario"]) if evento_historico.get("usuario") else ""}</div>'
                        f'<div class="hist-evento">{html.escape(str(evento_historico["evento"]))}</div>{det}</div>',
                        unsafe_allow_html=True,
                    )
            if "aviso_lista" in st.session_state:
                st.success(st.session_state.pop("aviso_lista"))
