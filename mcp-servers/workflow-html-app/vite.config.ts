import { defineConfig } from 'vite';
import { viteSingleFile } from 'vite-plugin-singlefile';
import { resolve, dirname, relative, isAbsolute, sep } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
function resolveSafeOutDir(candidate: string) {
  const resolved = resolve(__dirname, candidate);
  const relativePath = relative(__dirname, resolved).split(sep).join('/');
  if (!relativePath || relativePath === '.' || relativePath.startsWith('../') || isAbsolute(relativePath)) {
    throw new Error('WORKFLOW_HTML_APP_UI_OUT_DIR must resolve under the package root');
  }
  if (relativePath === 'ui' || relativePath.startsWith('ui/')
    || relativePath === 'dist' || relativePath.startsWith('dist/')) {
    throw new Error(`WORKFLOW_HTML_APP_UI_OUT_DIR must not target source or published UI directories: ${relativePath}`);
  }
  const lastSegment = relativePath.split('/').at(-1) || '';
  if (!lastSegment.startsWith('.tmp-ui-')) {
    throw new Error('WORKFLOW_HTML_APP_UI_OUT_DIR must be a managed temp directory named .tmp-ui-*');
  }
  return resolved;
}

const outDir = resolveSafeOutDir(process.env.WORKFLOW_HTML_APP_UI_OUT_DIR || '.tmp-ui-build');
const entries = {
  'plan-viewer': resolve(__dirname, 'ui/plan-viewer.html'),
  'diagram-viewer': resolve(__dirname, 'ui/diagram-viewer.html'),
} as const;
const requestedEntry = process.env.WORKFLOW_HTML_APP_ENTRY;

if (requestedEntry && !(requestedEntry in entries)) {
  throw new Error(`Unknown WORKFLOW_HTML_APP_ENTRY: ${requestedEntry}`);
}

export default defineConfig({
  plugins: [viteSingleFile()],
  root: 'ui',
  build: {
    outDir,
    emptyOutDir: process.env.WORKFLOW_HTML_APP_KEEP_OUT_DIR !== '1',
    rollupOptions: {
      input: requestedEntry ? { [requestedEntry]: entries[requestedEntry as keyof typeof entries] } : entries,
    },
  },
});
