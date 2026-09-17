import { copyFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const frontend = path.resolve(root, '../../apps/frontend');
await mkdir(path.join(root, 'app/generated'), { recursive: true });
await mkdir(path.join(root, 'public/clue'), { recursive: true });
await copyFile(path.join(frontend, 'packages/design-system/generated/tokens.css'), path.join(root, 'app/generated/tokens.css'));
for (const weight of ['regular', 'medium']) {
  await copyFile(path.join(frontend, `public/fonts/satoshi-${weight}.woff2`), path.join(root, `public/clue/satoshi-${weight}.woff2`));
}
await copyFile(path.join(frontend, 'public/logos/clue-sidebar.svg'), path.join(root, 'public/clue/logo.svg'));
console.log('Copied the current Clue tokens and local brand fonts into the isolated prototype.');
