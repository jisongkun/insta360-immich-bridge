FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC
ENV VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH
ARG MEDIA_SDK_DEB=vendor/MediaSDK-3.1.5-linux-amd64.deb
ARG MEDIA_SDK_SHA256=444b4b0bc22aa5335e5cc2c3dd092b16207f3a7c19bb7fe97799e94eca69325e
COPY ${MEDIA_SDK_DEB} /tmp/MediaSDK.deb
COPY requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get -o Acquire::Retries=3 update \
    && apt-get -o Acquire::Retries=3 install -y --no-install-recommends ca-certificates \
    && sed -i "s|http://|https://|g" /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get -o Acquire::Retries=3 update && apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
      python3 python3-venv git ca-certificates tzdata \
      libimage-exiftool-perl ffmpeg \
    && echo "$MEDIA_SDK_SHA256  /tmp/MediaSDK.deb" | sha256sum -c - \
    && apt-get install -y /tmp/MediaSDK.deb \
    && python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt \
    && test -x /opt/MediaSDK-3.1.5-linux/bin/MediaSDKTest \
    && rm -rf /var/lib/apt/lists/* /tmp/MediaSDK.deb /tmp/requirements.txt

WORKDIR /opt/insta360
COPY auto-sticher.py convert_job.py ./
COPY bridge ./bridge
ENV BRIDGE_CONFIG=/config/bridge-config.json BRIDGE_PORT=8008
EXPOSE 8008
CMD ["python3", "-m", "bridge"]
