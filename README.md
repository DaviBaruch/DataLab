# DataLab — Análise Territorial do Brasil

Pipeline ETL + Dashboard interativo dos **distritos brasileiros** (IBGE). O projeto extrai dados da base territorial do IBGE, transforma com Python/Pandas, carrega em **PostgreSQL** e entrega um **dashboard Streamlit** com mapa coroplético das 27 UFs, rankings por estado, região e município, em três estilos visuais.

## Funcionalidades

- **ETL completo** em Python: transformação (`pandas` + `json_normalize`) e carga idempotente no PostgreSQL (`INSERT ... ON CONFLICT DO NOTHING`).
- Dados reais do IBGE: **10.751 distritos**, **5.571 municípios**, **27 UFs** (26 estados + Distrito Federal) e **5 regiões**, carregados do banco em tempo real.
- **Dashboard com 4 modos**: Visão geral, Análise por estados, Análise por regiões e Análise por municípios.
- **Mapa coroplético** das 27 UFs com malha oficial do IBGE (arquivo baixado uma vez e armazenado em cache).
- **3 estilos visuais**: Minimalista, Analítico e Dark/tecnológico.
- Tratamento honesto de dados ausentes: nada é preenchido ou descartado silenciosamente.

## Arquitetura

```text
API IBGE ──► data/raw/distritos.json ──► Transform (Pandas) ──► data/processed/distritos.csv
                                                                              │
                                                                              ▼
                                                              Load (Psycopg 3) ──► PostgreSQL (Docker)
                                                                              │
                                                                              ▼
                                                     Dashboard (Streamlit + Plotly) ◄── consultas SQL
```

## Estrutura de diretórios

```text
DataLab/
├── app/
│   └── dashboard/          # Dashboard Streamlit
│       ├── main.py         # Interface (modos, estilos, mapa, gráficos)
│       └── database.py     # Camada de consultas ao PostgreSQL (sem SQL duplicado no dashboard)
├── etl/
│   ├── transform/
│   │   └── transform_distritos.py   # Etapa Transform: normaliza e limpa
│   └── load/
│       ├── load_distritos.py        # Etapa Load: cria tabela e carrega (idempotente)
│       └── test_connection.py       # Diagnóstico de conexão com o banco
├── data/
│   ├── raw/                # Dados brutos (não versionados)
│   ├── processed/          # Dados transformados (não versionados)
│   └── geo/                # Malha GeoJSON do IBGE (não versionada; baixada em cache)
├── database/init/          # Scripts SQL de inicialização (se aplicável)
├── docs/                   # Documentação de arquitetura
├── tests/                  # Testes
├── .env.example            # Modelo de variáveis de ambiente (SEM segredos)
├── .gitignore              # Arquivos que não entram no Git
├── .dockerignore           # Arquivos que não entram na imagem
├── Dockerfile              # Imagem Python
├── compose.yaml            # Orquestração do PostgreSQL
├── requirements.txt        # Dependências Python
└── README.md
```

## Tecnologias

| Tecnologia | Uso |
|---|---|
| Python 3.12 + Pandas | Pipeline ETL (normalização, limpeza, validação) |
| Psycopg 3 | Conexão e carga no PostgreSQL |
| PostgreSQL 16 (Docker) | Armazenamento e consultas |
| Streamlit | Interface do dashboard |
| Plotly | Mapa coroplético e gráficos interativos |
| Docker Compose | PostgreSQL containerizado |
| Git / GitHub | Versionamento e publicação |

## Pré-requisitos

- **Docker Desktop** (com WSL 2 no Windows) — para o PostgreSQL: `docker --version`
- **Python 3.12+** — para ETL e dashboard: `python --version`
- **Git** — `git --version`
- Conexão com a internet — para `pip install` e, no primeiro uso, baixar a malha do IBGE

## Instalação

```bash
# 1. Clonar o repositório
git clone https://github.com/<seu-usuario>/DataLab.git
cd DataLab

# 2. Criar o ambiente virtual e instalar dependências
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux/macOS
pip install -r requirements.txt

# 3. Configurar as variáveis de ambiente
cp .env.example .env          # Windows: copy .env.example .env
# 4. Subir o PostgreSQL
docker compose up -d
```

## Configuração (`.env`)

Copie `.env.example` para `.env` e ajuste os valores. **Nunca** versione o `.env` real — o `.gitignore` já o exclui. O arquivo exemplo usa apenas placeholders (`senha`), sem credenciais reais:

```dotenv
POSTGRES_USER=datalab
POSTGRES_PASSWORD=senha
POSTGRES_DB=datalab
POSTGRES_PORT=5432
DATABASE_URL=postgresql://datalab:senha@postgres:5432/datalab
```

> No Windows, `localhost` é a porta publicada pelo Docker para o PostgreSQL.
> O usuário/senha acima são de **exemplo** — use os valores do seu `.env`.

## Executando o pipeline ETL

Cada etapa roda da **raiz do projeto**, com o Python do venv:

```bash
# 1. Popule data/raw/distritos.json (dados da API de distritos do IBGE;
#    o Transform espera uma lista de objetos com 'id', 'nome' e blocos
#    aninhados de municipio/microrregiao/regiao_imediata).

# 2. Transform: lê data/raw/distritos.json, limpa e grava data/processed/distritos.csv
.venv\Scripts\python etl/transform/transform_distritos.py

# 3. Load: cria a tabela 'distritos' (se não existir) e insere os registros.
#    Execuções repetidas não duplicam dados (ON CONFLICT DO NOTHING).
.venv\Scripts\python etl/load/load_distritos.py
```

O Load é **idempotente**: rodar de novo insere apenas o que falta e ignora o resto.

## Executando o dashboard

Com o PostgreSQL rodando (`docker compose up -d`) e os dados carregados:

```bash
.venv\Scripts\python -m streamlit run app/dashboard/main.py
```

Abra `http://localhost:8501`. Opções na barra lateral:

- **Visão geral** — indicadores gerais + mapa + barras por estado.
- **Análise por estados** — mapa + ranking dos estados.
- **Análise por regiões** — mapa + distribuição regional (rosca).
- **Análise por municípios** — mapa + top 10 municípios em distritos.

Estilos: **Minimalista**, **Analítico** e **Dark/tecnológico**.

Na primeira execução o dashboard baixa a malha das 27 UFs da API de malhas do IBGE (uma única vez, salva em `data/geo/`).

## Docker

```bash
docker compose up -d       # sobe o PostgreSQL
docker compose ps          # status dos serviços
docker compose logs -f     # logs
docker compose down        # encerra
```

## Sobre os dados

- Fonte: cadastro de **distritos** da API de localidades do IBGE (10.751 registros).
- Cada distrito chega com duas hierarquias: `municipio → microrregiao → mesorregiao → UF → região` e `municipio → regiao imediata → regiao intermediaria → UF → região`. As consultas usam a UF/região **efetivas** (com valor na primeira hierarquia que os contiver).
- Valores ausentes **não** são preenchidos nem descartados: aparecem como NULL, quantificados em indicadores próprios.
- O GeoJSON do mapa é a malha oficial do IBGE (qualidade intermediária), com as 27 UFs identificadas pelo código oficial.

## Segurança

- `.env` (credenciais reais) nunca é versionado; apenas `.env.example` com placeholders.
- Nenhum token ou senha aparece no código, nos exemplos ou no histórico.
- O banco usa porta publicada apenas no `localhost` (Docker Desktop).

---

*Projeto de engenharia de dados: Docker, ETL (Python/Pandas), PostgreSQL e dashboards com Streamlit + Plotly.*
