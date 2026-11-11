import { defineConfig } from 'astro/config';

// Fully static output: deployable to Vercel (or any static host) with no server and no adapter.
// `site` is only used for canonical links. Set SITE_URL once the real domain exists; until then Vercel's
// production URL is used when present, and no canonical link is emitted locally.
const site = process.env.SITE_URL
  ?? (process.env.VERCEL_PROJECT_PRODUCTION_URL ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}` : undefined);

export default defineConfig({ output: 'static', trailingSlash: 'always', site });
