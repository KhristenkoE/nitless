import pg from 'pg';
import { logger } from './logger.js';

const log = logger.child({ module: 'db' });

/**
 * A SQL fragment built with the `sql` tag. Interpolated values become bind
 * parameters ($1, $2, ...); interpolated fragments are inlined. Never build SQL
 * with string concatenation.
 */
export class Sql {
  constructor(
    readonly strings: readonly string[],
    readonly values: readonly unknown[],
  ) {}
}

export function sql(strings: TemplateStringsArray, ...values: unknown[]): Sql {
  return new Sql([...strings], values);
}

export const emptySql = new Sql([''], []);

export function compile(fragment: Sql): { text: string; values: unknown[] } {
  const values: unknown[] = [];
  const render = (f: Sql): string =>
    f.strings.reduce((text, part, i) => {
      if (i === 0) return part;
      const value = f.values[i - 1];
      if (value instanceof Sql) return text + render(value) + part;
      values.push(value);
      return `${text}$${values.length}${part}`;
    }, '');
  return { text: render(fragment), values };
}

const pool = new pg.Pool({
  connectionString: process.env.DATABASE_URL,
  max: Number(process.env.DB_POOL_SIZE ?? 10),
});

pool.on('error', (error) => log.error({ err: error }, 'idle client error'));

export async function query<T>(fragment: Sql): Promise<T[]> {
  const { text, values } = compile(fragment);
  const started = performance.now();
  const result = await pool.query(text, values);
  log.debug({ ms: Math.round(performance.now() - started), rows: result.rowCount }, 'query');
  return result.rows as T[];
}

export async function queryOne<T>(fragment: Sql): Promise<T | undefined> {
  const rows = await query<T>(fragment);
  return rows[0];
}
