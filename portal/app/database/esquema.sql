-- Esquema do banco do portal (MySQL 8). Rode com: python -m app.database.criar_esquema
-- O schema é compartilhado com a área inteira: TODA tabela do portal começa com portal_ (portal_tb_*) e as constraints de
-- chave estrangeira com fk_portal_, para identificar o que é do projeto e não colidir com nomes de outros projetos.
-- Padrão TAG: tabelas tb_*, colunas com prefixo (id_ chave, nm_ nome, ds_ texto, dt_ data, vl_/qt_ número,
-- ic_ indicador, nr_ número de documento/ordem, js_ JSON).

-- ===== Segurança do portal =====
CREATE TABLE IF NOT EXISTS portal_tb_usuario (
    nm_usuario              VARCHAR(80) NOT NULL PRIMARY KEY,
    nm_nome                 VARCHAR(200) NOT NULL,
    nm_perfil               VARCHAR(20) NOT NULL,
    ic_ativo                TINYINT(1) NOT NULL DEFAULT 1,
    js_apps                 JSON NULL,
    ds_salt                 VARCHAR(200) NOT NULL,
    ds_hash                 VARCHAR(400) NOT NULL,
    qt_iteracoes            INT NOT NULL,
    ic_pimenta              TINYINT(1) NOT NULL DEFAULT 0,
    ic_trocar_senha         TINYINT(1) NOT NULL DEFAULT 0,
    qt_falhas               INT NOT NULL DEFAULT 0,
    qt_bloqueios            INT NOT NULL DEFAULT 0,
    dt_bloqueado_ate        DATETIME NULL,
    js_bloqueio_dispositivo JSON NULL,
    dt_criado               DATETIME NULL,
    dt_ultimo_acesso        DATETIME NULL
);

CREATE TABLE IF NOT EXISTS portal_tb_usuario_2fa (
    nm_usuario VARCHAR(80) NOT NULL PRIMARY KEY,
    ds_segredo VARCHAR(300) NOT NULL,  -- segredo TOTP criptografado (Fernet)
    dt_criado  DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS portal_tb_sessao (
    ds_hash    VARCHAR(200) NOT NULL PRIMARY KEY,
    nm_usuario VARCHAR(80) NOT NULL,
    dt_criado  DATETIME NOT NULL,
    dt_expira  DATETIME NOT NULL,
    KEY ix_sessao_expira (dt_expira)
);

CREATE TABLE IF NOT EXISTS portal_tb_dispositivo (
    nm_usuario     VARCHAR(80) NOT NULL,
    ds_dispositivo VARCHAR(120) NOT NULL,
    ds_ip          VARCHAR(80) NULL,
    nm_host        VARCHAR(200) NULL,
    dt_visto       DATETIME NULL,
    PRIMARY KEY (nm_usuario, ds_dispositivo)
);

CREATE TABLE IF NOT EXISTS portal_tb_acesso_log (
    id_acesso     BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    dt_evento     DATETIME NOT NULL,
    nm_evento     VARCHAR(60) NOT NULL,
    nm_usuario    VARCHAR(80) NULL,
    ds_detalhe    TEXT NULL,
    ds_ip         VARCHAR(80) NULL,
    nm_computador VARCHAR(200) NULL,
    KEY ix_acesso_evento (dt_evento)
);

-- ===== Mesa de Boletas: Controle de Erros =====
CREATE TABLE IF NOT EXISTS portal_tb_boletador_card (
    id_card              INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    ds_titulo            VARCHAR(300) NOT NULL,
    ds_descricao         TEXT NULL,
    nm_coluna            VARCHAR(60) NOT NULL,
    nm_prioridade        VARCHAR(20) NOT NULL,
    qt_ocorrencias       INT NOT NULL DEFAULT 0,
    ds_solucao           TEXT NULL,
    nm_categoria         VARCHAR(80) NULL,
    ds_causa_raiz        TEXT NULL,
    dt_criado            DATETIME NULL,
    dt_atualizado        DATETIME NULL,
    dt_ultima_ocorrencia DATE NULL,
    dt_resolvido         DATETIME NULL,
    qt_ocorrencias_ata   INT NULL  -- foto da última ata (antes: snapshot_ata.json)
);

CREATE TABLE IF NOT EXISTS portal_tb_boletador_card_conexao (
    id_card           INT NOT NULL,
    id_card_conectado INT NOT NULL,
    PRIMARY KEY (id_card, id_card_conectado),
    CONSTRAINT fk_portal_conexao_card FOREIGN KEY (id_card) REFERENCES portal_tb_boletador_card (id_card) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS portal_tb_boletador_card_historico (
    id_historico   INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    id_card        INT NOT NULL,
    dt_registro    DATETIME NULL,
    qt_ocorrencias INT NOT NULL DEFAULT 0,
    ds_nota        TEXT NULL,
    CONSTRAINT fk_portal_historico_card FOREIGN KEY (id_card) REFERENCES portal_tb_boletador_card (id_card) ON DELETE CASCADE
);

-- ===== Solicitações / Processos externos =====
CREATE TABLE IF NOT EXISTS portal_tb_cliente (
    id_cliente INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    ds_cliente VARCHAR(300) NOT NULL,   -- "<id> - NOME", como na lista antiga
    UNIQUE KEY uq_cliente (ds_cliente)
);

CREATE TABLE IF NOT EXISTS portal_tb_solicitacao (
    id_solicitacao    INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    ds_cliente        VARCHAR(300) NOT NULL,
    nm_solicitante    VARCHAR(200) NULL,
    dt_solicitacao    DATE NULL,
    nm_tipo           VARCHAR(80) NULL,
    ds_descricao      TEXT NULL,
    nm_status         VARCHAR(40) NOT NULL,
    dt_conclusao      DATE NULL,
    nm_evidencia      VARCHAR(400) NULL,  -- só o nome do arquivo na pasta de evidências (antes: caminho absoluto)
    nm_prioridade     VARCHAR(40) NULL,
    nm_registrado_por VARCHAR(200) NULL,
    ds_competencia    VARCHAR(10) NULL,
    dt_sla            DATE NULL,
    KEY ix_solicitacao_status (nm_status)
);

CREATE TABLE IF NOT EXISTS portal_tb_solicitacao_historico (
    id_historico   INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    id_solicitacao INT NOT NULL,
    dt_evento      DATETIME NULL,
    nm_evento      VARCHAR(120) NULL,
    ds_detalhe     TEXT NULL,
    nm_usuario     VARCHAR(80) NULL,
    CONSTRAINT fk_portal_solicitacao_hist FOREIGN KEY (id_solicitacao) REFERENCES portal_tb_solicitacao (id_solicitacao) ON DELETE CASCADE
);

-- ===== Conciliação de Caixa =====
CREATE TABLE IF NOT EXISTS portal_tb_caixa_categoria (
    nm_categoria VARCHAR(200) NOT NULL PRIMARY KEY,
    nr_ordem     INT NOT NULL
);

CREATE TABLE IF NOT EXISTS portal_tb_caixa_estado (
    nm_planilha   VARCHAR(200) NOT NULL,
    id_carteira   VARCHAR(40) NOT NULL,
    ds_obs        TEXT NULL,
    nm_status     VARCHAR(20) NULL,
    ds_comentario TEXT NULL,
    PRIMARY KEY (nm_planilha, id_carteira)
);

CREATE TABLE IF NOT EXISTS portal_tb_caixa_monitor_email (
    id_monitor        INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    ds_token          VARCHAR(80) NOT NULL,
    nm_imagem         VARCHAR(300) NULL,
    nm_status         VARCHAR(40) NOT NULL,
    qt_prazo_horas    INT NULL,
    dt_criado         DATETIME NULL,
    dt_enviado        DATETIME NULL,
    ds_topico         VARCHAR(300) NULL,
    ds_assunto        VARCHAR(500) NULL,
    ds_para           TEXT NULL,
    nm_respondido_por VARCHAR(300) NULL,
    dt_respondido     DATETIME NULL,
    ds_entry_id       VARCHAR(400) NULL,
    ds_corpo          MEDIUMTEXT NULL,
    ds_nota_anexos    TEXT NULL,
    nm_slack          VARCHAR(40) NULL,
    ds_alerta_prazo   VARCHAR(80) NULL,
    UNIQUE KEY uq_monitor_token (ds_token)
);

-- ===== Crava Cotas =====
CREATE TABLE IF NOT EXISTS portal_tb_crava_cadastro (
    id_cadastro            INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    ds_grupo_proc_paralelo VARCHAR(200) NULL,
    id_cliente             VARCHAR(40) NULL,
    nm_apelido             VARCHAR(300) NULL,
    id_pessoa              VARCHAR(40) NULL,
    ds_zera_caixa          VARCHAR(40) NULL,
    ds_tipo_cliente        VARCHAR(80) NULL,
    ds_ativo               VARCHAR(40) NULL,
    ds_tipo_controle       VARCHAR(80) NULL,
    ds_implantacao         VARCHAR(80) NULL,
    ds_status              VARCHAR(80) NULL,
    ds_data_dia            VARCHAR(40) NULL,
    ds_data_atualizacao    VARCHAR(40) NULL,
    ds_ativo_cetip         VARCHAR(40) NULL,
    UNIQUE KEY uq_crava_cliente (id_cliente)   -- Id Cliente (carteira na Britech) identifica o cadastro
);

CREATE TABLE IF NOT EXISTS portal_tb_crava_leitura_meta (
    id_meta      TINYINT NOT NULL PRIMARY KEY,   -- sempre 1
    dt_lido      DATETIME NULL,
    ic_concluido TINYINT(1) NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS portal_tb_crava_leitura (
    nm_dia         VARCHAR(10) NOT NULL PRIMARY KEY,   -- "D-2", "D-3"
    ds_situacao    VARCHAR(40) NULL,
    vl_progresso   DECIMAL(6,2) NULL,
    ds_diagnostico TEXT NULL,
    ds_data        VARCHAR(20) NULL
);

CREATE TABLE IF NOT EXISTS portal_tb_crava_leitura_linha (
    nm_dia        VARCHAR(10) NOT NULL,
    nr_linha      INT NOT NULL,
    ds_id_exec    VARCHAR(80) NULL,
    nm_fundo      VARCHAR(300) NULL,
    nr_cnpj       VARCHAR(30) NULL,
    ds_valor_cota VARCHAR(80) NULL,
    ds_status     VARCHAR(120) NULL,
    PRIMARY KEY (nm_dia, nr_linha),
    CONSTRAINT fk_portal_leitura_linha FOREIGN KEY (nm_dia) REFERENCES portal_tb_crava_leitura (nm_dia) ON DELETE CASCADE
);

-- ===== Britech =====
CREATE TABLE IF NOT EXISTS portal_tb_britech_carteira (
    id_cliente VARCHAR(20) NOT NULL PRIMARY KEY,
    nr_ordem   INT NOT NULL
);

-- ===== Extratos =====
CREATE TABLE IF NOT EXISTS portal_tb_extratos_fundo_cotista (
    id_registro    INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    nm_fundo       VARCHAR(300) NULL,
    nr_cnpj        VARCHAR(30) NULL,
    nm_cotista     VARCHAR(300) NULL,
    nr_doc_cotista VARCHAR(30) NULL,
    ds_emails      TEXT NULL,
    -- chaves só com letras e números (sem ponto, traço e barra). Um cadastro = fundo (CNPJ) + cotista (CPF/CNPJ + nome):
    -- cotistas diferentes podem usar o mesmo CPF/CNPJ (ex.: perfis Agressivo, Conservador e Moderado do mesmo grupo).
    -- O nome entra na chave pela própria coluna nm_cotista (a collation do banco ignora maiúsculas e acentos).
    ds_chave_fundo   VARCHAR(30) GENERATED ALWAYS AS (REGEXP_REPLACE(UPPER(COALESCE(nr_cnpj, '')), '[^0-9A-Z]', '')) STORED,
    ds_chave_cotista VARCHAR(30) GENERATED ALWAYS AS (REGEXP_REPLACE(UPPER(COALESCE(nr_doc_cotista, '')), '[^0-9A-Z]', '')) STORED,
    UNIQUE KEY uq_fundo_cotista (ds_chave_fundo, ds_chave_cotista, nm_cotista)
);

-- Aba "Planilha1" da planilha antiga (nome + documento; o app nunca leu essa aba)
CREATE TABLE IF NOT EXISTS portal_tb_extratos_cotista_legado (
    id_registro INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    nm_cotista  VARCHAR(300) NULL,
    nr_doc      VARCHAR(30) NULL
);

CREATE TABLE IF NOT EXISTS portal_tb_extratos_rodada (
    id_rodada      INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    dt_inicio      DATETIME NOT NULL,
    dt_referencia  DATE NOT NULL,
    ic_encerrada   TINYINT(1) NOT NULL DEFAULT 0,
    dt_atualizado  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_rodada_inicio (dt_inicio)
);

CREATE TABLE IF NOT EXISTS portal_tb_extratos_rodada_item (
    id_rodada INT NOT NULL,
    nr_item   INT NOT NULL,
    ds_emails TEXT NULL,
    qt_linhas INT NULL,
    js_cnpjs  JSON NULL,   -- {fundo: cnpj}
    PRIMARY KEY (id_rodada, nr_item),
    CONSTRAINT fk_portal_rodada_item FOREIGN KEY (id_rodada) REFERENCES portal_tb_extratos_rodada (id_rodada) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS portal_tb_extratos_rodada_cotista (
    id_rodada      INT NOT NULL,
    nr_item        INT NOT NULL,
    nr_ordem       INT NOT NULL,   -- ordem de leitura (fundos e cotistas mantêm a ordem original)
    nm_fundo       VARCHAR(300) NOT NULL,
    nm_cotista     VARCHAR(300) NULL,
    nr_doc_cotista VARCHAR(30) NULL,
    PRIMARY KEY (id_rodada, nr_item, nr_ordem),
    CONSTRAINT fk_portal_rodada_cotista FOREIGN KEY (id_rodada, nr_item) REFERENCES portal_tb_extratos_rodada_item (id_rodada, nr_item) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS portal_tb_extratos_rodada_reenvio (
    id_rodada  INT NOT NULL,
    nr_item    INT NOT NULL,
    dt_reenvio DATETIME NOT NULL,
    PRIMARY KEY (id_rodada, nr_item),
    CONSTRAINT fk_portal_rodada_reenvio FOREIGN KEY (id_rodada) REFERENCES portal_tb_extratos_rodada (id_rodada) ON DELETE CASCADE
);

-- Manifesto dos anexos já salvos (antes: Extratos/<AAAA-MM>/_salvos.json)
CREATE TABLE IF NOT EXISTS portal_tb_extratos_anexo_salvo (
    ds_chave   VARCHAR(600) NOT NULL,   -- "<EntryID>|<arquivo>|<tamanho>"
    nm_mes     CHAR(7) NOT NULL,        -- AAAA-MM
    ds_caminho TEXT NOT NULL,           -- relativo à pasta Extratos (ex.: 2026-10/Fundo/arquivo.pdf)
    PRIMARY KEY (ds_chave(300), nm_mes)
);

-- Histórico de cotas do Monitor de cotas da Rentabilidade (antes: dados/britech/Historico_Cotas.csv)
CREATE TABLE IF NOT EXISTS portal_tb_britech_historico_cota (
    id_carteira             VARCHAR(20) NOT NULL,
    dt_cota                 DATE NOT NULL,
    vl_cota_bruta           DECIMAL(24,10) NULL,
    vl_pl_fechamento        DECIMAL(24,6) NULL,
    vl_quantidade_fechamento DECIMAL(24,8) NULL,
    dt_atualizacao          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,   -- quando a busca na API gravou a linha
    PRIMARY KEY (id_carteira, dt_cota)
);

-- Campos extras da solicitação (resolução e e-mail do solicitante) que não existem em portal_tb_solicitacao
CREATE TABLE IF NOT EXISTS portal_tb_solicitacao_complemento (
    id_solicitacao       INT NOT NULL PRIMARY KEY,
    ds_resolucao         TEXT NULL,
    ds_email_solicitante VARCHAR(300) NULL,
    CONSTRAINT fk_portal_solicitacao_compl FOREIGN KEY (id_solicitacao) REFERENCES portal_tb_solicitacao (id_solicitacao) ON DELETE CASCADE
);

-- Cadastros de fundo/cotista apagados na tela (cópia da linha, quem apagou e quando), para poder recuperar
CREATE TABLE IF NOT EXISTS portal_tb_extratos_cadastro_excluido (
    id_exclusao    INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    dt_exclusao    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    nm_usuario     VARCHAR(80) NULL,
    id_registro    INT NULL,
    nm_fundo       VARCHAR(300) NULL,
    nr_cnpj        VARCHAR(30) NULL,
    nm_cotista     VARCHAR(300) NULL,
    nr_doc_cotista VARCHAR(30) NULL,
    ds_emails      TEXT NULL,
    KEY ix_cadastro_excluido_data (dt_exclusao)
);
