ARG ANALYSIS_BASE
FROM ${ANALYSIS_BASE}
LABEL org.gridlens.purpose="generated-analysis"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 NVIDIA_VISIBLE_DEVICES=void
ENV PATH="/opt/conda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ENTRYPOINT ["python", "-I", "-B"]
