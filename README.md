docker run -p 4317:4317 \
 -v ./otel-collector-config.yaml:/etc/otel-collector-config.yaml \
 otel/opentelemetry-collector:latest \
 --config=/etc/otel-collector-config.yaml
