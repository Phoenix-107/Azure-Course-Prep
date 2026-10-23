"""
Database management and seeding script for Azure AZ-900 Scholar Prep.
Creates the SQLite database schema and seeds initial core topics and high-quality AZ-900 questions.
"""

import json
import os
import sqlite3
from pathlib import Path

# Base directory for database persistence
BASE_DIR = Path(__file__).resolve().parent.parent
DB_DIR = BASE_DIR / "data"
DB_PATH = DB_DIR / "app.db"


def get_db_connection() -> sqlite3.Connection:
    """Return an active connection with Row factory enabled."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    """Create tables and seed initial data if needed."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Topics Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS topics (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        weight REAL DEFAULT 1.0
    );
    """)

    # 2. Chunks Table (for future LLM RAG pipelines)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        note_name TEXT,
        topic_id TEXT REFERENCES topics(id),
        text TEXT NOT NULL
    );
    """)

    # 3. Questions Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chunk_id INTEGER REFERENCES chunks(id),
        topic_id TEXT REFERENCES topics(id),
        question TEXT NOT NULL UNIQUE,
        options_json TEXT NOT NULL,
        answer_index INTEGER NOT NULL,
        explanation TEXT,
        source_quote TEXT,
        is_mock INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 4. Attempts Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        question_id INTEGER REFERENCES questions(id),
        topic_id TEXT,
        correct INTEGER NOT NULL,
        mode TEXT,
        answered_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_attempts_user_topic ON attempts(user_id, topic_id);
    """)

    # --- SEED TOPICS ---
    topics_seed = [
        ("cloud-concepts", "Describe cloud concepts", 1.0),
        ("azure-architecture", "Azure architecture & services", 1.2),
        ("azure-management", "Azure management & governance", 1.0),
    ]

    for topic_id, name, weight in topics_seed:
        cursor.execute("""
        INSERT INTO topics (id, name, weight)
        VALUES (?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            weight = excluded.weight;
        """, (topic_id, name, weight))

    # --- SEED QUESTIONS (Realistic AZ-900 Exam Style) ---
    seed_questions = [
        # Topic 1: Cloud Concepts
        {
            "topic_id": "cloud-concepts",
            "question": "Which cloud computing deployment model allows an organization to host critical workloads on private infrastructure while bursting to the public cloud during peak demand?",
            "options": [
                "Public cloud only",
                "Private cloud only",
                "Hybrid cloud",
                "Multi-tenant bare metal"
            ],
            "answer_index": 2,
            "explanation": "A hybrid cloud combines on-premises infrastructure (or private cloud) with public cloud services, allowing data and applications to be shared between them. This enables cloud bursting during peak traffic.",
            "source_quote": "A hybrid cloud combines public and private clouds, allowing apps and data to be shared between them.",
            "is_mock": 1
        },
        {
            "topic_id": "cloud-concepts",
            "question": "Under the cloud Shared Responsibility Model, which component is ALWAYS the customer's responsibility across IaaS, PaaS, and SaaS?",
            "options": [
                "Physical datacenter security",
                "Information, data, and user access management",
                "Operating system patching",
                "Virtual network infrastructure"
            ],
            "answer_index": 1,
            "explanation": "Regardless of the cloud service model (IaaS, PaaS, or SaaS), the customer always retains responsibility for securing their data, information, endpoints, and identity/access management.",
            "source_quote": "In all cloud deployment types, you own your data and identities. You are responsible for protecting the security of your data and identities.",
            "is_mock": 1
        },
        {
            "topic_id": "cloud-concepts",
            "question": "How does shifting IT infrastructure from an on-premises datacenter to Microsoft Azure primarily affect financial expenditure?",
            "options": [
                "Increases Capital Expenditure (CapEx) while eliminating Operational Expenditure (OpEx)",
                "Converts ongoing Operational Expenditure (OpEx) into large upfront Capital Expenditure (CapEx)",
                "Shifts upfront Capital Expenditure (CapEx) to a pay-as-you-go Operational Expenditure (OpEx) model",
                "Requires upfront full licensing purchases with zero recurring costs"
            ],
            "answer_index": 2,
            "explanation": "Cloud computing moves expenses from CapEx (spending money upfront on physical infrastructure and servers) to OpEx (spending money on services and products as they are consumed).",
            "source_quote": "Cloud computing shifts the financial model from upfront Capital Expenditure (CapEx) to continuous Operational Expenditure (OpEx).",
            "is_mock": 1
        },

        # Topic 2: Azure Architecture & Services
        {
            "topic_id": "azure-architecture",
            "question": "Which Azure architectural component consists of one or more physical datacenters equipped with independent power, cooling, and networking within an Azure region?",
            "options": [
                "Resource Group",
                "Availability Zone",
                "Azure Geography",
                "Management Group"
            ],
            "answer_index": 1,
            "explanation": "An Availability Zone is a physically separate location within an Azure region. Each zone is made up of one or more datacenters equipped with independent power, cooling, and networking infrastructure.",
            "source_quote": "Availability Zones are physically separate datacenters within an Azure region, each with independent power, cooling, and networking.",
            "is_mock": 1
        },
        {
            "topic_id": "azure-architecture",
            "question": "An engineering team needs to host serverless code snippets that trigger automatically in response to HTTP requests or database changes without provisioning any servers. Which Azure service is the best fit?",
            "options": [
                "Azure Virtual Machines",
                "Azure Functions",
                "Azure Kubernetes Service (AKS)",
                "Azure Virtual Desktop"
            ],
            "answer_index": 1,
            "explanation": "Azure Functions is an event-driven serverless compute service that enables developers to run event-triggered code without having to explicitly provision or manage infrastructure.",
            "source_quote": "Azure Functions is a serverless compute service that lets you run event-triggered code without explicitly provisioning or managing infrastructure.",
            "is_mock": 1
        },
        {
            "topic_id": "azure-architecture",
            "question": "Which Azure Blob Storage access tier provides the lowest storage cost for data that is rarely accessed and can tolerate a retrieval latency of several hours?",
            "options": [
                "Hot Tier",
                "Cool Tier",
                "Cold Tier",
                "Archive Tier"
            ],
            "answer_index": 3,
            "explanation": "The Archive tier offers the lowest storage cost per gigabyte, but has higher data retrieval costs and latency (data must be rehydrated, taking up to several hours). It is designed for long-term audit backups.",
            "source_quote": "The Archive tier has the lowest storage cost and highest retrieval costs compared to hot and cool tiers, with latency of several hours.",
            "is_mock": 1
        },

        # Topic 3: Azure Management & Governance
        {
            "topic_id": "azure-management",
            "question": "What Azure tool enables administrators to enforce organizational standards, assess compliance, and prevent users from deploying non-compliant resources (such as VMs in disallowed regions)?",
            "options": [
                "Azure Policy",
                "Azure Key Vault",
                "Azure Advisor",
                "Azure Bastion"
            ],
            "answer_index": 0,
            "explanation": "Azure Policy helps to enforce organizational standards and to assess compliance at-scale. It can enforce governance rules like allowed locations, SKU sizes, or required resource tags.",
            "source_quote": "Azure Policy evaluates your resources and flags those that not comply with corporate standards.",
            "is_mock": 1
        },
        {
            "topic_id": "azure-management",
            "question": "Which statement accurately describes an Azure Resource Group?",
            "options": [
                "A resource can belong to multiple Resource Groups at the same time",
                "Resources in a Resource Group must all reside in the exact same region as the Resource Group",
                "It serves as a logical container for managing and grouping related Azure resources together",
                "Deleting a Resource Group retains all child resources in an unmanaged state"
            ],
            "answer_index": 2,
            "explanation": "A Resource Group is a container that holds related resources for an Azure solution. A resource can only belong to one Resource Group at a time, and resources can reside in different geographic regions.",
            "source_quote": "A resource group is a container that holds related resources for an Azure solution.",
            "is_mock": 1
        },
        {
            "topic_id": "azure-management",
            "question": "Which Azure governance feature allows you to define a repeatable set of Azure resources that adheres to an organization's standards, patterns, and security requirements by combining ARM templates, Role assignments, and Policies?",
            "options": [
                "Azure Blueprints",
                "Azure Service Health",
                "Azure Arc",
                "Azure Monitor"
            ],
            "answer_index": 0,
            "explanation": "Azure Blueprints enables cloud architects to define a repeatable set of Azure resources that implement and adhere to an organization's standards, patterns, and requirements (composed of Resource Groups, Policy assignments, Role assignments, and ARM templates).",
            "source_quote": "Azure Blueprints enables cloud architects to define a repeatable set of Azure resources that implement and adhere to standards and patterns.",
            "is_mock": 1
        }
    ]

    for q in seed_questions:
        cursor.execute("""
        INSERT INTO questions (topic_id, question, options_json, answer_index, explanation, source_quote, is_mock)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(question) DO UPDATE SET
            topic_id = excluded.topic_id,
            options_json = excluded.options_json,
            answer_index = excluded.answer_index,
            explanation = excluded.explanation,
            source_quote = excluded.source_quote,
            is_mock = excluded.is_mock;
        """, (
            q["topic_id"],
            q["question"],
            json.dumps(q["options"]),
            q["answer_index"],
            q["explanation"],
            q["source_quote"],
            q["is_mock"]
        ))

    conn.commit()
    conn.close()
    print("Database schema verified and seed data populated successfully.")


if __name__ == "__main__":
    init_db()
