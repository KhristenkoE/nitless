import { createApp } from './app.js';
import { logger } from './lib/logger.js';

const log = logger.child({ module: 'server' });
const port = Number(process.env.PORT ?? 4000);

createApp().listen(port, () => {
  log.info({ port }, 'bookings api listening');
});
