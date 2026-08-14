# Deployment status

## Live validation endpoint

The application is currently reachable at:

[Open FactCheck Agent](https://8501-iko97mn1ph576ru6gbwe6-e43209af.sg1.manus.computer)

This endpoint is a public sandbox proxy over the running Streamlit process. It is suitable for immediate evaluator testing while the sandbox remains active, but it is not a durable production host and may disappear when the sandbox is stopped.

## Durable deployment path

The repository includes `Dockerfile` and `render.yaml` for a durable Render deployment. Connect the repository to Render, select Blueprint deployment, and add `OPENAI_API_KEY` only if model-assisted analysis is required. The container health endpoint is `/_stcore/health`, and the service listens on port `8501`.

The account-side GitHub publishing connection was not authorized in this session, so the project could not be pushed to a repository or attached to Render/Streamlit Community Cloud automatically. The remaining step is to publish `/home/ubuntu/fact_check_agent` to a Git repository that the evaluator controls, then connect that repository using either Render Blueprint deployment or Streamlit Community Cloud.

## Validation completed

The live endpoint renders the upload workflow. The automated suite passes, the no-key path successfully extracts a trap PDF and classifies the sample facts as Verified, Inaccurate, and Verified, the live evidence layer is reachable, and the optional structured model path was smoke-tested successfully. Reports are generated as Markdown, CSV, JSON, and PDF from the same typed result model.
