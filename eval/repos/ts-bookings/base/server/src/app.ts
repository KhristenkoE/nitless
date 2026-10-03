import cookieParser from 'cookie-parser';
import express from 'express';
import { errorHandler } from './lib/http.js';
import { router } from './routes.js';

export function createApp() {
  const app = express();
  app.disable('x-powered-by');
  app.use(express.json({ limit: '100kb' }));
  app.use(cookieParser());
  app.get('/healthz', (_req, res) => {
    res.json({ ok: true });
  });
  app.use('/api', router);
  app.use(errorHandler);
  return app;
}
