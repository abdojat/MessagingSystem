# Project Overview

## Academic purpose

The project demonstrates a distributed publish/subscribe messaging architecture. Publishers send messages to persistent channels/topics; authorized subscribers receive live notifications and can recover missed messages from durable storage. The web interface is the demonstration client, not the system's architectural identity.

## Problem addressed

Direct point-to-point messaging tightly couples senders and receivers and makes fanout, offline recovery, and subscriber management harder to explain and scale. This project separates durable application state from asynchronous delivery:

- publishers write once to a channel;
- channel membership defines the subscriber set;
- PostgreSQL commits the message and transactional outbox;
- RabbitMQ routes committed events asynchronously;
- Redis and WebSockets provide low-latency online delivery;
- REST history and sync recover missed data.

## System scope

The final MVP includes:

- user registration, login, session lifecycle, and email verification;
- public/private channel creation and management;
- invitations, join requests, approvals, roles, and permissions;
- encrypted persistent messages and protected encrypted attachments;
- outbox-driven RabbitMQ delivery, retries, dead-letter visibility, Redis fanout, WebSockets, and offline sync;
- event/activity logs and superadmin operational views;
- SHA-256 audit hash chains and the supervisor-mandated Merkle-tree checkpoint/proof system;
- development, hardened-demo, and single-host production-oriented Docker Compose profiles.

## Main contribution

The repository combines a realistic distributed delivery pipeline with a defendable security and integrity story while retaining PostgreSQL as the source of truth. It demonstrates that realtime infrastructure may be unavailable or bounded without losing persistent message history.

The audit design deliberately combines three complementary controls:

1. Per-scope hash chains preserve ordered event continuity.
2. Merkle trees produce compact membership proofs for checkpoint batches.
3. Ed25519 signatures bind checkpoint roots to an independently held signing identity.

An exported latest anchor adds rollback evidence only when the operator retains it outside the application/database host.

## Scope boundaries

This is a final university MVP, not an enterprise messaging product. It does not claim end-to-end encryption, immutable/blockchain storage, automatic external notarization, multi-host high availability, managed key custody, production load certification, or a complete observability platform.

For implementation detail, see [Architecture](ARCHITECTURE.md). For requirement evidence, see [Requirements Mapping](REQUIREMENTS_MAPPING.md).
