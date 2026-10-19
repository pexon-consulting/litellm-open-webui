# Presidio analyzer with German and English NLP models.
# The official image only ships en_core_web_lg, so German names and places are not found.
FROM mcr.microsoft.com/presidio-analyzer:2.2.362

USER root
# spaCy German model, pinned by version and SHA-256
RUN pip install --no-cache-dir \
    "de_core_news_md @ https://github.com/explosion/spacy-models/releases/download/de_core_news_md-3.8.0/de_core_news_md-3.8.0-py3-none-any.whl#sha256=b903f59220f1e76dd672acdaa7fa454d6703fe056c5ccd6457820e70874116d0"

COPY analyzer.yaml /app/presidio_analyzer/conf/analyzer-de-en.yaml
COPY nlp.yaml /app/presidio_analyzer/conf/nlp-de-en.yaml
COPY recognizers.yaml /app/presidio_analyzer/conf/recognizers-de-en.yaml
ENV ANALYZER_CONF_FILE=presidio_analyzer/conf/analyzer-de-en.yaml \
    NLP_CONF_FILE=presidio_analyzer/conf/nlp-de-en.yaml \
    RECOGNIZER_REGISTRY_CONF_FILE=presidio_analyzer/conf/recognizers-de-en.yaml
USER 1001
