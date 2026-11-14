FROM apify/actor-python:3.13
USER myuser
COPY --chown=myuser:myuser requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# Bake the default Whisper model into the image so the opt-in fallback has no cold download
ENV HF_HUB_DISABLE_TELEMETRY=1
RUN python3 -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8')"
COPY --chown=myuser:myuser . ./
RUN python3 -m compileall -q src/
CMD ["python3", "-m", "src"]
