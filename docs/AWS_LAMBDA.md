# AWS Lambda demo deployment

This deployment is deliberately retrieval-only. It packages the NIST corpus and
serves the FastAPI dashboard through a public Lambda Function URL. It does not
store an LLM key in AWS and it does not run semantic retrieval, so the Lambda
package stays small and the demo remains within a low-cost, free-plan-friendly
footprint.

## Architecture

Browser -> Lambda Function URL -> FastAPI / SQLite FTS5 -> NIST citations

The packaged database is copied into Lambda's writable `/tmp` directory at cold
start so query traces can be recorded without altering the deployment package.

## Build the deployment ZIP

Run this command from the repository root with Python 3.12 or later. The script
targets the Linux CPython 3.12 wheels required by Lambda, even when it runs on
Windows.

```powershell
python scripts/build_lambda_zip.py
```

## AWS console settings

- Runtime: Python 3.12 on x86_64
- Handler: `app.lambda_handler.handler`
- Memory: 512 MB
- Timeout: 15 seconds
- Function URL: `NONE` authorization for the public portfolio demo
- CORS: allow `GET`, `POST`, and `OPTIONS` from `*`
- Environment: leave LLM keys unset for this retrieval-only deployment

After deployment, open the Function URL, run a source-grounded query, and keep
the URL in the README and resume only after it is verified publicly.
