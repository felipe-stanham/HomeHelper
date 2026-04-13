# Testing Before Deploying to TST

Always test changes in the DEV (local) environment first before deploying to TST. Do not deploy to TST until explicitly asked.

## Why

In an early session, code was deployed directly to TST without local testing, which caused two rounds of broken deployments (SSE handler signature issues). Local testing would have caught the errors before they reached the remote server.

## Steps

1. Run the unit test suite: `python3 -m pytest tests/ -v --tb=short --no-cov`
2. If the change involves runtime behavior (servers, endpoints, etc.), spin up the dev server locally (`ENV=dev python -m uvicorn latarnia.main:app --host 0.0.0.0 --port 8000 --app-dir src`) and verify manually
3. Only after local tests pass, deploy to TST when the user asks
4. Never skip straight to TST deployment, even for "obvious" fixes
