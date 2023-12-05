import logging
from flask import Flask, render_template, request, jsonify
from flask_opentracing.tracing import tags
from prometheus_flask_exporter.multiprocess import GunicornInternalPrometheusMetrics
from flask_opentracing import FlaskTracing
from jaeger_client import Config
from jaeger_client.metrics.prometheus import PrometheusMetricsFactory
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor

import pymongo
from flask_pymongo import PyMongo

app = Flask(__name__)
metrics = GunicornInternalPrometheusMetrics(app)

app.config["MONGO_DBNAME"] = "example-mongodb"
app.config[
    "MONGO_URI"
] = "mongodb://example-mongodb-svc.default.svc.cluster.local:27017/example-mongodb"

logging.getLogger("").handlers = []
logging.basicConfig(format="%(message)s", level=logging.DEBUG)
logger = logging.getLogger(__name__)

mongo = PyMongo(app)


def init_tracer(service):
    config = Config(
        config={
            "sampler": {"type": "const", "param": 1},
            "logging": True,
            "reporter_batch_size": 1,
        },
        service_name=service,
        validate=True,
        metrics_factory=PrometheusMetricsFactory(service_name_label=service),
    )

    # this call also sets opentracing.tracer
    return config.initialize_tracer()


tracer = init_tracer("backend-service")
if tracer is None:
    raise Exception("No tracer")
flask_tracker = FlaskTracing(tracer, True, app)

by_path_counter = metrics.counter(
    "by_path_counter",
    "Request count by request paths",
    labels={"path": lambda: request.path},
)

histogram = metrics.histogram(
    "requests_by_status_and_path",
    "Requests latency by status and path",
    labels={"status": lambda r: r.status_code, "path": lambda: request.path},
)

@app.route("/")
@by_path_counter
@histogram
def homepage():
    with tracer.start_span("homepage") as span:
        res = "Hello World"
        span.set_tag("homepage", res)
        return res


@app.route("/api")
@by_path_counter
@histogram
def my_api():
    with tracer.start_span("api") as span:
        answer = "something"
        span.set_tag("answer", answer)
        return jsonify(repsonse=answer)


@app.route("/star", methods=["POST"])
@by_path_counter
@histogram
def add_star():
    with tracer.start_span("star") as span:
        try:
            star = mongo.db.stars
            name = request.json["name"]
            distance = request.json["distance"]
            star_id = star.insert({"name": name, "distance": distance})
            new_star = star.find_one({"_id": star_id})
            output = {"name": new_star["name"], "distance": new_star["distance"]}

            response = jsonify({"result": output})
            span.set_tag("message", response)
            return response
        except Exception as e:
            logger.error("Unable to get data from database")
            span.set_tag(tags.ERROR, e)


if __name__ == "__main__":
    app.run(debug=False)
