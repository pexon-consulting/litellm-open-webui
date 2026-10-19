# PII masking for LLM prompts with Presidio and LiteLLM (German and English)

This guide shows how the optional PII masking in this repository works: Microsoft Presidio finds names, places, e-mail addresses, IBANs and similar data in German and English prompts, and LiteLLM replaces them with placeholders before the request leaves your network. You get the setup, what the model provider actually receives, the known false positives, how to add your own recognizer, resource needs and how to test it.

Presidio reduces the risk that personal data reaches a model provider. It does not guarantee anonymisation. Read [Known false positives and limits](#known-false-positives-and-limits) before you rely on it.

## Contents

- [Turn it on](#turn-it-on)
- [How the request flows](#how-the-request-flows)
- [Why a custom analyzer image](#why-a-custom-analyzer-image)
- [How the guardrail is wired](#how-the-guardrail-is-wired)
- [What the provider receives](#what-the-provider-receives)
- [Answers contain placeholders](#answers-contain-placeholders)
- [Known false positives and limits](#known-false-positives-and-limits)
- [Add a recognizer](#add-a-recognizer)
- [Tune or block instead of mask](#tune-or-block-instead-of-mask)
- [Resource needs](#resource-needs)
- [Test it](#test-it)
- [Common problems](#common-problems)
- [Related guides](#related-guides)

## Turn it on

PII masking is an overlay on top of the normal stack:

```bash
docker compose -f compose.yaml -f compose.pii.yaml up -d --wait
```

The first start builds the analyzer image from `presidio/`, which downloads the German spaCy model from GitHub. Use the same `-f` options for every later `docker compose` command, otherwise Compose starts LiteLLM without the guardrail.

Check that LiteLLM loaded the guardrail:

```bash
export $(grep '^LITELLM_MASTER_KEY=' .env)
curl -s http://localhost:4000/guardrails/list -H "Authorization: Bearer $LITELLM_MASTER_KEY"
```

The answer must contain `"guardrail_name":"presidio-pii"`.

## How the request flows

1. A user sends a message in Open WebUI.
2. Open WebUI sends the whole chat to LiteLLM (`OPENAI_API_BASE_URL: http://litellm:4000/v1`).
3. LiteLLM sends the text to the Presidio analyzer, which returns the positions of detected entities.
4. LiteLLM sends the text and the positions to the Presidio anonymizer, which replaces each entity with a placeholder such as `<PERSON>`.
5. LiteLLM forwards the masked request to the model provider.
6. The answer comes back with placeholders and goes to the user unchanged.

Both Presidio containers run inside your Docker network. No text goes to a third party for detection.

## Why a custom analyzer image

The official image `mcr.microsoft.com/presidio-analyzer` ships only the English spaCy model (`en_core_web_lg`). Its pattern recognizers (e-mail, IBAN, credit card) work in any language, but names and places are found by the NLP model. With the English model only, German names and places are missed.

`presidio/Dockerfile` builds on the official image and adds the German model:

```dockerfile
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
```

The model wheel is pinned by version and SHA-256, so a changed file on GitHub breaks the build instead of slipping in. The three YAML files configure the analyzer:

**`presidio/analyzer.yaml`** declares the languages `de` and `en` and sets `default_score_threshold: 0`, so every detection is passed on, however low its score.

**`presidio/nlp.yaml`** loads `de_core_news_md` for `de` and `en_core_web_lg` for `en`, and maps the spaCy labels to Presidio entities: `PER` and `PERSON` to `PERSON`; `LOC`, `GPE`, `FAC` and `LOCATION` to `LOCATION`; `NORP` to `NRP`; `DATE` and `TIME` to `DATE_TIME`. It ignores, among others, `ORG`, `ORGANIZATION`, `MISC`, `MONEY` and `PRODUCT`. **Company names are therefore not masked.**

**`presidio/recognizers.yaml`** lists the recognizers. The generic predefined ones run for both languages: `EmailRecognizer`, `IbanRecognizer`, `PhoneRecognizer`, `IpRecognizer`, `UrlRecognizer`, `CryptoRecognizer`, `CreditCardRecognizer` (with German and English context words) and `SpacyRecognizer` (the NLP model). Country-specific US and UK recognizers (US social security numbers, UK NHS numbers and the like) are left out. One custom recognizer is added for the German tax id; see [Add a recognizer](#add-a-recognizer).

## How the guardrail is wired

`compose.pii.yaml` adds two services and changes the `litellm` service:

```yaml
services:
  presidio-analyzer:
    build: ./presidio
    image: llm-gateway/presidio-analyzer-de:2.2.362
  presidio-anonymizer:
    image: mcr.microsoft.com/presidio-anonymizer:2.2.362
  litellm:
    environment:
      PRESIDIO_ANALYZER_API_BASE: http://presidio-analyzer:3000
      PRESIDIO_ANONYMIZER_API_BASE: http://presidio-anonymizer:3000
    volumes:
      - ./litellm/guardrails.pii.yaml:/app/guardrails.yaml:ro
    depends_on:
      presidio-analyzer:
        condition: service_healthy
      presidio-anonymizer:
        condition: service_healthy
```

(Abridged: the real file also has healthchecks and `restart: unless-stopped`.) Neither Presidio container publishes a port.

The trick is the volume. `litellm/config.yaml` includes `guardrails.yaml`. Without the overlay, `/app/guardrails.yaml` is `litellm/guardrails.yaml`, which contains `guardrails: []`. With the overlay, the same path is mounted from `litellm/guardrails.pii.yaml`:

```yaml
guardrails:
  - guardrail_name: presidio-pii
    litellm_params:
      guardrail: presidio
      mode: pre_call
      default_on: true
      presidio_language: de
```

What the keys do (per the [LiteLLM Presidio docs](https://docs.litellm.ai/docs/proxy/guardrails/pii_masking_v2), as of 2026-10-16):

- `guardrail: presidio` uses LiteLLM's built-in Presidio integration. It is part of the open-source edition; LiteLLM's docs say "The OSS guardrail framework includes custom guardrails and Presidio for PII masking."
- `mode: pre_call` runs the check before the model call, on the input.
- `default_on: true` runs it on every request. Clients do not have to ask for it, and every Open WebUI request goes through it.
- `presidio_language: de` tells the analyzer to use the German model. A client can override the language per request with `guardrail_config: {"language": "en"}`.

LiteLLM's docs also describe `presidio_filter_scope` with the values `input`, `output` and `both`, default `both`. In our spend logs each masked request shows a second Presidio run marked `post_call`, so the answer seems to be scanned as well. We have not tested whether that masks names the model writes on its own.

## What the provider receives

Tested in this repo with a mock model that records what it receives. The user sends:

```text
Max Mustermann aus Berlin, IBAN DE79000000001234567890, an max.mustermann@example.com
```

The provider receives:

```text
<PERSON> aus <LOCATION>, IBAN <IBAN_CODE>, an <EMAIL_ADDRESS>
```

More observations from the same setup:

- **The whole request is masked**, not just the last message: the system prompt, earlier user messages and earlier model answers in the chat history.
- **Embedding requests are masked too.** When Open WebUI indexes an uploaded document through the `embedding` model, the provider receives masked chunks. The original text stays in your Open WebUI database.
- **All persons get the same placeholder.** "Anna Schmidt" and "Peter Meier" both become `<PERSON>`. The model cannot tell them apart.
- **Prompts are not stored in LiteLLM** anyway (`store_prompts_in_spend_logs: false`), and the guardrail entry in the spend log metadata shows `"guardrail_response": "REDACTED_BY_LITELM"` instead of the detected text. In our test database no original name or IBAN appeared in the spend logs.

## Answers contain placeholders

Masking means the model never sees the real values, so it cannot use them. Ask for "an e-mail to Anna Schmidt" and you get an answer addressed to `<PERSON>`. Users have to fill in the real names themselves. Tell them before you switch masking on, or they will report it as a bug.

Open WebUI's background tasks (chat titles, tags, follow-up suggestions) also go through LiteLLM with the same key, so with `default_on: true` they are masked as well, and titles can contain placeholders.

LiteLLM has an option `output_parse_pii: True` that replaces placeholders in the answer with the original values. It is not enabled in this repo and not tested here. With it on, LiteLLM switches to numbered placeholders with a token map (`presidio.py` in v1.105.1), so the "one placeholder per type" problem above does not apply in that mode. It also makes the guardrail block requests when the analyzer fails (see the limits below). Test it with your own prompts before you enable it.

## Known false positives and limits

Observed in this repo with `de_core_news_md` and the files in `presidio/`:

| Input | Result | Effect |
|---|---|---|
| "Steuer-ID" | tagged as `PERSON` in some sentences | the word is replaced |
| an 11-digit number such as `12345678901` | `DE_TAX_ID` and also `PHONE_NUMBER` | masked; the label can be wrong |
| "Schreib eine Mail an Anna Schmidt ..." | "Schreib" (a verb at the start) tagged as `PERSON` | the model sees `<PERSON> eine Mail an <PERSON>` |
| "Geburtsdatum 01.02.1985." | the date tagged as `PERSON` | masked, wrong label |
| "Mein Name ist Lisa" | "Lisa" alone not detected | the first name reaches the provider |
| "Kundennummer 4711-2025" | not detected | no recognizer for customer numbers |
| "Müller GmbH" | not masked | `ORG` is ignored in `nlp.yaml` |
| English text with `presidio_language: de` | "Sarah Johnson from Manchester" becomes one `PERSON` | masked, but spans are less exact than with `en` |
| "max.mustermann@example.com" | also `URL` hits on parts of it | the anonymizer still produces `<EMAIL_ADDRESS>` |
| "Say hello in German." | "Say hello" as `PERSON`, "German" as `LOCATION` | the model sees `<PERSON> in <LOCATION>.` and the instruction is lost |

General limits:

- **Presidio reduces risk, it does not guarantee anonymisation.** NLP models miss names, especially single first names, unusual names and names in lowercase. Anything that identifies a person indirectly (job title plus department, a rare diagnosis, an internal case number) is not detected.
- **German dates are not tagged as dates.** The German spaCy model has no `DATE` label, so the `DATE` mapping in `nlp.yaml` only applies to English text.
- **Only text is analysed.** Images sent to vision models are not checked (not tested in this repo).
- **Analyzer errors let prompts through unmasked.** With this repo's config (no `pii_entities_config`, no `output_parse_pii`), an analyzer that answers with HTTP 4xx/5xx or with something that is not JSON makes the guardrail log a warning and return no detections. The prompt then goes to the provider **unmasked** (`proxy/guardrails/guardrail_hooks/presidio.py` in v1.105.1, read in the source, not tested). If the analyzer cannot be reached at all, LiteLLM raises "Presidio PII analysis failed" and the request fails instead.
- **Blocking instead of passing through.** Setting any `pii_entities_config` (see [Tune or block instead of mask](#tune-or-block-instead-of-mask)), or `output_parse_pii`, makes LiteLLM block the request when the analyzer returns an invalid answer. If unmasked prompts are not acceptable for you, set `pii_entities_config` with `MASK` for the entities you care about, and monitor the analyzer. At startup, `depends_on` with `condition: service_healthy` keeps LiteLLM from starting before both Presidio services are healthy.
- **Data in Open WebUI is not masked.** Masking happens between LiteLLM and the provider. Chats, uploaded files and the search index in your database keep the original text. See the [GDPR checklist](gdpr.md) for retention.
- **Retrieval quality can drop.** Document chunks and search queries are embedded in masked form, so a search for a person's name matches `<PERSON>` in every document.

## Add a recognizer

Custom pattern recognizers go into `presidio/recognizers.yaml`. The German tax id recognizer is the template:

```yaml
  # German tax identification number (Steuer-ID): 11 digits, first digit not 0.
  # Pattern only, no checksum. Context words raise the score.
  - name: DeTaxIdRecognizer
    type: custom
    supported_entity: DE_TAX_ID
    supported_language: de
    patterns:
      - name: steuer_id
        regex: "\\b[1-9]\\d{10}\\b"
        score: 0.3
    context: [steuer-id, steueridentifikationsnummer, identifikationsnummer, steuernummer, idnr]
```

- `supported_entity` becomes the placeholder (`<DE_TAX_ID>`).
- `regex` is the pattern (backslashes doubled inside YAML double quotes).
- `score` is the base confidence. Context words near the match raise it: "Meine Steuer-ID ist 12345678901." scored 0.65 in our test, and the provider received `Meine Steuer-ID ist <DE_TAX_ID>.`
- There is no checksum, so any 11-digit number starting with 1-9 matches.

Example: an internal customer number in the format `KD-` plus six digits. This is an illustration, adapt the pattern to your format:

```yaml
  - name: CustomerNumberRecognizer
    type: custom
    supported_entity: CUSTOMER_ID
    supported_language: de
    patterns:
      - name: kundennummer
        regex: "\\bKD-\\d{6}\\b"
        score: 0.6
    context: [kundennummer, kunde, kd-nr]
```

For both languages, add a second entry with `supported_language: en`. The files are copied into the image at build time, so rebuild after every change:

```bash
docker compose -f compose.yaml -f compose.pii.yaml up -d --build --wait
```

Then check the analyzer directly from inside its container (the analyzer has no published port):

```bash
docker compose -f compose.yaml -f compose.pii.yaml exec -T presidio-analyzer python -c '
import json, urllib.request
body = json.dumps({"text": "Kundennummer KD-123456, Anna Schmidt", "language": "de"}).encode()
req = urllib.request.Request("http://localhost:3000/analyze", data=body, headers={"Content-Type": "application/json"})
for e in json.loads(urllib.request.urlopen(req).read()):
    print(e["entity_type"], e["start"], e["end"], round(e["score"], 2))
'
```

LiteLLM also supports ad hoc recognizers passed from its own config (`presidio_ad_hoc_recognizers`, see the LiteLLM docs). This repo keeps all recognizers in the analyzer image instead.

## Tune or block instead of mask

These LiteLLM keys are documented in the [LiteLLM Presidio docs](https://docs.litellm.ai/docs/proxy/guardrails/pii_masking_v2) but not set or tested in this repo. They go under `litellm_params` in `litellm/guardrails.pii.yaml`:

```yaml
      pii_entities_config:
        CREDIT_CARD: "BLOCK"     # reject the request instead of masking
        PERSON: "MASK"
      presidio_score_thresholds:
        ALL: 0.5                 # drop detections below this score
        DE_TAX_ID: 0.6
```

- `BLOCK` rejects the whole request when the entity is found. Useful for data that must never leave, at the cost of users getting errors.
- `presidio_score_thresholds` reduces false positives, and also hits. The `PHONE_NUMBER` hit on an 11-digit number scored 0.4 in our test, `PERSON` hits typically 0.85.

Restart LiteLLM after changing the file:

```bash
docker compose -f compose.yaml -f compose.pii.yaml restart litellm
```

## Resource needs

Measured on one machine (Docker Desktop on macOS, idle stack, short prompts):

| Container | Image size | Memory |
|---|---|---|
| `presidio-analyzer` (custom, German and English models) | 1.02 GB | about 1.0 GiB |
| `presidio-anonymizer` | 248 MB | about 47 MiB |

The official analyzer image alone is 957 MB, so the German model adds about 60 MB to the image. Both spaCy models are loaded into memory at start. Plan at least 1.5 GB of additional RAM for the overlay.

Latency: a single-sentence analyze call took 6-12 ms on a warm analyzer in our test, and LiteLLM's guardrail entries in the spend log show about 4 ms per run. Long documents take longer; LiteLLM splits very large content blocks into chunks (`presidio_analyze_chunk_size_bytes`, default 500,000 bytes).

## Test it

`tests/test_gateway.py` contains `test_pii_is_masked_before_the_provider`. It runs against the stack with a mock model instead of a real provider, so it costs nothing. Never run it against a production stack: the test overlay replaces your models. Use a separate clone with its own `COMPOSE_PROJECT_NAME` and ports, as in [Run the tests](quickstart.md#run-the-tests).

```bash
docker compose -f compose.yaml -f compose.pii.yaml -f compose.test.yaml up -d --wait
python3 scripts/bootstrap.py
python3 -m venv .venv && .venv/bin/pip install pytest pyyaml
.venv/bin/pytest tests -k pii
```

The test sends `Max Mustermann aus Berlin, IBAN DE79000000001234567890, an max.mustermann@example.com` through LiteLLM, reads what the mock model received, and checks that "Mustermann", the IBAN and the e-mail address are gone and that `<EMAIL_ADDRESS>` and `<IBAN_CODE>` are present. Without `compose.pii.yaml` the test is skipped ("PII overlay not running").

For your own prompts, run them through the analyzer directly (see [Add a recognizer](#add-a-recognizer)) with the kind of text your users actually write: e-mails, meeting notes, support tickets. That shows false positives and misses faster than any generic list.

## Common problems

**The guardrail list is empty.** LiteLLM was started without the overlay. Use `-f compose.yaml -f compose.pii.yaml` on every command.

**The build fails at `pip install`.** The build downloads the spaCy wheel from GitHub. The build host needs internet access to `github.com`. If the SHA-256 does not match, the download was changed or corrupted.

**LiteLLM waits a long time at start.** It waits until both Presidio services are healthy. The analyzer loads two NLP models, which takes a while (`start_period: 30s` in its healthcheck).

**English names are cut wrongly.** The default language is `de`. For mostly English prompts, set `presidio_language: en` in `litellm/guardrails.pii.yaml`, or create a second guardrail for English.

**Changes in `presidio/*.yaml` have no effect.** They are baked into the image. Rebuild with `--build`.

**Users complain about `<PERSON>` in answers.** That is how masking works. See [Answers contain placeholders](#answers-contain-placeholders).

## Related guides

- [GDPR checklist for an internal LLM gateway](gdpr.md)
- [EU-hosted LLMs with LiteLLM](eu-models.md)
- [LiteLLM config.yaml explained](configuration.md)
- [Quick start](quickstart.md)
- [Security policy and defaults](../SECURITY.md)

> **Note:** Technical information as of 16 October 2026, not legal advice; the authors are not lawyers or data protection officers. No guarantee of completeness or compliance. You remain the controller and must do your own assessment (DPIA, Art. 30 record, DPAs) with your data protection officer or a lawyer.
