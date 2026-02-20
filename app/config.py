import os

REGION = os.getenv("REGION", "us")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://propuser:proppassword@db-us:5432/properties")
KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:29092")
KAFKA_TOPIC = "property-updates"
