import { mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { createApiServer, createStore } from './app.mjs';

const port = Number(process.env.PORT ?? 8787);
const databasePath = resolve(process.env.APP_DATABASE_PATH ?? './data/love-fueling-station.sqlite');
const sessionSecret = process.env.SESSION_SECRET;
const secureCookies = process.env.COOKIE_SECURE !== 'false';

if (!sessionSecret || sessionSecret.length < 32) {
  throw new Error('SESSION_SECRET must be configured with at least 32 characters.');
}

await mkdir(dirname(databasePath), { recursive: true });
const store = createStore({ databasePath });
const server = createApiServer({ store, sessionSecret, secureCookies });

server.listen(port, '0.0.0.0', () => {
  console.info(`Love Fueling Station API listening on :${port}`);
});

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.once(signal, () => server.close(() => {
    store.close();
    process.exit(0);
  }));
}
