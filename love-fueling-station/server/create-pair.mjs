import { mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { createStore } from './app.mjs';

const databasePath = resolve(process.env.APP_DATABASE_PATH ?? './data/love-fueling-station.sqlite');
const appOrigin = (process.env.APP_ORIGIN ?? 'https://example.com').replace(/\/$/, '');
const expiresInDays = Number(process.env.INVITATION_EXPIRES_IN_DAYS ?? 7);

if (!Number.isInteger(expiresInDays) || expiresInDays < 1 || expiresInDays > 30) {
  throw new Error('INVITATION_EXPIRES_IN_DAYS must be an integer from 1 to 30.');
}

await mkdir(dirname(databasePath), { recursive: true });
const store = createStore({ databasePath });
const pair = store.createInvitationPair({ expiresInDays });

console.info('Send each link only to the intended person. Each link is single-use.');
console.info(`Wife invitation: ${appOrigin}/?invite=${encodeURIComponent(pair.wifeToken)}`);
console.info(`Husband invitation: ${appOrigin}/?invite=${encodeURIComponent(pair.husbandToken)}`);
console.info(`Expires at: ${pair.expiresAt}`);
store.close();
