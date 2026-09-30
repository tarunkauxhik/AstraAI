# The sandbox for DEVELOP runs: Python 3.12 and a pinned pytest, nothing else. Repository
# tests run here with no network, so nothing is ever installed at run time.
#
#   docker build -t astraai-sandbox-python:3.12.14-pytest9.1.1 backend/sandbox
FROM python:3.12.14-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea

RUN pip install --no-cache-dir --no-deps \
        pytest==9.1.1 iniconfig==2.3.0 packaging==26.3 pluggy==1.6.0 pygments==2.21.0
