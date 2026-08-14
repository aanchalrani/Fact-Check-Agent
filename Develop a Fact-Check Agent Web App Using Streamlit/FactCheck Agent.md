# FactCheck Agent

FactCheck Agent is a Python and Streamlit application that turns a fact-heavy PDF into an evidence review. It extracts page-traceable factual claims, searches the live web, compares claims with retrieved evidence, classifies findings as **Verified**, **Inaccurate**, or **False**, and exports a review-ready report in Markdown, CSV, JSON, or PDF.

> This tool is an evidence-assistance layer, not an autonomous publisher. Search results and source availability change over time, and important findings should be reviewed by a human before publication.

## Product flow

The application follows a five-stage workflow. It first validates and reads the uploaded PDF in memory. It then identifies independently checkable assertions such as statistics, dates, financial figures, and technical measurements, preserving page numbers when available. Next, it builds focused search queries and uses a live DuckDuckGo HTML search request to retrieve titles, snippets, URLs, and domains. Finally, it weighs the returned evidence with either an optional structured model or a deterministic fallback, shows the source trail, and serializes the final report.

The PDF pathway uses `pypdf` page extraction; the library documents that text extraction is not OCR and that scanned, image-only PDFs may require an OCR text layer [3]. The application therefore gives a clear remediation message when a PDF has too little extractable text rather than silently fabricating claims.

## Evidence and verdict policy

| Verdict | Meaning in the application | Typical action |
|---|---|---|
| **Verified** | Retrieved evidence supports the central factual assertion and its key figures or dates. | Retain, while checking the cited source in context. |
| **Inaccurate** | Reliable evidence points to a material error, outdated value, wrong date, or missing qualification. | Correct or qualify the claim before publication. |
| **False** | The claim is contradicted by the retrieved evidence or no reliable evidence supports it. | Remove, replace, or escalate for human review. |

The no-key mode uses live search plus deterministic scoring, including number and date comparisons, source-domain reliability signals, and text overlap. When `OPENAI_API_KEY` is configured, the app uses a structured model call for claim extraction and evidence adjudication, while still displaying the original search sources and never allowing the model to invent a source URL.

## Repository structure

| Path | Purpose |
|---|---|
| `app.py` | Streamlit interface, session state, workflow controls, findings dashboard, and downloads. |
| `factcheck/pdf_utils.py` | PDF parsing, page mapping, heuristic claim extraction, and optional model extraction. |
| `factcheck/web_search.py` | Live search, URL normalization, source metadata, and reliability signals. |
| `factcheck/verification.py` | Evidence comparison, model adjudication, deterministic fallback, and verdict creation. |
| `factcheck/reports.py` | Markdown, CSV, JSON, and PDF report exporters. |
| `factcheck/models.py` | Typed dataclasses for claims, sources, results, and reports. |
| `tests/test_factcheck.py` | Automated regression tests for extraction, numeric contradiction detection, and exports. |
| `Dockerfile` | Non-root production container with a health check. |
| `render.yaml` | Render deployment blueprint for a public HTTPS service. |
| `.streamlit/config.toml` | Safe upload, headless server, CORS/XSRF, and visual configuration. |

## Local run

Create a virtual environment, install the pinned dependencies, and start Streamlit from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

The browser will open the local Streamlit URL. To enable model-assisted extraction and adjudication, copy `.env.example` to `.env` and export the values in the process environment. The app remains usable without a model key because live search and deterministic scoring are built in.

Run the automated tests with:

```bash
PYTHONPATH=. pytest -q
```

## Configuration

| Variable | Required | Description |
|---|---:|---|
| `OPENAI_API_KEY` | No | Enables model-assisted claim extraction and evidence adjudication. |
| `OPENAI_API_BASE` | No | OpenAI-compatible API base; defaults to `https://api.openai.com/v1`. |
| `OPENAI_MODEL` | No | Model name; defaults to `gpt-4o-mini`. |

Secrets must be configured in the hosting provider's secret manager or environment settings. Never commit `.env`, `.streamlit/secrets.toml`, or an API key to the repository.

## Deployment options

| Approach | Tradeoffs | Cost | Setup complexity |
|---|---|---:|---:|
| **Render using `render.yaml`** | Public HTTPS deployment with a Docker runtime and health check; free instances may sleep when idle, so the first request can be slower. | Free tier available; paid instances are optional. | Low after the repository is connected. |
| **Streamlit Community Cloud** | Simplest Streamlit-native hosting and secrets UI; requires a GitHub repository and an account with permission to deploy it. | Free tier available. | Low, but account authorization is required. |
| **Docker on an existing server** | Maximum control and predictable uptime, but the operator owns TLS, updates, monitoring, and firewall configuration. | Depends on the server. | Medium to high. |

For this repository, Render is the portable default because `render.yaml` and the Dockerfile make the runtime explicit. Streamlit Community Cloud is equally suitable when the repository owner prefers a Streamlit-native deployment flow.

### Render deployment

Create a repository containing this project, connect it to Render, and choose **Blueprint** deployment so Render reads `render.yaml`. In the service environment settings, add `OPENAI_API_KEY` if model-assisted analysis is wanted. The service health endpoint is `/_stcore/health`; the container listens on port `8501`. After the first successful build, Render provides a public HTTPS URL that can be shared with evaluators.

### Streamlit Community Cloud deployment

Push the repository to GitHub, create a new app in Streamlit Community Cloud, select the repository and `app.py` entry point, and add the optional environment variables in the app's secrets or environment settings. The repository already includes `requirements.txt`, `.streamlit/config.toml`, and a headless configuration suitable for hosted execution.

## Evaluation with a trap document

Upload a PDF containing a mixture of correct facts, changed dates, and intentionally wrong statistics. The app should extract the numerical assertions, allow the evaluator to deselect irrelevant candidates, and then surface the strongest findings in the **Results** tab. For each finding, verify that the UI displays the verdict, confidence, rationale, correction or context when available, live search queries, source domain, source type, reliability signal, and clickable URL. Download the Markdown or PDF report and confirm that the report preserves the same claim-to-source trail.

## Production safeguards

The app caps uploads at 20 MB, refuses empty or unextractable PDFs, uses request timeouts for external calls, avoids persisting the uploaded file, limits the number of claims and sources processed per run, uses a non-root container user, and includes a health check. The UI makes the optional-model boundary visible so an evaluator can distinguish deterministic fallback mode from model-assisted mode.

## References

[1]: https://docs.streamlit.io/develop/api-reference/widgets/st.file_uploader "Streamlit st.file_uploader documentation"

[2]: https://docs.streamlit.io/develop/api-reference/widgets/st.download_button "Streamlit st.download_button documentation"

[3]: https://pypdf.readthedocs.io/en/latest/user/extract-text.html "pypdf text extraction documentation"
