# ============================================================
# DataLab — Dockerfile (Fase 2: imagem Python simples)
# ------------------------------------------------------------
# Imagem leve (python:slim) para priorizar baixo consumo de
# memória (máquina com 8 GB de RAM). Evoluirá nas próximas
# fases: ETL na Fase 4, dashboard na Fase 5.
#
# Uso (PowerShell):
#   docker build -t datalab .
#   docker run --rm datalab
# ============================================================

FROM python:3.12-slim

# Diretório de trabalho dentro do container
WORKDIR /app

# Dependências primeiro para aproveitar o cache do Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código da aplicação
COPY app/ ./app/

# Placeholder: confirma que o container executa.
# Será substituído pelos comandos reais do ETL (Fase 4).
CMD ["python", "--version"]
