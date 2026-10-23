"""
Seed script for Azure AZ-900 Flashcards Coach.
Inserts 14 hand-written flashcards across core AZ-900 topics with backs under 15 words.
Idempotent and safe to run repeatedly.
"""

from backend.db import get_db_connection, init_db

SEED_CARDS = [
    # Topic 1: Cloud Concepts
    {
        "topic_id": "cloud-concepts",
        "front": "What does Azure Blob Storage store?",
        "back": "Unstructured data such as files, images, and backups.",
        "type": "basic",
        "hint": "Massively scalable object storage"
    },
    {
        "topic_id": "cloud-concepts",
        "front": "What expenditure model does cloud computing shift IT costs towards?",
        "back": "Pay-as-you-go Operational Expenditure (OpEx).",
        "type": "basic",
        "hint": "CapEx vs OpEx"
    },
    {
        "topic_id": "cloud-concepts",
        "front": "In the cloud shared responsibility model, the customer always owns [...] and identities.",
        "back": "data",
        "type": "cloze",
        "hint": "Information & access"
    },
    {
        "topic_id": "cloud-concepts",
        "front": "What cloud model combines private on-premises infrastructure with public cloud bursting?",
        "back": "Hybrid cloud.",
        "type": "basic",
        "hint": "Mix of deployment models"
    },
    {
        "topic_id": "cloud-concepts",
        "front": "Cloud [...] is the ability to dynamically scale resources up or down to match demand.",
        "back": "elasticity",
        "type": "cloze",
        "hint": "Stretches and contracts automatically"
    },

    # Topic 2: Azure Architecture & Services
    {
        "topic_id": "azure-architecture",
        "front": "What is an Azure Availability Zone?",
        "back": "Physically separated datacenter with independent power, cooling, and network.",
        "type": "basic",
        "hint": "Resilience within an Azure region"
    },
    {
        "topic_id": "azure-architecture",
        "front": "An Azure Region consists of datacenters connected through a dedicated [...] latency network.",
        "back": "low",
        "type": "cloze",
        "hint": "Round-trip network delay"
    },
    {
        "topic_id": "azure-architecture",
        "front": "Which Azure service provides event-driven serverless compute?",
        "back": "Azure Functions.",
        "type": "basic",
        "hint": "Run code snippets without infrastructure"
    },
    {
        "topic_id": "azure-architecture",
        "front": "Which Blob Storage tier offers lowest storage cost for rarely accessed audit archives?",
        "back": "Archive tier.",
        "type": "basic",
        "hint": "Accepts several hours retrieval latency"
    },
    {
        "topic_id": "azure-architecture",
        "front": "An Azure [...] is a logical container that holds related resources for an Azure solution.",
        "back": "Resource Group",
        "type": "cloze",
        "hint": "Lifecycle and management boundary"
    },

    # Topic 3: Azure Management & Governance
    {
        "topic_id": "azure-management",
        "front": "What Azure service enforces organizational standards and assesses corporate compliance at scale?",
        "back": "Azure Policy.",
        "type": "basic",
        "hint": "Governance and guardrails"
    },
    {
        "topic_id": "azure-management",
        "front": "Azure [...] defines repeatable sets of resources combining ARM templates, RBAC, and policies.",
        "back": "Blueprints",
        "type": "cloze",
        "hint": "Standardized environment setup"
    },
    {
        "topic_id": "azure-management",
        "front": "What service securely stores application secrets, certificates, and cryptographic keys?",
        "back": "Azure Key Vault.",
        "type": "basic",
        "hint": "Centralized secret management"
    },
    {
        "topic_id": "azure-management",
        "front": "Which Azure tool provides personalized recommendations to optimize costs, security, and performance?",
        "back": "Azure Advisor.",
        "type": "basic",
        "hint": "Cloud optimization advisor"
    }
]


def seed_cards():
    """Seed flashcards into SQLite database idempotently."""
    init_db()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        for c in SEED_CARDS:
            cursor.execute(
                """
                INSERT INTO cards (topic_id, front, back, type, hint)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(front) DO UPDATE SET
                    topic_id = excluded.topic_id,
                    back = excluded.back,
                    type = excluded.type,
                    hint = excluded.hint;
                """,
                (c["topic_id"], c["front"], c["back"], c["type"], c.get("hint"))
            )
        conn.commit()
        count = conn.execute("SELECT COUNT(*) as count FROM cards").fetchone()["count"]
        print(f"Flashcards seeded successfully! Total cards in database: {count}")
    finally:
        conn.close()


if __name__ == "__main__":
    seed_cards()
