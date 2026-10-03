/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
import * as eventRepository from '../repositories/eventRepository.js';
import { logger } from './logger.js';

const log = logger.child({ module: 'audit' });

export interface AuditEvent {
  type: string;
  actorId: string;
  subjectId: string;
  meta?: Record<string, unknown>;
}

/**
 * Appends an event to the audit trail without holding up the request.
 *
 * Fire-and-forget by design: the audit table lives on a slower replica-backed
 * volume and an audit hiccup must never fail or delay a user-facing request.
 * The returned promise ALWAYS resolves (failures are logged and counted here),
 * so callers write `void audit.record(...)` and do not await it.
 */
export function record(event: AuditEvent): Promise<void> {
  return eventRepository.insertAudit(event).catch((error: unknown) => {
    log.error({ err: error, type: event.type, subjectId: event.subjectId }, 'audit write failed');
  });
}
