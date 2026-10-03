/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
import type { AuditEvent } from '../lib/audit.js';
import { query, sql } from '../lib/db.js';

export async function insertAudit(event: AuditEvent): Promise<void> {
  await query(sql`
    INSERT INTO audit_events (type, actor_id, subject_id, meta)
    VALUES (${event.type}, ${event.actorId}, ${event.subjectId}, ${JSON.stringify(event.meta ?? {})})`);
}

export async function enqueueOutbox(topic: string, payload: Record<string, unknown>): Promise<void> {
  await query(sql`INSERT INTO outbox (topic, payload) VALUES (${topic}, ${JSON.stringify(payload)})`);
}
