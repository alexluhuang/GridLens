# check=skip=InvalidDefaultArgInFrom
# Sandbox image for approved generated scripts; see README.md in this directory. ANALYSIS_BASE has no default on
# purpose: src/gridlens/agent/scripts.py accepts only an immutable sha256 image ID, so a floating default tag here
# would contradict that pin. Build (the --build-arg is required, a bare `docker build` fails by design):
#   docker build --build-arg ANALYSIS_BASE=<base image pinned by digest, with pandas and pyarrow> -t gridlens-analysis:0.1.0 packaging/agent
#   docker image inspect gridlens-analysis:0.1.0 --format '{{.Id}}'
ARG ANALYSIS_BASE
FROM ${ANALYSIS_BASE}
USER root
RUN if [ -d /opt/conda ]; then chmod a+rx /opt/conda /opt/conda/bin /opt/conda/lib; fi
LABEL org.gridlens.purpose="generated-analysis"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 NVIDIA_VISIBLE_DEVICES=void
ENV PATH="/opt/conda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ENTRYPOINT ["python", "-I", "-B"]
# Last USER wins, so the image itself defaults to nobody for any use outside GridLens; GridLens always passes --user.
USER 65534:65534
