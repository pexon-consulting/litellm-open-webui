# EU-hosted LLMs with LiteLLM: Azure, Bedrock, Vertex, Mistral, STACKIT, IONOS and more

This guide lists the EU hosting options for large language models that work with the LiteLLM proxy in this repository. For each provider you get what "EU" means in the provider's own documents, the traps that send data outside the EU anyway, how long prompts are kept for abuse monitoring, and the ready-made file in `examples/providers/`. At the end you find prices, how to combine providers with fallbacks, and the facts on the CLOUD Act and the EU-US Data Privacy Framework.

All provider statements were read on 2026-10-16. Providers change their terms, so follow the links before you rely on a statement. Items we could not confirm from a primary source are marked **not verified**.

## Contents

- [What to check before you call a model "EU"](#what-to-check-before-you-call-a-model-eu)
- [Overview](#overview)
- [Switch the stack to another provider](#switch-the-stack-to-another-provider)
- [Microsoft Azure OpenAI / Foundry](#microsoft-azure-openai--foundry)
- [AWS Bedrock](#aws-bedrock)
- [Google Vertex AI](#google-vertex-ai)
- [Mistral AI](#mistral-ai)
- [OpenAI API with EU data residency](#openai-api-with-eu-data-residency)
- [Anthropic API](#anthropic-api)
- [STACKIT](#stackit)
- [IONOS AI Model Hub](#ionos-ai-model-hub)
- [OVHcloud AI Endpoints](#ovhcloud-ai-endpoints)
- [Scaleway Generative APIs](#scaleway-generative-apis)
- [T-Systems LLM Hub](#t-systems-llm-hub)
- [Nebius Token Factory](#nebius-token-factory)
- [Aleph Alpha PhariaAI](#aleph-alpha-phariaai)
- [Self-hosted: vLLM and Ollama](#self-hosted-vllm-and-ollama)
- [Prices](#prices)
- [Combine providers with fallbacks](#combine-providers-with-fallbacks)
- [CLOUD Act and Data Privacy Framework: the facts](#cloud-act-and-data-privacy-framework-the-facts)
- [Common problems](#common-problems)
- [Related guides](#related-guides)

## What to check before you call a model "EU"

"EU-hosted" can mean several different things. Check each point separately for every model you add:

1. **Processing location.** Where does inference run? Some EU options include EFTA countries (Norway, Switzerland) or the UK.
2. **Storage and abuse monitoring.** Many providers keep prompts and outputs for a while to detect abuse, even when they do not train on them. Ask three questions:
   - Where is that copy stored?
   - For how long?
   - Can humans read it?
3. **Endpoint choice.** With several providers the same model is reachable through a global endpoint and an EU endpoint. Only the EU endpoint carries the commitment. One wrong `api_base` or region in `litellm/models.yaml` and the commitment is gone.
4. **Contract.** A data processing agreement (DPA) under GDPR Art. 28. See the [GDPR checklist](gdpr.md).
5. **Company jurisdiction.** Where the provider is incorporated can matter independently of where the data centre is. See [CLOUD Act and Data Privacy Framework](#cloud-act-and-data-privacy-framework-the-facts).

## Overview

| Provider | EU option (provider wording, short) | LiteLLM prefix | File in this repo |
|---|---|---|---|
| Azure OpenAI | `DataZoneStandard` deployment in an EU region | `azure/` | `examples/providers/azure-openai.yaml` |
| AWS Bedrock | `eu.` geo inference profile from `eu-central-1` | `bedrock/` | `examples/providers/aws-bedrock.yaml` |
| Google Vertex AI | location `eu` or an EU region | `vertex_ai/` | `examples/providers/google-vertex.yaml` |
| Mistral AI | `api.eu.mistral.ai` | `mistral/` | `examples/providers/mistral.yaml` (default in `litellm/models.yaml`) |
| OpenAI | `eu.api.openai.com`, needs approval | `openai/` | `examples/providers/openai-eu.yaml` |
| Anthropic API | no EU option | - | none |
| STACKIT | Germany and Austria only | `openai/` | `examples/providers/stackit.yaml` |
| IONOS | German data centres only | `openai/` | `examples/providers/ionos.yaml` |
| OVHcloud | Gravelines, France | `ovhcloud/` | `examples/providers/ovhcloud.yaml` |
| Scaleway | Paris, France | `scaleway/` | `examples/providers/scaleway.yaml` |
| T-Systems | open models on T-Cloud Germany | `openai/` | `examples/providers/t-systems.yaml` |
| Nebius | only dedicated endpoints have a region commitment | `nebius/` | none |
| Self-hosted | wherever your hardware is | `hosted_vllm/`, `ollama_chat/` | `examples/providers/self-hosted.yaml` |

## Switch the stack to another provider

The stack reads its models from `litellm/models.yaml` (pulled in by `include:` in `litellm/config.yaml`). The default file uses Mistral's EU endpoint. To use another provider:

1. Replace (or extend) the model list, for example `cp examples/providers/stackit.yaml litellm/models.yaml`.
2. Put the provider key into `.env`, for example `STACKIT_AI_TOKEN=...`. The variable names are listed at the top of each file and in `.env.example`.
3. Update `router_settings.fallbacks` in `litellm/config.yaml`. It refers to `mistral-medium` and `mistral-small`, which must exist in the new `models.yaml`.
4. Uncomment the `embedding` entry at the end of the provider file, or follow the note there.
5. Run the static checks, then recreate LiteLLM so it reads the new files and the new `.env` value:

```bash
.venv/bin/pytest tests/test_config_files.py
docker compose up -d --force-recreate litellm
```

The virtual environment is set up as in [Run the tests](quickstart.md#run-the-tests).

Keep three things in mind:

- **Only `model_list` belongs in `models.yaml`.** LiteLLM's `include:` merges top-level keys only. A list such as `model_list` is appended, but a dict such as `router_settings` is replaced by the included file (tested in this repo). Fallbacks, retries and all other settings therefore stay in `litellm/config.yaml`.
- **Open WebUI needs a model called `embedding`** for document search (`RAG_EMBEDDING_MODEL=embedding` in `compose.yaml`). Only `mistral.yaml` has an active one. The other files have a commented `embedding` entry (not tested in this repo) or a note on what to use instead. Without it, document upload fails and LiteLLM gives no warning.
- **Prices are part of the model entry.** If LiteLLM does not know a model's price, spend stays 0 and budgets never trigger (tested in this repo). See [Prices](#prices).

## Microsoft Azure OpenAI / Foundry

**What "EU" means.** Azure has several deployment types ("SKUs"), and the type decides where processing happens ([deployment types](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/deployment-types), as of 2026-10-16):

- `GlobalStandard` may process in any Azure region.
- `DataZoneStandard`, `DataZoneProvisionedManaged` and `DataZoneBatch` process within the Microsoft-defined data zone (US, EU, APAC).
- `Standard` and `ProvisionedManaged` process within the Azure geography of the resource.
- `DeveloperTier` has no data residency guarantee.

For a Data Zone deployment in an EU member state, Microsoft says data may be processed in that member state or any other EU member state ([data privacy](https://learn.microsoft.com/en-us/azure/ai-foundry/responsible-ai/openai/data-privacy)). The EU Data Zone follows the EU Data Boundary and can include EFTA countries (Norway, Switzerland). Microsoft can add regions to a data zone. Data at rest stays in the Azure geography. Prompts and completions are not available to OpenAI and are not used for training.

**Pitfalls.**

- **The Global SKU.** `GlobalStandard` is often the default in the portal and is cheaper (GPT-5: USD 1.25 / 10.00 per 1M tokens global versus 1.375 / 11.00 in the Data Zone). One deployment of the wrong type and requests can be processed anywhere. Microsoft documents an Azure Policy that denies `sku.name` equals `GlobalStandard`. Use it.
- **The deployment name tells LiteLLM nothing.** Azure deployment names are free text. `examples/providers/azure-openai.yaml` sets `model_info.base_model: azure/eu/gpt-5-2025-08-07`, which makes LiteLLM use the EU Data Zone price.
- **Claude on Foundry.** Anthropic's data residency page mentions only a US Data Zone for Claude on Microsoft Foundry. An EU Data Zone for Claude there: **not verified / not found**.

**Retention and abuse monitoring.** The abuse-monitoring data store sits in the customer's geography; for the EEA, human reviewers are located in the EEA. With "modified abuse monitoring", storage and human review are removed, automated review remains. It needs an application and is limited to customers managed by a Microsoft account team or an eligible program ([limited access](https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/openai/limited-access)). Check the result with `az cognitiveservices account show`: the capability `"ContentLogging": "false"` must be present. The retention period of abuse-monitoring data (often quoted as 30 days) is **not verified**: Microsoft's dedicated page returned HTTP 404 on 2026-10-16.

**Contract.** Microsoft Products and Services Data Protection Addendum (DPA).

**In this repo.** `examples/providers/azure-openai.yaml`, `.env`: `AZURE_API_KEY`, `AZURE_API_BASE` (`https://<resource>.openai.azure.com/`), `AZURE_API_VERSION`.

```yaml
  - model_name: gpt-5
    litellm_params:
      model: azure/<your-datazone-deployment-name>
      api_base: os.environ/AZURE_API_BASE
      api_version: os.environ/AZURE_API_VERSION
      api_key: os.environ/AZURE_API_KEY
    model_info:
      base_model: azure/eu/gpt-5-2025-08-07
```

Which `api_version` value to use today is **not verified**. LiteLLM's own docs still show older values such as `2024-08-01-preview`.

## AWS Bedrock

**What "EU" means.** Bedrock offers geo cross-region inference profiles with the prefix `eu.`, for example `eu.anthropic.claude-sonnet-4-6` or `eu.anthropic.claude-haiku-5-5` (Bedrock model cards, as of 2026-10-16). From the source region `eu-central-1` (Frankfurt) the EU profile routes to `eu-central-1`, `eu-north-1` (Stockholm), `eu-south-1` (Milan), `eu-south-2` (Spain), `eu-west-1` (Ireland) and `eu-west-3` (Paris). AWS states that model providers such as Anthropic have no access to Bedrock logs, prompts or completions, and that "your data is not shared with model providers, and is not used to improve the base models" ([Bedrock security](https://aws.amazon.com/bedrock/security-compliance/)).

**Pitfalls.**

- **The source region decides the destination list.** From `eu-central-2` the `eu.` profile also includes Zurich. From `eu-west-2` it also includes London. Switzerland and the UK are not EU member states. The example file therefore sets `aws_region_name: eu-central-1`.
- **Trust the API, not the prefix.** AWS advises checking the destinations with `GetInferenceProfile` from each source region instead of relying on the prefix ([inference profiles](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html)). Opt-in destination regions may store prompts for abuse detection. Service Control Policies (SCPs) can restrict the regions an account may use.

**Retention and abuse monitoring.** Bedrock has data retention modes, set per region at account or project level ([data retention](https://docs.aws.amazon.com/bedrock/latest/userguide/data-retention.html)):

- `none`: "No request or response data is written to durable storage by AWS or shared with the model provider." Requests to models that require retention are blocked.
- `default`: the model's policy applies. AWS may keep data for safety and abuse prevention; the model provider does not receive it.
- `aws_review`: kept for human review by AWS within the AWS boundary. Some providers require this mode.

The abuse detection page ([abuse detection](https://docs.aws.amazon.com/bedrock/latest/userguide/abuse-detection.html)) says Bedrock uses a zero-operator-access model. For OpenAI proprietary models, classifier-flagged traffic is kept up to 30 days (gpt-oss is exempt). For Claude Fable 5 / 5.1 (mode `aws_review` required), prompts and completions are retained for up to 30 days and may be reviewed by AWS staff. Retained data is stored in the destination region.

**Contract.** AWS Data Processing Addendum, referenced from the [AWS GDPR Center](https://aws.amazon.com/compliance/gdpr-center/).

**In this repo.** `examples/providers/aws-bedrock.yaml`, `.env`: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (the file suggests an IAM user that may call `bedrock:InvokeModel` only).

```yaml
  - model_name: claude-sonnet
    litellm_params:
      model: bedrock/eu.anthropic.claude-sonnet-4-6
      aws_region_name: eu-central-1
      aws_access_key_id: os.environ/AWS_ACCESS_KEY_ID
      aws_secret_access_key: os.environ/AWS_SECRET_ACCESS_KEY
```

## Google Vertex AI

Google now also brands Vertex AI as "Gemini Enterprise Agent Platform".

**What "EU" means** ([data residency](https://cloud.google.com/vertex-ai/generative-ai/docs/learn/data-residency), as of 2026-10-16): data at rest stays in the selected location. Regional endpoints keep ML processing in the jurisdiction. The `eu` multi-region covers EU member states only; the UK and Switzerland are excluded. Its endpoint is `https://aiplatform.eu.rep.googleapis.com`. In LiteLLM, `vertex_location: eu` resolves to that host (checked in the LiteLLM source).

**Pitfalls.**

- **The `global` endpoint gives no data residency guarantee.** It is also cheaper (Gemini 3.5 Flash: USD 1.50 / 9.00 global versus 1.65 / 9.90 non-global).
- **Not every model is in the EU.** Per Google's table: Gemini 4 Argon, Gemini 3.8 Flash, Gemini 3.5 Flash, Gemini 2.5 Pro and Flash and the embeddings are available in `eu`. Claude Sonnet 4.5 / 4.6, Opus 4.5 / 4.6 and Haiku 4.5 are in `eu` and `europe-west1`. Claude 5.x is in `eu` only. Claude Opus 4 / 4.1 has no EU location. Mistral Medium 3, Mistral Small 3.1 and Codestral 2 are in `eu` and `europe-west4`. Open models as a service (Llama, Qwen, gpt-oss, DeepSeek) have no EU location listed.
- **Grounding stores data.** Grounding with Google Search keeps data 3 days, grounding with Google Maps 30 days.

**Retention and abuse monitoring** ([data governance](https://cloud.google.com/vertex-ai/generative-ai/docs/data-governance)): no training on customer data without permission. Prompts may be logged for abuse monitoring; customers can request an exception for zero data retention. Request-response logging is off by default. The retention period of abuse-monitoring logs is **not verified**.

**Contract.** Cloud Data Processing Addendum (CDPA).

**In this repo.** `examples/providers/google-vertex.yaml`, `.env`: `VERTEX_PROJECT`, `VERTEX_CREDENTIALS` (path to a service account JSON inside the container).

```yaml
  - model_name: gemini-flash
    litellm_params:
      model: vertex_ai/gemini-2.5-flash
      vertex_project: os.environ/VERTEX_PROJECT
      vertex_location: eu
      vertex_credentials: os.environ/VERTEX_CREDENTIALS
```

`compose.yaml` does not mount a service account file into the `litellm` container. `.env.example` suggests `VERTEX_CREDENTIALS=/app/vertex-sa.json`, so you have to add that mount yourself, for example in a `compose.override.yaml` next to `compose.yaml` (both `compose.override.yaml` and `secrets/` are in `.gitignore`):

```yaml
services:
  litellm:
    volumes:
      - ./secrets/vertex-sa.json:/app/vertex-sa.json:ro
```

Keep the service account file in `./secrets/`, out of git. The example file uses LiteLLM's built-in list prices, which can be the lower global price. Add `input_cost_per_token` / `output_cost_per_token` from the [Vertex pricing page](https://cloud.google.com/vertex-ai/generative-ai/pricing) if budgets must be exact.

## Mistral AI

**What "EU" means** ([regional inference](https://docs.mistral.ai/inference/regional-inference.md), as of 2026-10-16): `api.eu.mistral.ai` processes in EU/EFTA data centres. `api.mistral.ai` is global, with no location commitment. Mistral says data is hosted in the EU by default and that some features transfer data under standard contractual clauses ([help article](https://help.mistral.ai/en/articles/347629)).

**Pitfalls.**

- **The default host is global.** Without `api_base: https://api.eu.mistral.ai/v1`, LiteLLM's `mistral/` provider talks to the global host. LiteLLM honours `api_base` for Mistral (checked in the LiteLLM source; it appends `/v1` if missing).
- **Not everything is regional.** Agents, Batch and Files are not available on the regional endpoint, and the control plane is not regional. Function calling is the only tool that is processed regionally.
- **Unsupported features void the guarantee.** Mistral's page says: "if a workload depends on an unsupported feature, the regional processing guarantees for that workload do not apply."
- **The EU endpoint costs 1.1x the list price.** LiteLLM's built-in price list has the global price, so `litellm/models.yaml` sets the EU prices explicitly.

**Retention and abuse monitoring.** API inputs and outputs are kept 30 rolling days for abuse monitoring unless zero data retention (ZDR) applies ([privacy policy](https://legal.mistral.ai/terms/privacy-policy/?lang=en)). ZDR is available for pay-as-you-go only, on stateless endpoints, and needs approval ([help article](https://help.mistral.ai/en/articles/347612)). Training opt-out: Admin > Privacy > "Anonymous improvement data".

**Contract.** [Mistral DPA](https://legal.mistral.ai/terms/data-processing-addendum/).

**In this repo.** Default in `litellm/models.yaml` (models `mistral-small`, `mistral-medium`, `embedding`); `examples/providers/mistral.yaml` adds `mistral-large`. `.env`: `MISTRAL_API_KEY`.

## OpenAI API with EU data residency

**What "EU" means** ([your data](https://platform.openai.com/docs/guides/your-data), as of 2026-10-16): the host `eu.api.openai.com` covers the EEA plus Switzerland, with regional storage and regional processing. TLS terminates in the region via Cloudflare Regional Services. API data is not used for training (since 1 March 2023) unless the customer opts in.

**Pitfalls.**

- **Not self-service.** EU residency requires sales eligibility, Modified Abuse Monitoring (MAM) or Zero Data Retention (ZDR), and a Modified Retention amendment. A normal API key on the EU host gets errors.
- **System data is excluded** from residency (for example account data).
- **Price uplift.** Models released on or after 5 March 2026 cost 10% more via EU residency.

**Retention and abuse monitoring.** Abuse logs are kept up to 30 days. ZDR and MAM need approval.

**Contract.** OpenAI's DPA page returned HTTP 403 to our automated fetch; its content is **not verified**.

**In this repo.** `examples/providers/openai-eu.yaml` (model `openai/gpt-5.6-terra`, `api_base: https://eu.api.openai.com/v1`), `.env`: `OPENAI_EU_API_KEY`. The file sets prices of LiteLLM's list price times 1.1.

## Anthropic API

**There is no EU option on Anthropic's first-party API.** The `inference_geo` parameter accepts only `"global"` or `"us"`, and the workspace geo is only `"us"` ([data residency](https://docs.claude.com/en/docs/build-with-claude/data-residency), as of 2026-10-16). Claude with EU processing is documented on [AWS Bedrock](#aws-bedrock) (`eu.` profiles) and [Google Vertex AI](#google-vertex-ai) (`eu`, `europe-west1`). This repo has no Anthropic API example for that reason.

## STACKIT

**What "EU" means.** STACKIT (Schwarz Digits) regions are exclusively in Germany (`eu01`) and Austria (`eu02`) ([regions](https://docs.stackit.cloud/platform/regions/)). The AI Model Serving FAQ says: "We do not store any customer data from the requests", and data is not used for training ([FAQ](https://docs.stackit.cloud/products/data-and-ai/ai-model-serving/faq/), as of 2026-10-16).

**Pitfalls.**

- **The double prefix.** There is no dedicated LiteLLM provider, so the model string is `openai/` plus the STACKIT model id, which itself can start with `openai/`: `openai/openai/gpt-oss-120b`.
- **No built-in prices, and EUR.** LiteLLM does not know these models. The example sets the EUR prices (0.45 / 0.65 per 1M tokens, net). See [Prices](#prices) for the currency rule.

**Contract.** DPA content **not verified** (not fetched).

**In this repo.** `examples/providers/stackit.yaml` (`gpt-oss-120b`, `llama-3.3-70b`), base URL `https://api.openai-compat.model-serving.eu01.onstackit.cloud/v1`, `.env`: `STACKIT_AI_TOKEN`.

## IONOS AI Model Hub

**What "EU" means** ([data handling](https://docs.ionos.com/cloud/ai/ai-model-hub/governance-and-compliance/data-handling.md), as of 2026-10-16): IONOS states that inference runs only in German data centres, and that prompts and outputs are never logged or stored and not used for training; only metadata is recorded. No third-party sub-processors, access by EU personnel only. Certifications: ISO 27001 and BSI C5. The DPA is part of the contract ("Datenschutzpaket").

**Pitfalls.** IONOS retires models regularly: Llama 3.1 8B on 15 October 2026, Mistral Nemo on 22 October 2026. Check the model list before you add a model.

**In this repo.** `examples/providers/ionos.yaml` (`gpt-oss-120b`, `llama-3.3-70b`), base URL `https://openai.inference.de-txl.ionos.com/v1`, prices in EUR, `.env`: `IONOS_API_TOKEN`.

## OVHcloud AI Endpoints

**What "EU" means.** Infrastructure in Gravelines, France. "Data is not stored or shared during or after model use" ([capabilities](https://docs.ovhcloud.com/en/guides/public-cloud/ai-machine-learning/ai-endpoints-capabilities), as of 2026-10-16). Data is never used to train models; only billing data is kept.

**Pitfalls.** LiteLLM's built-in prices for the two example models are 0.08 / 0.40 (gpt-oss-120b) and 0.67 / 0.67 (Llama 3.3 70B) per 1M tokens. These numbers match OVHcloud's EUR list prices, so treat spend for these models as EUR. OVHcloud's English page shows USD and the German page labels prices "inkl. MwSt."; we have not resolved that inconsistency.

**Contract.** DPA **not verified** (the data protection page returned HTTP 403).

**In this repo.** `examples/providers/ovhcloud.yaml`, `.env`: `OVHCLOUD_API_KEY`.

## Scaleway Generative APIs

**What "EU" means** ([FAQ](https://www.scaleway.com/en/docs/generative-apis/faq/), [data privacy](https://www.scaleway.com/en/docs/generative-apis/reference-content/data-privacy/), as of 2026-10-16): serverless models are hosted in Paris. Scaleway's FAQ says `api.scaleway.ai` stays in Europe. Zero data retention by default, no training. Scaleway states it is not subject to the US CLOUD Act.

**Retention.** Exception to ZDR: full requests may be stored up to two weeks on suspected misuse or HTTP 500 errors.

**Contract.** DPA **not verified** (not reviewed).

**In this repo.** `examples/providers/scaleway.yaml` (`mistral-small-3.2`, `gpt-oss-120b`), prices in EUR, `.env`: `SCW_SECRET_KEY`.

## T-Systems LLM Hub

**What "EU" means** ([models](https://docs.llmhub.t-systems.net/models/), as of 2026-10-16): open-source models run on T-Cloud in Germany; data is processed in the EU/EEA and not stored. No training regardless of model.

**Pitfalls.**

- **Proprietary models are forwarded.** GPT, Claude, Gemini and Mistral Medium are forwarded to Azure or GCP, which "may use sub-processors worldwide". T-Systems names the locations: GPT-5 in Azure Sweden, Claude on GCP Europe, Gemini 3 Pro worldwide. For EU-only processing, stay with the open models.
- **The path is `/v2`**, not `/v1`: `https://llm-server.llmhub.t-systems.net/v2`.
- **Prices are not public in a form we could verify.** The example file has commented-out price lines; enter your contract prices or budgets never trigger. Do not use 0 as a placeholder, LiteLLM treats an explicit 0 as free.

**In this repo.** `examples/providers/t-systems.yaml`, `.env`: `TSYSTEMS_LLMHUB_API_KEY`.

## Nebius Token Factory

No example file in this repo.

**What "EU" means** ([legal quick guide](https://docs.tokenfactory.nebius.com/legal/legal-quick-guide), as of 2026-10-16): public endpoints have no region commitment ("Global"). Only dedicated endpoints carry a contractual region commitment (DPA §6.1). Without ZDR, inputs and outputs are retained (for speculative decoding) and stored in Finland. ZDR is an organisation-level setting.

**Pitfalls.** LiteLLM's default base URL for `nebius/` is still the old `https://api.studio.nebius.ai/v1`, so set `api_base`. The data-plane host for `eu-west1` is `https://api.tokenfactory.eu-west1.nebius.com`; whether it needs a `/v1` suffix is **not verified**. Prices: **not verified**.

```yaml
  - model_name: nebius-eu-west1
    litellm_params:
      model: nebius/<model-id>
      api_base: https://api.tokenfactory.eu-west1.nebius.com/v1
      api_key: os.environ/NEBIUS_API_KEY
```

## Aleph Alpha PhariaAI

PhariaAI runs on-premise or hosted and offers an OpenAI-compatible `/chat/completions` endpoint. LiteLLM's `aleph_alpha` provider only lists the legacy luminous models, so use `openai/` with `api_base`. Cohere and Aleph Alpha have signed a combination agreement that is pending regulatory approval ([announcement](https://cohere.com/blog/cohere-and-aleph-alpha-sign-agreement), as of 2026-10-16). No example file in this repo.

## Self-hosted: vLLM and Ollama

Residency is wherever you run the hardware. `examples/providers/self-hosted.yaml` has one entry for each: `hosted_vllm/<model-id>` with `api_base: os.environ/VLLM_API_BASE`, and `ollama_chat/llama3.3` with `api_base: http://host.docker.internal:11434`. From inside the `litellm` container, `localhost` is the container itself, not the Docker host. LiteLLM cannot price your own GPUs; set a cost per token if budgets should mean something.

## Prices

List prices per 1M tokens for EU options, net of VAT unless stated, as of 2026-10-16.

| Provider / model (EU option) | Input | Output | Currency |
|---|---|---|---|
| Azure GPT-5, Data Zone (swedencentral) | 1.375 | 11.00 | USD |
| Azure GPT-5 mini, Data Zone (swedencentral) | 0.275 | 2.20 | USD |
| Azure GPT-4.1, Data Zone (swedencentral) | 2.20 | 8.80 | USD |
| Bedrock Claude Sonnet 5.5, `eu.` profile, eu-central-1 | 2.20 | 11.00 | USD |
| Bedrock Claude Haiku 5.5, eu-central-1 | 0.11 | 0.55 | USD |
| Bedrock Claude Sonnet 4.6, regional profile, eu-central-1 | 3.30 | 16.50 | USD |
| Bedrock gpt-oss-120b, eu-central-1 | 0.20 | 0.79 | USD |
| Vertex Gemini 3.5 Flash, non-global endpoint | 1.65 | 9.90 | USD |
| Mistral Small 4 (`mistral-small-2603`), global list price | 0.15 | 0.60 | USD |
| Mistral Medium 3.5 (`mistral-medium-3-5`), global list price | 1.50 | 7.50 | USD |
| STACKIT gpt-oss-120b / Llama 3.3 70B / Gemma 4 31B / Qwen3.8 27B | 0.45 | 0.65 | EUR (net) |
| IONOS gpt-oss-120b | 0.15 | 0.65 | EUR |
| IONOS Llama 3.3 70B | 0.65 | 0.65 | EUR |
| OVHcloud gpt-oss-120b | 0.08 | 0.40 | EUR (excl. VAT) |
| OVHcloud Llama 3.3 70B | 0.67 | 0.67 | EUR (excl. VAT) |
| Scaleway gpt-oss-120b | 0.15 | 0.60 | EUR |
| Scaleway llama-3.3-70b-instruct | 0.90 | 0.90 | EUR |
| Scaleway mistral-small-3.2-24b-instruct-2506 | 0.15 | 0.35 | EUR |

Sources: [Azure retail prices API](https://prices.azure.com/api/retail/prices), the AWS price list for eu-central-1, [Vertex pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing), [Mistral pricing](https://docs.mistral.ai/inference/pricing.md), [STACKIT](https://stackit.com/en/products/data-ai/stackit-ai-model-serving), [IONOS price list](https://docs.ionos.com/cloud/support/general-information/price-list/ionos-cloud-eur-en.md) (valid from 15 October 2026), [OVHcloud](https://www.ovhcloud.com/fr/public-cloud/prices/), [Scaleway](https://www.scaleway.com/en/pricing/model-as-a-service/).

Notes:

- **Mistral EU** costs 1.1x the table price: Small 0.165 / 0.66, Medium 1.65 / 8.25 USD. These are the values in `litellm/models.yaml`. Mistral Large 4 is on sale at USD 0.68 / 2.09 (regular 1.36 / 4.18).
- **Global versus EU.** The global options are cheaper: Azure GPT-5 global USD 1.25 / 10.00; Bedrock Sonnet 4.6 global 3.00 / 15.00 and Sonnet 5.5 global 2.00 / 10.00; Vertex Gemini 3.5 Flash global 1.50 / 9.00.
- **Vertex Gemini 4 Argon** non-global costs USD 2.20 / 11.00, a promo price through 30 November 2026 (regular 4.40 / 22.00). Which column of the Vertex pricing page we read (we assumed the Standard tier) is **not verified**.
- **Not collected:** OpenAI EU residency prices (the 10% uplift applies), T-Systems and Nebius prices (**not verified**).

**How LiteLLM uses prices.** These rules were tested in this repo:

- LiteLLM has a built-in price list in USD. For Mistral it holds the global price, so the EU price is set in `litellm/models.yaml`. For Azure, `model_info.base_model` points to the EU Data Zone price.
- Providers without built-in prices (STACKIT, IONOS, T-Systems, Scaleway, self-hosted) need `input_cost_per_token` and `output_cost_per_token`, otherwise spend stays 0 and budgets never trigger.
- LiteLLM has no currency field. EUR prices are just numbers. Do not mix EUR-priced and USD-priced models under one budget, or convert the prices first. The budget variables in `.env` (`USER_BUDGET_USD`, `OPENWEBUI_BUDGET_USD`) are named USD because the default models are priced in USD.
- Before each request LiteLLM reserves the worst-case cost against every budget the request counts toward. Without `max_tokens`, it reserves 16,384 output tokens (or the model maximum if that is lower). With Mistral Medium (8.25e-6 USD per output token) that is about 0.14 USD plus input per request. Keep budgets well above that.

## Combine providers with fallbacks

There are two ways to use several providers at once.

**Load balancing: same `model_name`, several entries.** Entries in `model_list` with the same `model_name` are load balanced. Users see one model in Open WebUI. Example: the same open model at two German providers.

```yaml
model_list:
  - model_name: gpt-oss-120b
    litellm_params:
      model: openai/openai/gpt-oss-120b
      api_base: https://api.openai-compat.model-serving.eu01.onstackit.cloud/v1
      api_key: os.environ/STACKIT_AI_TOKEN
      input_cost_per_token: 0.00000045
      output_cost_per_token: 0.00000065

  - model_name: gpt-oss-120b
    litellm_params:
      model: openai/openai/gpt-oss-120b
      api_base: https://openai.inference.de-txl.ionos.com/v1
      api_key: os.environ/IONOS_API_TOKEN
      input_cost_per_token: 0.00000015
      output_cost_per_token: 0.00000065
```

Several example files use the same names (`gpt-oss-120b` in five files, `llama-3.3-70b` in three, `claude-sonnet` in the Bedrock and Vertex files). If you paste two of them into `models.yaml`, the entries are load balanced, which may or may not be what you want. Rename one if you want separate models.

**Fallbacks: a second model when the first one fails.** Fallbacks are set in `router_settings` in `litellm/config.yaml` (not in `models.yaml`, because `include:` would replace the whole `router_settings` block). The default:

```yaml
router_settings:
  routing_strategy: simple-shuffle
  num_retries: 2
  allowed_fails: 3
  cooldown_time: 30
  fallbacks:
    - mistral-medium: ["mistral-small"]
```

A cross-provider version, for example Mistral EU first and STACKIT second, assuming both are in `models.yaml` under these names:

```yaml
  fallbacks:
    - mistral-medium: ["mistral-small", "gpt-oss-120b"]
```

What to watch:

- **A fallback can change the processing location.** Fall back only to models with the same residency level. A fallback from an EU model to a global endpoint defeats the purpose.
- **Fallbacks can be skipped silently near the end of a budget** (tested in this repo). LiteLLM reserves the primary model's worst-case cost first. If that reservation fills the remaining key budget, the configured fallback is skipped and the client sees the primary model's error. Setting `max_tokens` in the request, or budgets with headroom, avoids it. `general_settings.enforce_fallback_budget: false` also makes the fallback work, but then fallbacks to paid models are not budget-checked (LiteLLM issue #41344).
- **Do not mix currencies** across primary and fallback models under one budget.
- **Restrict who may use which provider.** A virtual key with a `models` list gets HTTP 403 for any other model, and the request never reaches the provider (tested in this repo).

## CLOUD Act and Data Privacy Framework: the facts

These are facts as of 2026-10-16, not an assessment.

**US CLOUD Act.** [18 U.S.C. § 2713](https://www.law.cornell.edu/uscode/text/18/2713) says a provider of electronic communication service or remote computing service "shall comply with the obligations of this chapter to preserve, backup, or disclose the contents of a wire or electronic communication and any record or other information pertaining to a customer or subscriber within such provider's possession, custody, or control, regardless of whether such communication, record, or other information is located within or outside of the United States." GDPR Art. 48 says a third-country court or authority decision requiring transfer or disclosure "may only be recognised or enforceable in any manner if based on an international agreement, such as a mutual legal assistance treaty". Azure, Bedrock, Vertex AI and the OpenAI API are run by US companies. Scaleway states it is not subject to the CLOUD Act.

**EU-US Data Privacy Framework (DPF).**

- Adequacy decision: Commission Implementing Decision (EU) 2023/1795 of 10 July 2023 ([EUR-Lex](https://eur-lex.europa.eu/eli/dec_impl/2023/1795/oj/eng)).
- The General Court dismissed the action against it in case T-553/23 Latombe v Commission on 3 September 2025 ([press release](https://curia.europa.eu/site/upload/docs/application/pdf/2025-09/cp250106en.pdf)).
- An appeal, C-703/25 P, was lodged on 31 October 2025 and seeks to annul the decision ([OJ C/2025/6610](https://eur-lex.europa.eu/eli/C/2025/6610/oj/eng)). A Court of Justice order of 4 June 2026 admitted an intervention. We found no judgment or Advocate General opinion; the curia case page was unavailable on 2026-10-16, so the current status is **not verified**.
- After the US Supreme Court decision Trump v. Slaughter (29 June 2026), the EDPB asked the Commission on 31 July 2026 "to closely assess whether this development affects the functioning of Commission Implementing Decision EU 2023/1795" ([EDPB letter](https://www.edpb.europa.eu/system/files/2026-08/edpb_letter_20260731_us_supremecourt_judgment_trump_v_slaughter_en.pdf)). The letter does not suspend the decision.
- On 30 June 2026 noyb asked the Commission to repeal the DPF and announced a court challenge ([noyb](https://noyb.eu/en/us-supreme-court-just-blew-eu-us-data-transfers)). Whether that action has been filed is **not verified**.
- The decision remains in force until repealed or annulled. We found no repeal as of 2026-10-16. Certified organisations are listed at [dataprivacyframework.gov](https://www.dataprivacyframework.gov/list/).

## Common problems

**Spend stays 0 and budgets never trigger.** The model has no price. Add `input_cost_per_token` and `output_cost_per_token` to the entry.

**Errors after switching `models.yaml`.** Read `docker compose logs litellm`. Check that the model names in `router_settings.fallbacks` in `litellm/config.yaml` still exist in the new file, and that every `os.environ/...` variable used in `models.yaml` is set in `.env`.

**OpenAI EU host returns errors.** A normal API key does not work on `eu.api.openai.com`. You need an EU residency project approved by OpenAI.

**Nebius requests go to the wrong host.** LiteLLM's default is the old `api.studio.nebius.ai`. Set `api_base`.

**T-Systems returns 404.** The base path is `/v2`.

**Vertex: credentials file not found.** Mount the service account JSON into the `litellm` container (see [Google Vertex AI](#google-vertex-ai)).

**Ollama not reachable.** Use `host.docker.internal` (Docker Desktop) or the bridge IP on Linux, not `localhost`.

**Document upload fails in Open WebUI after switching provider.** There is no model called `embedding`. Uncomment the entry in the provider file, or keep the Mistral `embedding` entry. `RAG_EMBEDDING_MODEL` is persisted by Open WebUI after the first start, so changing it in `.env` later needs the admin panel too.

## Related guides

- [GDPR checklist for an internal LLM gateway](gdpr.md)
- [PII masking with Presidio and LiteLLM](pii-masking.md)
- [LiteLLM budgets and rate limits](budgets.md)
- [LiteLLM config.yaml explained](configuration.md)
- [Quick start](quickstart.md)
- [Security policy and defaults](../SECURITY.md)

> **Note:** Technical information as of 16 October 2026, not legal advice; the authors are not lawyers or data protection officers. No guarantee of completeness or compliance. You remain the controller and must do your own assessment (DPIA, Art. 30 record, DPAs) with your data protection officer or a lawyer.
