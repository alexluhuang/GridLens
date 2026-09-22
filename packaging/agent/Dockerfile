ARG ANALYSIS_BASE
FROM ${ANALYSIS_BASE}
USER root
RUN if [ -d /opt/conda ]; then chmod a+rx /opt/conda /opt/conda/bin /opt/conda/lib; fi
LABEL org.gridlens.purpose="generated-analysis"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 NVIDIA_VISIBLE_DEVICES=void
ENV PATH="/opt/conda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ENTRYPOINT ["python", "-I", "-B"]
