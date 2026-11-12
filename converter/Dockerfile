FROM python:3.12-slim
ARG APT_MIRROR=deb.debian.org
RUN sed -i "s/deb.debian.org/$APT_MIRROR/g" /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-impress libreoffice-core fonts-dejavu fonts-liberation fonts-crosextra-carlito \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 converter && mkdir /convert && chown converter /convert
COPY convert.sh /usr/local/bin/convert.sh
USER converter
CMD ["/usr/local/bin/convert.sh"]
