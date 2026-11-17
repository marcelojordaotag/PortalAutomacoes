import re
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from app.utilitarias.tema import aplicarTema, topo
from app.paginas.solicitacoes.comum import (
    MESES, PASTA_EVIDENCIAS, PRIORIDADES, STATUS, TIPOS, abrirEmail, canonSolicitante, carregar, carregarClientes, criarSolicitacao, dataBr, evento, salvarSolicitacao,
)
from app.paginas.solicitacoes.slack_solicitacoes import avisarSlackUrgente, cobrarSlack

EXTENSOES_PERMITIDAS = ["pdf", "png", "jpg", "jpeg", "xlsx", "xls", "csv", "docx", "txt", "msg"]  # sem executáveis nem scripts
LIMITE_ANEXO_MB = 10

MESES_CURTOS = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


def seletorMesAno(rotulo, chave, padrao="", limpar=True):
    """Calendário de mês/ano (ano com setas + grade de meses). Devolve 'MM/AAAA' ou '' quando nada está selecionado."""
    if chave not in st.session_state:
        st.session_state[chave] = padrao
    ano_chave = f"{chave}_ano"
    if ano_chave not in st.session_state:
        st.session_state[ano_chave] = int(st.session_state[chave][3:]) if st.session_state[chave] else date.today().year

    def escolher(valor):
        st.session_state[chave] = valor
        if valor:
            st.session_state[ano_chave] = int(valor[3:])

    def mudarAno(delta):
        st.session_state[ano_chave] += delta

    atual = st.session_state[chave]
    if rotulo:
        st.markdown(f"<p style='font-size:14px;margin:0 0 .25rem 0'>{rotulo}</p>", unsafe_allow_html=True)
    with st.popover(atual or "Selecione mês/ano", icon=":material/calendar_month:", use_container_width=True):
        st.markdown(f"""<style>
    [class*="st-key-{chave}_m"] button, [class*="st-key-{chave}_ant"] button, [class*="st-key-{chave}_prox"] button {{
        background: transparent !important; border: 1px solid transparent !important; box-shadow: none !important; }}
    [class*="st-key-{chave}_m"] button *, [class*="st-key-{chave}_ant"] button *, [class*="st-key-{chave}_prox"] button * {{ color: #3D2B33 !important; }}
    [class*="st-key-{chave}_m"] button:hover, [class*="st-key-{chave}_ant"] button:hover, [class*="st-key-{chave}_prox"] button:hover {{
        background: #F1E6EA !important; border-color: transparent !important; }}
    [class*="st-key-{chave}_ant"] button *, [class*="st-key-{chave}_prox"] button * {{ color: #6B0F2A !important; }}
    [class*="st-key-{chave}_m"] button[data-testid="stBaseButton-primary"] {{ background: #6B0F2A !important; }}
    [class*="st-key-{chave}_m"] button[data-testid="stBaseButton-primary"] * {{ color: #fff !important; font-weight: 700; }}
    </style>""", unsafe_allow_html=True)
        esquerda, centro, direita = st.columns([1, 2, 1], vertical_alignment="center")
        esquerda.button("", icon=":material/chevron_left:", key=f"{chave}_ant", type="tertiary", on_click=mudarAno, args=(-1,))
        centro.markdown(f"<div style='text-align:center;font-weight:700'>{st.session_state[ano_chave]}</div>", unsafe_allow_html=True)
        direita.button("", icon=":material/chevron_right:", key=f"{chave}_prox", type="tertiary", on_click=mudarAno, args=(1,))
        for linha in range(4):
            for indice, coluna in enumerate(st.columns(3)):
                mes = linha * 3 + indice + 1
                valor = f"{mes:02d}/{st.session_state[ano_chave]}"
                coluna.button(MESES_CURTOS[mes - 1], key=f"{chave}_m{mes}", use_container_width=True,
                              type="primary" if valor == atual else "tertiary", on_click=escolher, args=(valor,))
        hoje = date.today()
        botao_hoje, botao_limpar = st.columns(2)
        botao_hoje.button("Hoje", key=f"{chave}_hoje", type="primary", on_click=escolher, args=(f"{hoje.month:02d}/{hoje.year}",))
        if limpar:
            botao_limpar.button("Limpar", key=f"{chave}_limpar", type="primary", on_click=escolher, args=("",))
    return st.session_state[chave]


aplicarTema()
topo("Registro Solicitações de Fechamento", "Abra solicitações ao processamento e acompanhe o andamento", app="processos_externos")

if "form_v" not in st.session_state:
    st.session_state.form_v = 0  # muda a chave dos campos para limpar o formulário após salvar
regs = carregar()  # sempre do banco: os registros mudam enquanto a pessoa está na tela

aba_nova, aba_minhas = st.tabs(["Nova solicitação", "Minhas solicitações"])

# ---------------------------------------------------------------- NOVA SOLICITAÇÃO
with aba_nova:
    versao_form = st.session_state.form_v
    clientes = carregarClientes()

    coluna_cliente, coluna_solicitante = st.columns(2)
    cliente = coluna_cliente.selectbox("Cliente", [""] + clientes, key=f"cli_{versao_form}",
                          help="Digite para buscar por código ou nome.") if clientes else coluna_cliente.text_input("Cliente", key=f"cli_{versao_form}")
    logado = (st.session_state.get("auth") or {}).get("nome", "")
    solicitante = coluna_solicitante.text_input("Solicitante", value=logado, key=f"sol_{versao_form}", max_chars=80,
                               help="Vem com o seu nome; altere se estiver pedindo por outra pessoa.")

    coluna_data, coluna_tipo = st.columns(2)
    data_sol = coluna_data.date_input("Data", value=date.today(), format="DD/MM/YYYY", key=f"data_{versao_form}")
    tipo = coluna_tipo.selectbox("Tipo de demanda", TIPOS, key=f"tipo_{versao_form}")

    coluna_comp, coluna_urg = st.columns(2)
    hoje = date.today()
    with coluna_comp:
        competencia = seletorMesAno("Competência (mês/ano)", f"comp_{versao_form}", padrao=f"{hoje.month:02d}/{hoje.year}", limpar=False)
    prioridade = coluna_urg.radio("Urgência", PRIORIDADES, horizontal=True, key=f"prio_{versao_form}",
                                  format_func=lambda opcao: "Não urgente" if opcao == "Normal" else "Urgente")
    sla_data = None
    if prioridade == "Urgente":
        sla_data = st.columns(2)[0].date_input("SLA (prazo para conclusão)", value=max(hoje, data_sol), min_value=data_sol, format="DD/MM/YYYY",
                                               key=f"sla_{versao_form}", help="Data limite para o processamento concluir esta solicitação.")

    campos = []
    valores = {}
    extra = st.text_area("Detalhes adicionais" if campos else "Descrição do problema", height=110, key=f"desc_{versao_form}")
    linhas_desc = [f"{chave_item}: {val.strip()}" for chave_item, val in valores.items() if val.strip()]
    if extra.strip():
        linhas_desc.append(("Detalhes: " if linhas_desc else "") + extra.strip())
    descricao = "\n".join(linhas_desc)
    anexo = st.file_uploader("Evidência (opcional)", key=f"anexo_{versao_form}", type=EXTENSOES_PERMITIDAS,
                             help=f"Até {LIMITE_ANEXO_MB} MB. Tipos: " + ", ".join(EXTENSOES_PERMITIDAS))

    duplicadas = [solicitacao for solicitacao in regs if cliente and solicitacao["cliente"] == cliente and solicitacao.get("tipo") == tipo and solicitacao["status"] != "Concluído"]
    confirmar_dup = True
    if duplicadas:
        ids = ", ".join(f"#{solicitacao['id']} ({(solicitacao.get('data') or '')[:10]})" for solicitacao in duplicadas)
        st.warning(f"Este cliente já tem solicitação não concluída do tipo **{tipo}**: {ids}. Veja na aba de histórico antes de abrir outra.")
        confirmar_dup = st.checkbox("É uma solicitação nova mesmo assim", key=f"dup_{versao_form}")

    if st.button("Registrar solicitação", type="primary"):
        faltando = [nm_campo for nm_campo, val in (("Cliente", cliente), ("Solicitante", solicitante.strip()), ("Descrição", descricao.strip())) if not val]
        faltando += [rotulo for rotulo, obrig, _ in campos if obrig and not valores.get(rotulo, "").strip()]
        if faltando:
            st.error("Preencha: " + ", ".join(faltando))
        elif (clientes and cliente not in clientes) or len(solicitante) > 80 or len(descricao) > 5000:
            st.error("Dados inválidos: confira o cliente, o nome do solicitante (até 80 caracteres) e a descrição (até 5000).")
        elif anexo is not None and anexo.size > LIMITE_ANEXO_MB * 1024 * 1024:
            st.error(f"A evidência passa de {LIMITE_ANEXO_MB} MB.")
        elif not confirmar_dup:
            st.error("Existe solicitação semelhante em aberto. Marque a confirmação para registrar mesmo assim.")
        else:
            reg = {
                "cliente": cliente, "solicitante": canonSolicitante(solicitante), "data": data_sol.isoformat(),
                "tipo": tipo, "prioridade": prioridade, "competencia": competencia, "sla_data": sla_data.isoformat() if sla_data else None, "descricao": descricao.strip(), "status": "Em Processamento", "data_conclusao": None,
                "evidencia": "", "historico": [],
                "registrado_por": (st.session_state.get("auth") or {}).get("usuario", ""),
            }
            evento(reg, "Solicitação registrada", f"{tipo} · {prioridade}" + (f" · SLA {sla_data.strftime('%d/%m/%Y')}" if sla_data else "") + f" · competência {competencia} · por {reg['solicitante']}")
            novo_id = criarSolicitacao(reg)  # o id vem do banco (AUTO_INCREMENT)
            if anexo is not None:
                PASTA_EVIDENCIAS.mkdir(exist_ok=True)
                nome_seguro = re.sub(r"[^A-Za-z0-9._-]", "_", Path(anexo.name).name)[-80:]  # sem pastas nem caracteres especiais
                destino = PASTA_EVIDENCIAS / f"{novo_id}_{nome_seguro}"
                destino.write_bytes(anexo.getbuffer())
                reg["evidencia"] = str(destino)  # o banco guarda só o nome do arquivo
                salvarSolicitacao(reg)
            texto_mensagem = f"Solicitação #{novo_id} registrada."
            if prioridade == "Urgente":
                ok_slack, texto_slack = avisarSlackUrgente(reg)
                evento(reg, "Aviso urgente no Slack" if ok_slack else "Falha ao avisar no Slack", "" if ok_slack else texto_slack)
                salvarSolicitacao(reg)
                texto_mensagem += " " + texto_slack
            ok, texto = abrirEmail(reg)
            evento(reg, "Rascunho de e-mail criado" if ok else "Falha ao criar e-mail", "" if ok else texto)
            salvarSolicitacao(reg)
            texto_mensagem += " " + texto
            st.session_state.form_v += 1
            st.session_state.aviso = texto_mensagem
            st.rerun()
    if "aviso" in st.session_state:
        st.success(st.session_state.pop("aviso"))


# ---------------------------------------------------------------- MINHAS SOLICITAÇÕES
with aba_minhas:
    eu = (st.session_state.get("auth") or {}).get("usuario", "")
    minhas = sorted((solicitacao for solicitacao in regs if solicitacao.get("registrado_por") == eu), key=lambda solicitacao: solicitacao["id"], reverse=True)
    if not minhas:
        st.info("Você ainda não registrou nenhuma solicitação.")
    else:
        f1, f2, f3, f4 = st.columns(4)
        filtro_cliente = f1.multiselect("Cliente", sorted({solicitacao["cliente"] for solicitacao in minhas}), key="fm_cli")
        filtro_tipo = f2.multiselect("Tipo", TIPOS, key="fm_tipo")
        filtro_status = f3.multiselect("Status", STATUS, key="fm_status")
        filtro_urgencia = f4.selectbox("Urgência", ["Todas", "Urgentes", "Não urgentes"], key="fm_urg")
        f5, f6 = st.columns([1, 3])
        with f5:
            filtro_comp = seletorMesAno("Competência", "fm_comp")
        filtro_texto = f6.text_input("Buscar na descrição", key="fm_txt")
        visiveis = [solicitacao for solicitacao in minhas
                    if (not filtro_cliente or solicitacao["cliente"] in filtro_cliente)
                    and (not filtro_tipo or solicitacao.get("tipo") in filtro_tipo)
                    and (not filtro_status or solicitacao["status"] in filtro_status)
                    and (not filtro_comp or solicitacao.get("competencia") == filtro_comp)
                    and (filtro_urgencia == "Todas" or (solicitacao.get("prioridade") == "Urgente") == (filtro_urgencia == "Urgentes"))
                    and filtro_texto.strip().lower() in solicitacao.get("descricao", "").lower()]
        if not visiveis:
            st.info("Nenhuma solicitação com esses filtros.")
        else:
            tabela = st.dataframe(pd.DataFrame([{
                "ID": solicitacao["id"], "Data": solicitacao.get("data"), "Cliente": solicitacao["cliente"], "Tipo": solicitacao.get("tipo", ""),
                "Competência": solicitacao.get("competencia", ""), "Urgente": "Sim" if solicitacao.get("prioridade") == "Urgente" else "Não",
                "SLA": dataBr(solicitacao.get("sla_data")) or "–", "Status": solicitacao["status"], "Concluída em": solicitacao.get("data_conclusao") or "–",
                "Descrição": solicitacao.get("descricao", ""), "Como foi resolvida": solicitacao.get("resolucao", ""),
            } for solicitacao in visiveis]), hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row", key="tab_minhas")
            linhas_sel = tabela.selection.rows
            escolhida = visiveis[linhas_sel[0]] if linhas_sel else None
            pode_cobrar = escolhida is not None and escolhida["status"] != "Concluído"
            if st.button("Cobrar resposta no Slack", disabled=not pode_cobrar, key="cobrar",
                         help="Selecione na tabela uma solicitação não concluída para cobrar o processamento."):
                ok_cobranca, texto_cobranca = cobrarSlack(escolhida)
                evento(escolhida, "Cobrança enviada no Slack" if ok_cobranca else "Falha ao cobrar no Slack", "" if ok_cobranca else texto_cobranca)
                salvarSolicitacao(escolhida)
                (st.success if ok_cobranca else st.error)(texto_cobranca)
            elif escolhida is None:
                st.caption("Selecione uma linha da tabela para cobrar a resposta no Slack.")
