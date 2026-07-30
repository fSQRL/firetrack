import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// En dev, servir public/<dossier>/index.html pour les URLs de dossier (ex. /analyse/),
// comme le fait nginx en prod, au lieu du fallback SPA de Vite.
function staticDirIndex() {
  return {
    name: 'static-dir-index',
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        const url = req.url.split('?')[0];
        if (url.endsWith('/') && url !== '/'
            && existsSync(join(server.config.publicDir, url, 'index.html'))) {
          req.url = url + 'index.html';
        }
        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), staticDirIndex()],
});
