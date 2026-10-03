import pino from 'pino';

export const logger = pino({
  level: process.env.LOG_LEVEL ?? 'info',
  base: { service: 'bookings-api' },
  redact: ['req.headers.cookie', 'token'],
});
