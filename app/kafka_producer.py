import json
import logging
from kafka import KafkaProducer
from config import KAFKA_BROKER, KAFKA_TOPIC

logger = logging.getLogger(__name__)

_producer = None

def get_producer():
    global _producer
    if _producer is None:
        _producer = KafkaProducer(
            bootstrap_servers=[KAFKA_BROKER],
            value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
            acks="all",
            retries=3,
        )
    return _producer

def publish_update(property_dict: dict):
    """Publish a property update event to Kafka."""
    try:
        producer = get_producer()
        future = producer.send(KAFKA_TOPIC, value=property_dict)
        producer.flush()
        record_metadata = future.get(timeout=10)
        logger.info(
            "Published to %s [partition %d] offset %d",
            record_metadata.topic,
            record_metadata.partition,
            record_metadata.offset,
        )
    except Exception as e:
        logger.error("Failed to publish Kafka message: %s", e)
        raise
