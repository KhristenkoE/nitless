import { createHash } from 'node:crypto';
import type { Actor, Role } from '../domain/types.js';
import { queryOne, sql } from '../lib/db.js';

const hashToken = (token: string) => createHash('sha256').update(token).digest('hex');

export async function findActorBySession(token: string): Promise<Actor | undefined> {
  const row = await queryOne<{ id: string; role: Role }>(sql`
    SELECT u.id, u.role
    FROM sessions s JOIN users u ON u.id = s.user_id
    WHERE s.token_hash = ${hashToken(token)} AND s.expires_at > now()`);
  return row && { id: row.id, role: row.role };
}
